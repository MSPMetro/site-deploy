#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass


API_BASE = "https://api.digitalocean.com/v2"


def _token() -> str:
    t = (os.environ.get("DIGITALOCEAN_ACCESS_TOKEN") or os.environ.get("DO_API_TOKEN") or "").strip()
    if not t:
        raise SystemExit(
            "missing DigitalOcean API token: set DIGITALOCEAN_ACCESS_TOKEN (recommended) or DO_API_TOKEN"
        )
    return t


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes


def do_request(method: str, path: str, *, payload: dict | None = None) -> HttpResult:
    token = _token()
    url = f"{API_BASE}{path}"
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "mspmetro-cityfeed/do_cdn.py",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return HttpResult(status=resp.status, body=resp.read())
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        return HttpResult(status=getattr(e, "code", 0) or 0, body=body)
    except Exception as e:
        raise SystemExit(f"request failed: {method} {url}: {e}") from e


def parse_json(res: HttpResult) -> dict:
    if not res.body:
        return {}
    try:
        return json.loads(res.body.decode("utf-8"))
    except Exception:
        return {"_raw": res.body.decode("utf-8", errors="replace")}


def require_ok(res: HttpResult, *, context: str) -> dict:
    if 200 <= res.status < 300:
        return parse_json(res)
    j = parse_json(res)
    msg = j.get("message") if isinstance(j, dict) else None
    rid = j.get("request_id") if isinstance(j, dict) else None
    extra = []
    if msg:
        extra.append(msg)
    if rid:
        extra.append(f"request_id={rid}")
    extra_s = f" ({'; '.join(extra)})" if extra else ""
    raise SystemExit(f"{context} failed: http {res.status}{extra_s}")


def list_endpoints() -> list[dict]:
    return require_ok(do_request("GET", "/cdn/endpoints"), context="list cdn endpoints").get("endpoints") or []


def find_endpoint_by_origin(origin: str) -> dict:
    origin = origin.strip()
    if not origin:
        raise SystemExit("origin is required")
    for e in list_endpoints():
        if (e.get("origin") or "") == origin:
            return e
    raise SystemExit(f"cdn endpoint not found for origin: {origin}")


def update_endpoint(endpoint_id: str, *, origin: str, ttl: int, custom_domain: str | None, certificate_id: str | None) -> dict:
    payload: dict[str, object] = {"origin": origin, "ttl": ttl}
    if custom_domain is not None:
        payload["custom_domain"] = custom_domain
    if certificate_id is not None:
        payload["certificate_id"] = certificate_id
    return require_ok(do_request("PUT", f"/cdn/endpoints/{endpoint_id}", payload=payload), context="update cdn endpoint")


def purge_cache(endpoint_id: str, *, files: list[str] | None) -> None:
    payload = {"files": files or ["*"]}
    require_ok(do_request("DELETE", f"/cdn/endpoints/{endpoint_id}/cache", payload=payload), context="purge cdn cache")


def create_le_cert(*, name: str, dns_names: list[str]) -> dict:
    payload = {"name": name, "type": "lets_encrypt", "dns_names": dns_names}
    res = do_request("POST", "/certificates", payload=payload)
    if 200 <= res.status < 300:
        return parse_json(res).get("certificate") or {}

    j = parse_json(res)
    msg = (j.get("message") or "").lower() if isinstance(j, dict) else ""
    if "failed to find related domains" in msg:
        raise SystemExit(
            "DigitalOcean couldn't issue a managed (Let's Encrypt) certificate for that hostname because the apex domain "
            "is not managed in this DigitalOcean account.\n"
            "\n"
            "Fix options:\n"
            "1) Move the apex domain into DigitalOcean DNS (Domains) and retry, or\n"
            "2) Generate a cert elsewhere (e.g. Caddy/certbot) and upload it as a custom certificate, then attach it.\n"
        )
    raise SystemExit(f"create LE certificate failed: http {res.status} ({j.get('message') if isinstance(j, dict) else ''})")


def create_custom_cert(*, name: str, leaf_pem: str, key_pem: str, chain_pem: str | None) -> dict:
    payload: dict[str, object] = {
        "name": name,
        "type": "custom",
        "private_key": key_pem,
        "leaf_certificate": leaf_pem,
    }
    if chain_pem:
        payload["certificate_chain"] = chain_pem
    return require_ok(do_request("POST", "/certificates", payload=payload), context="create custom certificate").get("certificate") or {}


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def cmd_list(args: argparse.Namespace) -> int:
    eps = list_endpoints()
    if args.json:
        print(json.dumps({"endpoints": eps}, indent=2, sort_keys=True))
        return 0

    for e in eps:
        print(
            "\t".join(
                [
                    e.get("id") or "",
                    e.get("origin") or "",
                    e.get("endpoint") or "",
                    e.get("custom_domain") or "",
                ]
            )
        )
    return 0


def cmd_set_domain(args: argparse.Namespace) -> int:
    if args.endpoint_id:
        ep = require_ok(do_request("GET", f"/cdn/endpoints/{args.endpoint_id}"), context="get cdn endpoint").get("endpoint") or {}
    else:
        ep = find_endpoint_by_origin(args.origin)

    endpoint_id = ep.get("id") or ""
    origin = ep.get("origin") or ""
    if not endpoint_id or not origin:
        raise SystemExit("could not determine endpoint_id/origin")

    cert_id = args.certificate_id
    if args.le_cert_name:
        cert = create_le_cert(name=args.le_cert_name, dns_names=[args.custom_domain])
        cert_id = cert.get("id")
    if args.custom_cert_name:
        leaf = _read_text(args.custom_cert_leaf)
        key = _read_text(args.custom_cert_key)
        chain = _read_text(args.custom_cert_chain) if args.custom_cert_chain else None
        cert = create_custom_cert(name=args.custom_cert_name, leaf_pem=leaf, key_pem=key, chain_pem=chain)
        cert_id = cert.get("id")

    if not cert_id:
        raise SystemExit(
            "missing certificate id: provide --certificate-id, or use --le-cert-name, or use --custom-cert-name/--custom-cert-leaf/--custom-cert-key"
        )

    updated = update_endpoint(
        endpoint_id,
        origin=origin,
        ttl=int(args.ttl),
        custom_domain=args.custom_domain,
        certificate_id=cert_id,
    )
    print(json.dumps(updated, indent=2, sort_keys=True))
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    if args.endpoint_id:
        ep_id = args.endpoint_id
    else:
        ep_id = (find_endpoint_by_origin(args.origin).get("id") or "").strip()
    if not ep_id:
        raise SystemExit("could not determine endpoint_id")
    purge_cache(ep_id, files=args.files)
    print("OK")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Manage DigitalOcean CDN endpoints for MSPMetro.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List CDN endpoints")
    p_list.add_argument("--json", action="store_true", help="Print JSON")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set-domain", help="Set CDN custom domain + certificate")
    p_set.add_argument("--origin", help="Origin hostname (e.g. origin-do.sfo3.digitaloceanspaces.com)")
    p_set.add_argument("--endpoint-id", help="CDN endpoint id (alternative to --origin)")
    p_set.add_argument("--custom-domain", required=True, help="Custom domain to serve (e.g. origin-do.mspmetro.com)")
    p_set.add_argument("--ttl", default="3600", help="TTL seconds (default 3600)")

    group = p_set.add_mutually_exclusive_group(required=False)
    group.add_argument("--certificate-id", help="Existing DO certificate id to attach")
    group.add_argument("--le-cert-name", help="Create a managed (Let's Encrypt) certificate with this name and attach it")
    group.add_argument("--custom-cert-name", help="Upload a custom certificate with this name and attach it")

    p_set.add_argument("--custom-cert-leaf", help="Path to leaf certificate PEM (required with --custom-cert-name)")
    p_set.add_argument("--custom-cert-key", help="Path to private key PEM (required with --custom-cert-name)")
    p_set.add_argument("--custom-cert-chain", help="Path to chain PEM (optional with --custom-cert-name)")
    p_set.set_defaults(func=cmd_set_domain)

    p_purge = sub.add_parser("purge", help="Purge CDN cache")
    p_purge.add_argument("--origin", help="Origin hostname (e.g. origin-do.sfo3.digitaloceanspaces.com)")
    p_purge.add_argument("--endpoint-id", help="CDN endpoint id (alternative to --origin)")
    p_purge.add_argument("--files", nargs="*", help="Files to purge (default: all)")
    p_purge.set_defaults(func=cmd_purge)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.cmd in {"set-domain", "purge"} and not (getattr(args, "origin", None) or getattr(args, "endpoint_id", None)):
        raise SystemExit("provide --origin or --endpoint-id")

    if getattr(args, "custom_cert_name", None):
        if not args.custom_cert_leaf or not args.custom_cert_key:
            raise SystemExit("--custom-cert-leaf and --custom-cert-key are required with --custom-cert-name")

    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
