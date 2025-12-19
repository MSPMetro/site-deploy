#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv


@dataclass(frozen=True)
class ManifestFile:
    path: str
    hash: str
    size: int


def utc_version() -> str:
    # Match the existing snapshot naming style seen on servers:
    # 2025-12-17T08:29:45.585118Z
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256_hex(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def iter_files(site_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in site_dir.rglob("*"):
        if p.is_file():
            files.append(p)
    return sorted(files)


def guess_content_type(key: str) -> str:
    ct, _ = mimetypes.guess_type(key)
    return ct or "application/octet-stream"


def s3_client(endpoint_url: str | None, region: str, addressing_style: str) -> boto3.client:
    # S3-compatible services often need signature v4.
    cfg = Config(signature_version="s3v4", s3={"addressing_style": addressing_style})
    return boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region, config=cfg)


def object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def ensure_object_acl(s3, bucket: str, key: str, acl: str) -> None:
    try:
        s3.put_object_acl(Bucket=bucket, Key=key, ACL=acl)
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code") or ""
        msg = (e.response.get("Error") or {}).get("Message") or ""
        acl_unsupported = (
            code in {"AccessControlListNotSupported", "InvalidRequest", "NotImplemented", "AccessDenied"}
            or "acl" in msg.lower()
        )
        if acl_unsupported:
            return
        raise


def upload_file(
    s3,
    bucket: str,
    key: str,
    path: Path,
    *,
    cache_control: str,
    acl: str | None,
) -> None:
    extra: dict[str, object] = {
        "ContentType": guess_content_type(key),
        "CacheControl": cache_control,
    }
    if acl:
        extra["ACL"] = acl

    try:
        with path.open("rb") as f:
            s3.put_object(Bucket=bucket, Key=key, Body=f, **extra)
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code") or ""
        msg = (e.response.get("Error") or {}).get("Message") or ""
        acl_unsupported = code in {"AccessControlListNotSupported", "InvalidRequest", "AccessDenied"} or "acl" in msg.lower()
        if acl and acl_unsupported:
            extra.pop("ACL", None)
            with path.open("rb") as f:
                s3.put_object(Bucket=bucket, Key=key, Body=f, **extra)
            return
        raise


def upload_bytes(
    s3,
    bucket: str,
    key: str,
    body: bytes,
    *,
    content_type: str,
    cache_control: str,
    acl: str | None,
) -> None:
    extra: dict[str, object] = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
        "CacheControl": cache_control,
    }
    if acl:
        extra["ACL"] = acl

    try:
        s3.put_object(**extra)
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code") or ""
        msg = (e.response.get("Error") or {}).get("Message") or ""
        acl_unsupported = code in {"AccessControlListNotSupported", "InvalidRequest", "AccessDenied"} or "acl" in msg.lower()
        if acl and acl_unsupported:
            extra.pop("ACL", None)
            s3.put_object(**extra)
            return
        raise


def head_object_sha256(s3, bucket: str, key: str) -> str | None:
    try:
        r = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    meta = (r.get("Metadata") or {})
    sha = meta.get("sha256")
    return sha


def upload_site_tree(
    s3,
    bucket: str,
    site_dir: Path,
    *,
    acl: str | None,
) -> int:
    uploaded = 0
    for f in iter_files(site_dir):
        rel = f.relative_to(site_dir).as_posix()
        digest, _size = sha256_hex(f)

        # Cache policy: HTML and JSON should revalidate; static assets can be long-lived.
        if rel.endswith((".html", ".json")):
            cache_control = "no-cache, must-revalidate"
        elif rel.startswith("static/"):
            cache_control = "public, max-age=31536000, immutable"
        else:
            cache_control = "public, max-age=604800"

        existing = head_object_sha256(s3, bucket, rel)
        if existing == digest:
            continue

        extra: dict[str, object] = {
            "ContentType": guess_content_type(rel),
            "CacheControl": cache_control,
            "Metadata": {"sha256": digest},
        }
        if acl:
            extra["ACL"] = acl

        try:
            with f.open("rb") as fp:
                s3.put_object(Bucket=bucket, Key=rel, Body=fp, **extra)
        except ClientError as e:
            code = (e.response.get("Error") or {}).get("Code") or ""
            msg = (e.response.get("Error") or {}).get("Message") or ""
            acl_unsupported = code in {"AccessControlListNotSupported", "InvalidRequest", "AccessDenied"} or "acl" in msg.lower()
            if acl and acl_unsupported:
                extra.pop("ACL", None)
                with f.open("rb") as fp:
                    s3.put_object(Bucket=bucket, Key=rel, Body=fp, **extra)
            else:
                raise

        uploaded += 1

    return uploaded


def main() -> int:
    load_dotenv()

    ap = argparse.ArgumentParser(description="Publish a cityfeed manifest + objects to an S3-compatible bucket.")
    ap.add_argument("--site-dir", default="build/site", help="Directory containing the static site to publish.")
    ap.add_argument("--bucket", default=os.environ.get("S3_BUCKET", ""), help="S3 bucket name (or set S3_BUCKET).")
    ap.add_argument(
        "--endpoint-url",
        default=os.environ.get("S3_ENDPOINT_URL", ""),
        help="S3 endpoint URL (or set S3_ENDPOINT_URL). Leave empty for AWS.",
    )
    ap.add_argument("--region", default=os.environ.get("S3_REGION", "us-east-1"), help="S3 region (default us-east-1).")
    ap.add_argument(
        "--version",
        default=os.environ.get("PUBLISH_VERSION", ""),
        help="Manifest version string (defaults to current UTC timestamp). Also supports env PUBLISH_VERSION.",
    )
    ap.add_argument(
        "--origin-base-url",
        default=os.environ.get("ORIGIN_BASE_URL", ""),
        help="Public origin base URL for edges (printed only). Example: https://pull.s3.fr-par.scw.cloud",
    )
    ap.add_argument(
        "--addressing-style",
        default=os.environ.get("S3_ADDRESSING_STYLE", "auto"),
        choices=("auto", "virtual", "path"),
        help="S3 addressing style for boto3 (default: auto).",
    )
    ap.add_argument(
        "--allow-bucket-endpoint",
        action="store_true",
        default=os.environ.get("ALLOW_BUCKET_ENDPOINT", "").strip() == "1",
        help="Allow endpoint URLs that already include the bucket name (usually causes keys to be prefixed by the bucket name).",
    )
    ap.add_argument(
        "--object-acl",
        default=os.environ.get("S3_OBJECT_ACL", "public-read"),
        help="ACL to apply to uploaded objects (default: public-read). Set to 'none' to omit the ACL field.",
    )
    ap.add_argument(
        "--upload-site-tree",
        action="store_true",
        default=os.environ.get("PUBLISH_SITE_TREE", "").strip() == "1",
        help="Also upload the static site tree to normal paths (index.html, /static/...), so object storage/CDNs can serve the site directly.",
    )
    args = ap.parse_args()

    site_dir = Path(args.site_dir).resolve()
    if not site_dir.is_dir():
        raise SystemExit(f"site dir not found: {site_dir}")

    bucket = args.bucket.strip()
    if not bucket:
        raise SystemExit("missing bucket: pass --bucket or set S3_BUCKET")

    endpoint_url = args.endpoint_url.strip() or None
    region = args.region.strip() or "us-east-1"
    version = args.version.strip() or utc_version()
    if "/" in version or version.startswith(".") or version.endswith("."):
        raise SystemExit(f"invalid version (unsafe for S3 keys): {version!r}")
    acl = args.object_acl.strip()
    if not acl or acl.lower() == "none":
        acl = None

    files: list[ManifestFile] = []
    objects_to_upload: dict[str, Path] = {}

    for f in iter_files(site_dir):
        rel = f.relative_to(site_dir).as_posix()
        digest, size = sha256_hex(f)
        files.append(ManifestFile(path=rel, hash=digest, size=size))
        objects_to_upload.setdefault(digest, f)

    manifest = {"version": version, "files": [mf.__dict__ for mf in files]}
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")

    if endpoint_url:
        parsed = urlparse(endpoint_url)
        host = parsed.hostname or ""
        if host.startswith(f"{bucket}.") and not args.allow_bucket_endpoint:
            print(
                "\n".join(
                    [
                        "error: S3_ENDPOINT_URL appears to include the bucket name already.",
                        f"  bucket:      {bucket}",
                        f"  endpoint:    {endpoint_url}",
                        "",
                        "This commonly results in objects being written under a top-level prefix matching the bucket name,",
                        "e.g. `pull/objects/...` instead of `objects/...` (which breaks the cityfeed puller origin layout).",
                        "",
                        "Fix (use a base endpoint; keep the bucket separate):",
                        "",
                        "Scaleway example:",
                        "  S3_ENDPOINT_URL=https://s3.fr-par.scw.cloud",
                        f"  S3_BUCKET={bucket}",
                        f"  ORIGIN_BASE_URL=https://{bucket}.s3.fr-par.scw.cloud",
                        "",
                        "DigitalOcean Spaces example (region nyc3/sfo3/etc):",
                        "  S3_ENDPOINT_URL=https://REGION.digitaloceanspaces.com",
                        f"  S3_BUCKET={bucket}",
                        f"  ORIGIN_BASE_URL=https://REGION.digitaloceanspaces.com/{bucket}",
                        "",
                        "If you really intend to use a bucket-specific endpoint, re-run with --allow-bucket-endpoint.",
                    ]
                ),
                file=sys.stderr,
            )
            return 2

    s3 = s3_client(endpoint_url=endpoint_url, region=region, addressing_style=args.addressing_style)

    uploaded_objects = 0
    for digest, src_path in objects_to_upload.items():
        key = f"objects/{digest}"
        if object_exists(s3, bucket, key):
            if acl:
                ensure_object_acl(s3, bucket, key, acl)
            continue
        upload_file(s3, bucket, key, src_path, cache_control="public, max-age=31536000, immutable", acl=acl)
        uploaded_objects += 1

    upload_bytes(
        s3,
        bucket,
        "manifests/latest.json",
        manifest_bytes,
        content_type="application/json",
        cache_control="no-cache, must-revalidate",
        acl=acl,
    )
    upload_bytes(
        s3,
        bucket,
        f"manifests/{version}.json",
        manifest_bytes,
        content_type="application/json",
        cache_control="public, max-age=31536000, immutable",
        acl=acl,
    )

    uploaded_site = 0
    if args.upload_site_tree:
        uploaded_site = upload_site_tree(s3, bucket, site_dir, acl=acl)

    origin = args.origin_base_url.strip()
    if origin and not origin.startswith(("http://", "https://")):
        origin = f"https://{origin}"
    origin = origin.rstrip("/") if origin else ""

    if not origin and endpoint_url:
        parsed = urlparse(endpoint_url)
        if parsed.scheme and parsed.hostname:
            origin = f"{parsed.scheme}://{bucket}.{parsed.hostname}".rstrip("/")

    print(f"Published version: {version}")
    print(f"Files: {len(files)} (unique objects: {len(objects_to_upload)}, uploaded new: {uploaded_objects})")
    if args.upload_site_tree:
        print(f"Site tree: uploaded new/changed: {uploaded_site}")
    print(f"Bucket: {bucket}")
    if endpoint_url:
        print(f"Endpoint: {endpoint_url}")
    if origin:
        print(f"Origin for cityfeed-puller: {origin}")
    print("Manifest: manifests/latest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
