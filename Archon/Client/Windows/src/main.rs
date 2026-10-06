#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod platform;

use std::{
    fs,
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

struct State {
    backend: Mutex<Option<backend::Backend>>,
    origin: Mutex<Option<tauri::Url>>,
    quitting: AtomicBool,
}

fn root() -> Result<PathBuf, String> {
    let executable = std::env::current_exe().map_err(|e| e.to_string())?;
    let directory = executable.parent().ok_or("No executable directory")?;
    // Release EXE lives in the ZIP root; cargo run can find a Git checkout.
    directory
        .ancestors()
        .find(|path| path.join("Archon/Client/Windows/backend.py").is_file())
        .map(PathBuf::from)
        .ok_or("找不到 EverSpark 源码。请完整解压 ZIP。\nEverSpark source is missing.")
        .map_err(str::to_owned)
}

fn main() {
    let result = run();
    if let Err(error) = result {
        platform::startup_error(&error);
    }
}

fn run() -> Result<(), String> {
    let root = root()?;
    let logs = root.join("Data/Logs/client");
    fs::create_dir_all(&logs).map_err(|e| {
        format!("客户端目录不可写，请移动到自己的文件夹。\nCannot write client directory: {e}")
    })?;
    platform::prepare_webview(&root)?;
    let profile = root.join("Data/Runtime/WebView2");
    fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
    let state = Arc::new(State {
        backend: Mutex::new(None),
        origin: Mutex::new(None),
        quitting: AtomicBool::new(false),
    });
    let setup_state = state.clone();
    let exit_state = state.clone();
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .setup(move |app| {
            let navigation_state = setup_state.clone();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("EverSpark Forge")
                .inner_size(1280.0, 820.0)
                .min_inner_size(900.0, 600.0)
                .data_directory(profile.clone())
                .on_navigation(move |url| {
                    if url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost") {
                        return true;
                    }
                    if navigation_state
                        .origin
                        .lock()
                        .unwrap()
                        .as_ref()
                        .is_some_and(|origin| origin.origin() == url.origin())
                    {
                        return true;
                    }
                    if url.scheme() == "blob" {
                        return url
                            .as_str()
                            .strip_prefix("blob:")
                            .and_then(|value| value.parse::<tauri::Url>().ok())
                            .is_some_and(|source| {
                                navigation_state
                                    .origin
                                    .lock()
                                    .unwrap()
                                    .as_ref()
                                    .is_some_and(|origin| origin.origin() == source.origin())
                            });
                    }
                    // Media download URLs must remain in WebView2 so its native
                    // download dialog receives the attachment response.
                    if url.scheme() == "http"
                        && ["/archive", "/file"].contains(&url.path())
                        && url.host_str().is_some_and(|host| {
                            host.parse::<std::net::Ipv4Addr>()
                                .map(|ip| {
                                    ip.octets()[0] == 100 && (64..=127).contains(&ip.octets()[1])
                                })
                                .unwrap_or(false)
                        })
                    {
                        return true;
                    }
                    if ["http", "https"].contains(&url.scheme()) {
                        platform::open(url.as_str());
                    }
                    false
                })
                .on_download(|webview, event| {
                    use tauri::webview::DownloadEvent;
                    match event {
                        DownloadEvent::Requested { destination, .. } => {
                            let text = serde_json::to_string(&format!(
                                "正在下载至 / Downloading to: {}",
                                destination.display()
                            ))
                            .unwrap();
                            let _ = webview.eval(&format!(
                                "if (typeof showNotice === 'function') showNotice({text});"
                            ));
                        }
                        DownloadEvent::Finished { path, success, .. } => {
                            let path = path.map(|value| value.to_path_buf());
                            thread::spawn(move || {
                                platform::download_finished(path.as_deref(), success)
                            });
                        }
                        _ => {}
                    }
                    true
                })
                .on_new_window(|url, _| {
                    if ["http", "https"].contains(&url.scheme()) {
                        platform::open(url.as_str());
                    }
                    tauri::webview::NewWindowResponse::Deny
                })
                .build()?;
            let handle = app.handle().clone();
            let state = setup_state.clone();
            let root = root.clone();
            let logs = logs.clone();
            thread::spawn(move || {
                while !state.quitting.load(Ordering::Relaxed) {
                    match backend::Backend::launch(&root, &state.quitting) {
                        Ok(backend) => {
                            let url: tauri::Url = backend.url.parse().unwrap();
                            *state.origin.lock().unwrap() = Some(url.clone());
                            let mut slot = state.backend.lock().unwrap();
                            if state.quitting.load(Ordering::Relaxed) {
                                break;
                            }
                            *slot = Some(backend);
                            drop(slot);
                            if let Some(window) = handle.get_webview_window("main") {
                                if let Err(error) = window.navigate(url) {
                                    state.backend.lock().unwrap().take();
                                    if !platform::retry_or_logs(&error.to_string(), &logs) {
                                        handle.exit(1);
                                        break;
                                    }
                                    continue;
                                }
                            }
                            while !state.quitting.load(Ordering::Relaxed) {
                                thread::sleep(Duration::from_millis(500));
                                let exited = state
                                    .backend
                                    .lock()
                                    .unwrap()
                                    .as_mut()
                                    .map(|b| b.exited().unwrap_or(true))
                                    .unwrap_or(true);
                                if exited {
                                    break;
                                }
                            }
                            state.backend.lock().unwrap().take();
                            if state.quitting.load(Ordering::Relaxed) {
                                break;
                            }
                            if !platform::retry_or_logs(
                                "主机进程已退出。\nThe backend process stopped.",
                                &logs,
                            ) {
                                handle.exit(1);
                                break;
                            }
                        }
                        Err(error) => {
                            if state.quitting.load(Ordering::Relaxed) {
                                break;
                            }
                            if !platform::retry_or_logs(&error, &logs) {
                                handle.exit(1);
                                break;
                            }
                        }
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .map_err(|e| e.to_string())?;
    app.run(move |_, event| {
        if matches!(
            event,
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
        ) {
            exit_state.quitting.store(true, Ordering::Relaxed);
            exit_state.backend.lock().unwrap().take();
        }
    });
    Ok(())
}
