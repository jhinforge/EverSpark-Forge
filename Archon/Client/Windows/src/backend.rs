use crate::platform::Job;
use serde::Deserialize;
use std::{
    fs::{self, OpenOptions},
    io::{self, Write},
    os::windows::{io::AsRawHandle, process::CommandExt},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicBool, Ordering},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

#[derive(Deserialize)]
struct Ready {
    pid: u32,
    nonce: String,
    url: String,
}

pub struct Backend {
    child: Child,
    _job: Job,
    ready: PathBuf,
    pub url: String,
}

impl Backend {
    pub fn launch(root: &Path, quitting: &AtomicBool) -> Result<Self, String> {
        let python = root.join("Runtime/Python/python.exe");
        let entry = root.join("Archon/Client/Windows/backend.py");
        if !python.is_file() || !entry.is_file() {
            return Err("找不到便携 Python 或源码。请完整解压发布 ZIP；Git 源码请先运行打包脚本。\nPortable Python or source is missing. Extract the entire release ZIP.".into());
        }
        let directory = root.join("Data/Runtime");
        fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
        let nonce = format!(
            "{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        );
        let ready = directory.join(format!("desktop-{nonce}.json"));
        let logs = root.join("Data/Logs/client");
        fs::create_dir_all(&logs).map_err(|e| e.to_string())?;
        let output = OpenOptions::new()
            .create(true)
            .append(true)
            .open(logs.join("backend.log"))
            .map_err(|e| e.to_string())?;
        let job = Job::new().map_err(|e| format!("Cannot create backend process Job: {e}"))?;
        let mut child = Command::new(python)
            .arg("-I")
            .args(["-X", "utf8"])
            .arg("-u")
            .arg(entry)
            .arg("--ready-file")
            .arg(&ready)
            .arg("--nonce")
            .arg(&nonce)
            .current_dir(root)
            .env("PYTHONUTF8", "1")
            .env("EVERSPARK_ORCHESTRATOR_PORT", "0")
            .env("EVERSPARK_WEBUI_PORT", "0")
            .env("EVERSPARK_REMOTE_ORCHESTRATOR_PORT", "0")
            .env("EVERSPARK_LOG_DIR", root.join("Data/Logs"))
            .stdin(Stdio::piped())
            .stdout(Stdio::from(output.try_clone().map_err(|e| e.to_string())?))
            .stderr(Stdio::from(output))
            .creation_flags(0x08000000)
            .spawn()
            .map_err(|e| e.to_string())?;
        if let Err(error) = job.assign(child.as_raw_handle()) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("Cannot own backend process: {error}"));
        }
        let mut backend = Self {
            child,
            _job: job,
            ready,
            url: String::new(),
        };
        backend
            .child
            .stdin
            .as_mut()
            .ok_or("Backend input is unavailable")?
            .write_all(b"start\n")
            .map_err(|e| e.to_string())?;
        let deadline = Instant::now() + Duration::from_secs(60);
        loop {
            if quitting.load(Ordering::Relaxed) {
                return Err("Startup cancelled".into());
            }
            if let Some(code) = backend.child.try_wait().map_err(|e| e.to_string())? {
                return Err(format!("主机启动失败（{code}）。端口可能被命令行实例占用，请查看日志。\nBackend exited before readiness. Check the log and any running CLI instance."));
            }
            if let Ok(data) = fs::read(&backend.ready) {
                if let Ok(state) = serde_json::from_slice::<Ready>(&data) {
                    if state.pid == backend.child.id()
                        && state.nonce == nonce
                        && valid_url(&state.url)
                    {
                        backend.url = state.url;
                        return Ok(backend);
                    }
                }
            }
            if Instant::now() >= deadline {
                return Err("主机启动超时，请查看日志。\nBackend startup timed out.".into());
            }
            thread::sleep(Duration::from_millis(100));
        }
    }

    pub fn exited(&mut self) -> io::Result<bool> {
        Ok(self.child.try_wait()?.is_some())
    }
}

fn valid_url(value: &str) -> bool {
    value
        .strip_prefix("http://127.0.0.1:")
        .and_then(|port| port.parse::<u16>().ok())
        .map(|port| port != 0)
        .unwrap_or(false)
}

impl Drop for Backend {
    fn drop(&mut self) {
        if let Some(mut input) = self.child.stdin.take() {
            let _ = input.write_all(b"stop\n");
        }
        let deadline = Instant::now() + Duration::from_secs(8);
        loop {
            match self.child.try_wait() {
                Ok(Some(_)) => break,
                _ if Instant::now() >= deadline => {
                    let _ = self.child.kill();
                    let _ = self.child.wait();
                    break;
                }
                _ => thread::sleep(Duration::from_millis(50)),
            }
        }
        let _ = fs::remove_file(&self.ready);
        let _ = fs::remove_file(self.ready.with_extension("tmp"));
        // Closing _job removes any remaining child processes of this backend.
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn accepts_only_owned_loopback_origins() {
        assert!(super::valid_url("http://127.0.0.1:8780"));
        for value in [
            "http://127.0.0.1:0",
            "http://example.com:8780",
            "http://127.0.0.1:8780/x",
            "http://127.0.0.1:70000",
        ] {
            assert!(!super::valid_url(value));
        }
    }
}
