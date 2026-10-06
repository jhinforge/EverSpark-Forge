use std::{
    ffi::{OsStr, OsString},
    io,
    os::windows::ffi::{OsStrExt, OsStringExt},
    os::windows::process::CommandExt,
    path::{Path, PathBuf},
    process::Command,
    ptr,
};
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    },
    UI::{
        Controls::Dialogs::{
            CommDlgExtendedError, GetSaveFileNameW, OFN_EXPLORER, OFN_NOCHANGEDIR,
            OFN_OVERWRITEPROMPT, OFN_PATHMUSTEXIST, OPENFILENAMEW,
        },
        Shell::ShellExecuteW,
        WindowsAndMessaging::{
            MessageBoxW, IDYES, MB_ABORTRETRYIGNORE, MB_ICONERROR, MB_ICONINFORMATION, MB_OK,
            MB_YESNO,
        },
    },
};
use winreg::{
    enums::{HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE, KEY_READ, KEY_WOW64_32KEY},
    RegKey,
};

fn wide(text: impl AsRef<OsStr>) -> Vec<u16> {
    text.as_ref().encode_wide().chain(Some(0)).collect()
}

pub fn message(text: &str, buttons: u32) -> i32 {
    unsafe {
        MessageBoxW(
            ptr::null_mut(),
            wide(text).as_ptr(),
            wide("EverSpark Forge").as_ptr(),
            buttons | MB_ICONERROR,
        )
    }
}

pub fn startup_error(text: &str) {
    message(text, MB_OK);
}

pub fn open(target: impl AsRef<OsStr>) {
    unsafe {
        ShellExecuteW(
            ptr::null_mut(),
            wide("open").as_ptr(),
            wide(target).as_ptr(),
            ptr::null(),
            ptr::null(),
            1,
        );
    }
}

pub fn retry_or_logs(text: &str, logs: &Path) -> bool {
    loop {
        match message(
            &format!(
                "{text}\n\n重试 / Retry：重新启动\n忽略 / Ignore：打开日志\n中止 / Abort：退出"
            ),
            MB_ABORTRETRYIGNORE,
        ) {
            4 => return true,
            5 => open(logs),
            _ => return false,
        }
    }
}

pub fn prepare_webview(root: &Path) -> Result<(), String> {
    // Ignore inherited overrides: the two ZIPs have deterministic selection.
    std::env::remove_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER");
    std::env::remove_var("WEBVIEW2_USER_DATA_FOLDER");
    let fixed = root.join("Runtime/WebView2");
    if fixed.exists() {
        if !fixed.join("msedgewebview2.exe").is_file() {
            return Err(
                "随包 WebView2 不完整，请重新解压完整便携版。\nBundled WebView2 is incomplete."
                    .into(),
            );
        }
        // Required for unpackaged Fixed Version v120+ on Windows 10. The
        // grant is scoped to this runtime directory and uses stable SID names.
        let result = Command::new("icacls")
            .arg(&fixed)
            .args([
                "/grant",
                "*S-1-15-2-1:(OI)(CI)(RX)",
                "/grant",
                "*S-1-15-2-2:(OI)(CI)(RX)",
                "/T",
                "/Q",
            ])
            .creation_flags(0x08000000)
            .output()
            .map_err(|e| e.to_string())?;
        if !result.status.success() {
            return Err("无法设置随包 WebView2 的读取权限，请解压到自己有写入权限的目录。\nCannot prepare bundled WebView2 permissions.".into());
        }
        std::env::set_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", &fixed);
        return Ok(());
    }
    let key = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    let installed = [HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE].iter().any(|hive| {
        RegKey::predef(*hive)
            .open_subkey_with_flags(key, KEY_READ | KEY_WOW64_32KEY)
            .and_then(|k| k.get_value::<String, _>("pv"))
            .map(|v| !v.is_empty() && v != "0.0.0.0")
            .unwrap_or(false)
    });
    if installed {
        return Ok(());
    }
    if message("这台电脑缺少 WebView2。可安装微软运行时，或使用 EverSpark 完整便携版。\n\nWebView2 is missing. Install the Microsoft runtime or use the full portable ZIP.\n\n是否打开微软官方下载页面？ / Open Microsoft download page?", MB_YESNO) == IDYES {
        open("https://developer.microsoft.com/microsoft-edge/webview2/");
    }
    Err("缺少 WebView2，尚未启动后端。\nWebView2 is missing; the backend was not started.".into())
}

// The handle is owned, never inherited, and only passed back to Win32 APIs.
pub struct Job(usize);
impl Job {
    pub fn new() -> io::Result<Self> {
        unsafe {
            let handle = CreateJobObjectW(ptr::null(), ptr::null());
            if handle.is_null() {
                return Err(io::Error::last_os_error());
            }
            let job = Self(handle as usize);
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            Ok(job)
        }
    }
    pub fn assign(&self, process: HANDLE) -> io::Result<()> {
        if unsafe { AssignProcessToJobObject(self.0 as HANDLE, process) } == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(())
        }
    }
}
impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0 as HANDLE);
        }
    }
}

/// Report actual WebView2 download completion and the final destination.
pub fn download_finished(path: Option<&Path>, success: bool) {
    if !success {
        message(
            "下载失败或已取消，请重试。\nDownload failed or was cancelled. Please retry.",
            MB_OK,
        );
        return;
    }
    let Some(path) = path else {
        message("下载完成。\nDownload completed.", MB_OK);
        return;
    };
    let text = format!(
        "下载完成 / Download completed:\n{}\n\n是否打开所在文件夹？ / Open containing folder?",
        path.display()
    );
    let answer = unsafe {
        MessageBoxW(
            ptr::null_mut(),
            wide(text).as_ptr(),
            wide("EverSpark Forge").as_ptr(),
            MB_YESNO | MB_ICONINFORMATION,
        )
    };
    if answer == IDYES {
        if let Some(parent) = path.parent() {
            open(parent);
        }
    }
}

/// Choose the destination before WebView2 starts writing the download.
pub fn save_download(
    owner: windows_sys::Win32::Foundation::HWND,
    suggested: &Path,
) -> Result<Option<PathBuf>, String> {
    let mut filename = vec![0u16; 32768];
    let suggested_name = suggested.file_name().unwrap_or(OsStr::new("EverSpark.zip"));
    let name = wide(suggested_name);
    if name.len() > filename.len() {
        return Err("下载文件名过长 / Download filename is too long".into());
    }
    filename[..name.len()].copy_from_slice(&name);
    let filter = wide("ZIP archives (*.zip)\0*.zip\0All files (*.*)\0*.*\0");
    let title = wide("选择下载保存位置 / Save download as");
    let extension = wide(suggested.extension().unwrap_or(OsStr::new("zip")));
    let mut dialog: OPENFILENAMEW = unsafe { std::mem::zeroed() };
    dialog.lStructSize = std::mem::size_of::<OPENFILENAMEW>() as u32;
    dialog.hwndOwner = owner;
    dialog.lpstrFile = filename.as_mut_ptr();
    dialog.nMaxFile = filename.len() as u32;
    dialog.lpstrFilter = filter.as_ptr();
    dialog.nFilterIndex = if suggested
        .extension()
        .and_then(OsStr::to_str)
        .is_some_and(|value| value.eq_ignore_ascii_case("zip"))
    {
        1
    } else {
        2
    };
    dialog.lpstrTitle = title.as_ptr();
    dialog.lpstrDefExt = extension.as_ptr();
    dialog.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST;
    if unsafe { GetSaveFileNameW(&mut dialog) } != 0 {
        let length = filename
            .iter()
            .position(|value| *value == 0)
            .unwrap_or(filename.len());
        Ok(Some(PathBuf::from(OsString::from_wide(
            &filename[..length],
        ))))
    } else {
        let error = unsafe { CommDlgExtendedError() };
        if error == 0 {
            Ok(None)
        } else {
            Err(format!("无法打开保存窗口 / Save dialog failed ({error})"))
        }
    }
}
