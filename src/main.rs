use std::ffi::OsStr;
use std::fs::{self, File};
use std::io::{self};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;

use anyhow::{anyhow, bail, Context, Result};
use clap::Parser;
use reqwest::blocking::Client;
use reqwest::Url;
use serde::Deserialize;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

#[derive(Parser, Debug)]
#[command(
    name = "cityfeed-puller",
    version,
    about = "Manifest-based static site puller"
)]
struct Args {
    #[arg(long = "origin", required = true, num_args = 1..)]
    origins: Vec<String>,

    #[arg(long, default_value = "/var/www/mspmetro")]
    root: PathBuf,
}

#[derive(Debug, Deserialize)]
struct Manifest {
    version: String,
    files: Vec<ManifestFile>,
}

#[derive(Debug, Deserialize)]
struct ManifestFile {
    path: String,
    hash: String,
    size: u64,
}

fn main() {
    if let Err(err) = run() {
        eprintln!("error: {err:#}");
        std::process::exit(1);
    }
}

fn run() -> Result<()> {
    let args = Args::parse();
    let origins = normalize_origins(&args.origins)?;
    let root = args.root;

    ensure_dir(&root).with_context(|| format!("create root dir {}", root.display()))?;

    let objects_dir = root.join("objects");
    let snapshots_dir = root.join("snapshots");
    let current_link = root.join("current");

    ensure_dir(&objects_dir).context("create objects dir")?;
    ensure_dir(&snapshots_dir).context("create snapshots dir")?;

    let client = Client::builder()
        .timeout(Duration::from_secs(120))
        .user_agent(concat!("cityfeed-puller/", env!("CARGO_PKG_VERSION")))
        .build()
        .context("build http client")?;

    let (manifest, manifest_origin) = fetch_manifest_any(&client, &origins)?;
    eprintln!(
        "manifest version={} files={}",
        manifest.version,
        manifest.files.len()
    );
    eprintln!("manifest origin={manifest_origin}");

    let snapshot_final = snapshots_dir.join(&manifest.version);
    if snapshot_final.exists() {
        let target_rel = PathBuf::from("snapshots").join(&manifest.version);
        if current_points_to(&current_link, &target_rel).unwrap_or(false) {
            eprintln!("snapshot already present and current already points to it");
            return Ok(());
        }
        switch_symlink_atomically(&current_link, &target_rel, &root)
            .context("switch current symlink")?;
        eprintln!(
            "snapshot already present; switched current -> {}",
            target_rel.display()
        );
        return Ok(());
    }

    for file in &manifest.files {
        let _ = validate_rel_path(&file.path)
            .with_context(|| format!("invalid manifest path: {}", file.path))?;

        let obj_path = objects_dir.join(&file.hash);
        if obj_path.exists() {
            continue;
        }

        eprintln!("download object hash={} size={}", file.hash, file.size);
        download_object_any(&client, &origins, &file.hash, file.size, &objects_dir)
            .with_context(|| format!("download object {}", file.hash))?;
    }

    let staging = tempfile::Builder::new()
        .prefix(&format!(".{}.staging-", sanitize_prefix(&manifest.version)))
        .tempdir_in(&snapshots_dir)
        .context("create staging snapshot dir")?;

    for file in &manifest.files {
        let rel_path = validate_rel_path(&file.path)
            .with_context(|| format!("invalid manifest path: {}", file.path))?;

        let src_obj = objects_dir.join(&file.hash);
        if !src_obj.exists() {
            bail!(
                "missing required object after download: {}",
                src_obj.display()
            );
        }
        let actual_size = fs::metadata(&src_obj)
            .with_context(|| format!("stat {}", src_obj.display()))?
            .len();
        if actual_size != file.size {
            bail!(
                "object {} size mismatch on disk: expected {} got {}",
                file.hash,
                file.size,
                actual_size
            );
        }

        let dst = staging.path().join(&rel_path);
        if let Some(parent) = dst.parent() {
            ensure_dir(parent).with_context(|| format!("create dir {}", parent.display()))?;
        }

        if dst.exists() {
            bail!("snapshot destination already exists: {}", dst.display());
        }
        copy_file_atomic(&src_obj, &dst)
            .with_context(|| format!("copy {} -> {}", src_obj.display(), dst.display()))?;
    }

    let staging_path = staging.keep();
    fs::rename(&staging_path, &snapshot_final).with_context(|| {
        format!(
            "promote snapshot {} -> {}",
            staging_path.display(),
            snapshot_final.display()
        )
    })?;
    fsync_dir(&snapshots_dir).context("fsync snapshots dir")?;

    let target_rel = PathBuf::from("snapshots").join(&manifest.version);
    switch_symlink_atomically(&current_link, &target_rel, &root)
        .context("switch current symlink")?;

    eprintln!("switched current -> {}", target_rel.display());
    Ok(())
}

fn current_points_to(current: &Path, target_rel: &Path) -> Result<bool> {
    match fs::read_link(current) {
        Ok(link) => Ok(link == target_rel),
        Err(err) if err.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(err) => Err(err).with_context(|| format!("readlink {}", current.display())),
    }
}

fn normalize_origin(origin: &str) -> Result<String> {
    let trimmed = origin.trim();
    if trimmed.is_empty() {
        bail!("--origin must not be empty");
    }
    let normalized = trimmed.trim_end_matches('/');
    let url =
        Url::parse(normalized).context("parse --origin as URL (include http:// or https://)")?;
    match url.scheme() {
        "http" | "https" => {}
        other => bail!("unsupported --origin scheme: {other}"),
    }
    Ok(normalized.to_string())
}

fn normalize_origins(origins: &[String]) -> Result<Vec<String>> {
    if origins.is_empty() {
        bail!("at least one --origin is required");
    }
    let mut out: Vec<String> = Vec::new();
    for origin in origins {
        let normalized = normalize_origin(origin)?;
        if !out.iter().any(|x| x == &normalized) {
            out.push(normalized);
        }
    }
    Ok(out)
}

fn manifest_url(origin: &str) -> String {
    format!("{origin}/manifests/latest.json")
}

fn object_url(origin: &str, hash: &str) -> String {
    format!("{origin}/objects/{hash}")
}

fn fetch_manifest(client: &Client, origin: &str) -> Result<Manifest> {
    let url = manifest_url(origin);
    let resp = client
        .get(url)
        .send()
        .map_err(|e| augment_reqwest_error(e, origin))
        .context("request latest manifest")?;
    let resp = ensure_success(resp).context("latest manifest http status")?;
    let manifest: Manifest = serde_json::from_reader(resp).context("parse latest.json")?;
    if manifest.version.trim().is_empty() {
        bail!("manifest version is empty");
    }
    Ok(manifest)
}

fn fetch_manifest_any(client: &Client, origins: &[String]) -> Result<(Manifest, String)> {
    let mut last_err: Option<anyhow::Error> = None;
    for origin in origins {
        match fetch_manifest(client, origin) {
            Ok(manifest) => return Ok((manifest, origin.clone())),
            Err(err) => {
                eprintln!("warn: frontpage fetch failed from {origin}: {err:#}");
                last_err = Some(err);
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow!("no origins configured")))
        .context("fetch latest manifest from all origins")
}

fn download_object(
    client: &Client,
    origin: &str,
    hash: &str,
    expected_size: u64,
    objects: &Path,
) -> Result<()> {
    if hash.is_empty() || hash.contains('/') || hash.contains('\\') {
        bail!("invalid object hash: {hash}");
    }

    let url = object_url(origin, hash);
    let resp = client
        .get(url)
        .send()
        .map_err(|e| augment_reqwest_error(e, origin))
        .with_context(|| format!("request object {hash}"))?;
    let mut resp = ensure_success(resp).with_context(|| format!("object {hash} http status"))?;

    let mut tmp = tempfile::NamedTempFile::new_in(objects).context("create temp object file")?;
    let written = io::copy(&mut resp, &mut tmp).context("write object body")?;

    if expected_size != written {
        bail!("object {hash} size mismatch: expected {expected_size} got {written}");
    }

    tmp.as_file_mut()
        .sync_all()
        .context("fsync object temp file")?;
    let final_path = objects.join(hash);

    match tmp.persist_noclobber(&final_path) {
        Ok(_file) => {}
        Err(err) => {
            if err.error.kind() == io::ErrorKind::AlreadyExists {
                return Ok(());
            }
            return Err(err.error)
                .with_context(|| format!("persist object {}", final_path.display()));
        }
    }

    set_world_readable(&final_path).context("chmod object")?;
    fsync_dir(objects).context("fsync objects dir")?;
    Ok(())
}

fn download_object_any(
    client: &Client,
    origins: &[String],
    hash: &str,
    expected_size: u64,
    objects: &Path,
) -> Result<()> {
    let mut last_err: Option<anyhow::Error> = None;
    for origin in origins {
        match download_object(client, origin, hash, expected_size, objects) {
            Ok(()) => return Ok(()),
            Err(err) => {
                eprintln!("warn: object download failed from {origin} hash={hash}: {err:#}");
                last_err = Some(err);
            }
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow!("no origins configured")))
        .with_context(|| format!("download object {hash} from all origins"))
}

fn copy_file_atomic(src: &Path, dst: &Path) -> Result<()> {
    let parent = dst
        .parent()
        .ok_or_else(|| anyhow!("destination has no parent: {}", dst.display()))?;

    let mut tmp = tempfile::NamedTempFile::new_in(parent).context("create temp snapshot file")?;
    let mut src_f = File::open(src).with_context(|| format!("open {}", src.display()))?;
    io::copy(&mut src_f, &mut tmp).context("copy bytes")?;
    tmp.as_file_mut()
        .sync_all()
        .context("fsync snapshot temp file")?;

    match tmp.persist_noclobber(dst) {
        Ok(_file) => {}
        Err(err) => return Err(err.error).with_context(|| format!("persist {}", dst.display())),
    }

    set_world_readable(dst).context("chmod snapshot file")?;
    fsync_dir(parent).with_context(|| format!("fsync dir {}", parent.display()))?;
    Ok(())
}

fn set_world_readable(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        let mut perms = fs::metadata(path)
            .with_context(|| format!("stat {}", path.display()))?
            .permissions();
        // Readable by everyone, writable only by owner.
        perms.set_mode(0o644);
        fs::set_permissions(path, perms).with_context(|| format!("chmod {}", path.display()))?;
        return Ok(());
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Ok(())
    }
}

fn validate_rel_path(path_str: &str) -> Result<PathBuf> {
    if path_str.is_empty() {
        bail!("path is empty");
    }
    let path = Path::new(path_str);
    let mut out = PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::Normal(part) => {
                if part == OsStr::new("") || part == OsStr::new(".") {
                    bail!("invalid path component");
                }
                out.push(part);
            }
            _ => bail!("path must be relative and must not contain '..'"),
        }
    }
    if out.as_os_str().is_empty() {
        bail!("path resolves to empty");
    }
    Ok(out)
}

fn ensure_dir(path: &Path) -> Result<()> {
    fs::create_dir_all(path).with_context(|| format!("create_dir_all {}", path.display()))
}

fn fsync_dir(dir: &Path) -> Result<()> {
    let file = File::open(dir).with_context(|| format!("open dir {}", dir.display()))?;
    file.sync_all()
        .with_context(|| format!("fsync dir {}", dir.display()))
}

fn switch_symlink_atomically(current: &Path, target_rel: &Path, root: &Path) -> Result<()> {
    #[cfg(not(unix))]
    {
        let _ = (current, target_rel, root);
        bail!("symlink switching is only implemented for unix platforms");
    }

    #[cfg(unix)]
    {
        use std::os::unix::fs as unix_fs;

        let tmp_name = format!(".current.new.{}", std::process::id());
        let tmp_link = root.join(tmp_name);

        let _ = fs::remove_file(&tmp_link);
        unix_fs::symlink(target_rel, &tmp_link).with_context(|| {
            format!(
                "create symlink {} -> {}",
                tmp_link.display(),
                target_rel.display()
            )
        })?;

        fs::rename(&tmp_link, current).with_context(|| {
            format!(
                "rename symlink {} -> {}",
                tmp_link.display(),
                current.display()
            )
        })?;

        fsync_dir(root).context("fsync root dir")?;
        Ok(())
    }
}

fn sanitize_prefix(s: &str) -> String {
    s.chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect()
}

fn ensure_success(resp: reqwest::blocking::Response) -> Result<reqwest::blocking::Response> {
    let status = resp.status();
    let url = resp.url().to_string();
    if status.is_success() {
        return Ok(resp);
    }
    let mut body = resp.text().unwrap_or_default();
    body = body.replace('\n', " ").replace('\r', " ");
    if body.len() > 2000 {
        body.truncate(2000);
        body.push_str("…");
    }
    bail!("HTTP {status} for {url}: {body}");
}

fn augment_reqwest_error(err: reqwest::Error, origin: &str) -> anyhow::Error {
    let msg = err.to_string();
    if err.is_connect() && msg.contains("certificate not valid for name") {
        if let Some(hint) = tls_name_mismatch_hint(origin) {
            return anyhow!(err).context(hint);
        }
    }
    anyhow!(err)
}

fn tls_name_mismatch_hint(origin: &str) -> Option<String> {
    let url = Url::parse(origin).ok()?;
    if url.scheme() != "https" {
        return None;
    }
    let host = url.host_str()?;
    let parts: Vec<&str> = host.split('.').collect();
    let (idx, endpoint_head) = if let Some(i) = parts.iter().position(|p| *p == "s3") {
        (i, "s3")
    } else if let Some(i) = parts.iter().position(|p| *p == "s3-website") {
        (i, "s3")
    } else {
        return None;
    };
    if idx <= 1 {
        return None;
    }
    let bucket = parts[..idx].join(".");
    let endpoint = std::iter::once(endpoint_head)
        .chain(parts.iter().skip(idx + 1).copied())
        .collect::<Vec<_>>()
        .join(".");
    Some(format!(
        "Try path-style origin for dotted bucket names, e.g. `https://{endpoint}/{bucket}`"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validate_rel_path_rejects_absolute_and_parent() {
        assert!(validate_rel_path("/etc/passwd").is_err());
        assert!(validate_rel_path("../x").is_err());
        assert!(validate_rel_path("a/../../b").is_err());
    }

    #[test]
    fn validate_rel_path_accepts_simple() {
        let p = validate_rel_path("index.html").unwrap();
        assert_eq!(p, PathBuf::from("index.html"));

        let p = validate_rel_path("a/b/c.txt").unwrap();
        assert_eq!(p, PathBuf::from("a/b/c.txt"));

        let p = validate_rel_path("a/./b").unwrap();
        assert_eq!(p, PathBuf::from("a/b"));
    }

    #[test]
    fn normalize_origin_trims_and_rejects_bad_schemes() {
        assert_eq!(
            normalize_origin(" https://example.com/ ").unwrap(),
            "https://example.com"
        );
        assert!(normalize_origin("").is_err());
        assert!(normalize_origin("ftp://example.com").is_err());
        assert!(normalize_origin("not a url").is_err());
    }

    #[test]
    fn tls_name_mismatch_hint_for_dotted_bucket() {
        let hint = tls_name_mismatch_hint("https://foo.bar.s3.fr-par.scw.cloud").unwrap();
        assert!(hint.contains("path-style origin"));
        assert!(hint.contains("https://s3.fr-par.scw.cloud/foo.bar"));
        assert!(tls_name_mismatch_hint("http://foo.bar.s3.fr-par.scw.cloud").is_none());
        assert!(tls_name_mismatch_hint("https://puller.s3.fr-par.scw.cloud").is_none());
    }
}
