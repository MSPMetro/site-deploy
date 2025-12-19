#[cfg(unix)]
mod unix_only {
    use std::collections::HashMap;
    use std::fs;
    use std::io::Write;
    use std::net::{TcpListener, TcpStream};
    use std::process::Command;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::thread;

    use tiny_http::{Header, Response, Server, StatusCode};

    fn send_quit(addr: std::net::SocketAddr) {
        if let Ok(mut stream) = TcpStream::connect(addr) {
            let _ = stream.write_all(b"GET /__quit HTTP/1.1\r\nHost: localhost\r\n\r\n");
        }
    }

    fn start_origin(
        version: &str,
        manifest_bytes: Vec<u8>,
        objects: HashMap<String, Vec<u8>>,
        manifest_hits: Arc<AtomicUsize>,
        object_hits: Arc<AtomicUsize>,
    ) -> (std::net::SocketAddr, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let server = Server::from_listener(listener, None).unwrap();
        let addr = server.server_addr().to_ip().unwrap();

        let version = version.to_string();
        let handle = thread::spawn(move || {
            for req in server.incoming_requests() {
                let url = req
                    .url()
                    .split('?')
                    .next()
                    .unwrap_or(req.url())
                    .to_string();
                match url.as_str() {
                    "/__quit" => {
                        let _ = req.respond(Response::empty(200));
                        break;
                    }
                    "/manifests/latest.json" => {
                        manifest_hits.fetch_add(1, Ordering::SeqCst);
                        let mut resp = Response::from_data(manifest_bytes.clone());
                        resp.add_header(
                            Header::from_bytes(&b"Content-Type"[..], &b"application/json"[..])
                                .unwrap(),
                        );
                        let _ = req.respond(resp);
                    }
                    _ => {
                        if let Some(hash) = url.strip_prefix("/objects/") {
                            if let Some(bytes) = objects.get(hash) {
                                object_hits.fetch_add(1, Ordering::SeqCst);
                                let mut resp = Response::from_data(bytes.clone());
                                resp.add_header(
                                    Header::from_bytes(
                                        &b"Content-Type"[..],
                                        &b"application/octet-stream"[..],
                                    )
                                    .unwrap(),
                                );
                                let _ = req.respond(resp);
                                continue;
                            }
                        }
                        let _ = req.respond(Response::empty(StatusCode(404)));
                        eprintln!(
                            "[test origin] 404 {} (version={})",
                            url.as_str(),
                            version.as_str()
                        );
                    }
                }
            }
        });

        (addr, handle)
    }

    #[test]
    fn puller_fetches_objects_builds_snapshot_and_switches_current() {
        let version = "v-test-1";
        let hash = "hash1";
        let obj = b"hello world".to_vec();

        let manifest = format!(
            r#"{{
  "version": "{version}",
  "files": [
    {{ "path": "index.html", "hash": "{hash}", "size": {} }}
  ]
}}"#,
            obj.len()
        );
        let manifest_bytes = manifest.as_bytes().to_vec();

        let mut objects = HashMap::new();
        objects.insert(hash.to_string(), obj.clone());

        let manifest_hits = Arc::new(AtomicUsize::new(0));
        let object_hits = Arc::new(AtomicUsize::new(0));
        let (addr, handle) = start_origin(
            version,
            manifest_bytes,
            objects,
            Arc::clone(&manifest_hits),
            Arc::clone(&object_hits),
        );
        let origin = format!("http://{addr}");

        let root = tempfile::tempdir().unwrap();
        let bin = env!("CARGO_BIN_EXE_cityfeed-puller");

        let status = Command::new(bin)
            .arg("--origin")
            .arg(&origin)
            .arg("--root")
            .arg(root.path())
            .status()
            .unwrap();
        assert!(status.success());

        let objects_dir = root.path().join("objects");
        let snapshots_dir = root.path().join("snapshots");
        let current = root.path().join("current");

        assert_eq!(fs::read(objects_dir.join(hash)).unwrap(), obj);
        assert_eq!(
            fs::read(snapshots_dir.join(version).join("index.html")).unwrap(),
            obj
        );
        assert_eq!(
            fs::read_link(&current).unwrap(),
            std::path::PathBuf::from("snapshots").join(version)
        );

        // Second run should short-circuit once it sees the snapshot already exists.
        let status2 = Command::new(bin)
            .arg("--origin")
            .arg(&origin)
            .arg("--root")
            .arg(root.path())
            .status()
            .unwrap();
        assert!(status2.success());

        send_quit(addr);
        handle.join().unwrap();

        assert!(manifest_hits.load(Ordering::SeqCst) >= 2);
        assert_eq!(object_hits.load(Ordering::SeqCst), 1);
    }
}
