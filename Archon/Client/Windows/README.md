# Windows client implementation

The portable desktop client reuses Portal and the Python Archon control entry.
Tauri supplies the native window; WebView2 renders the UI. Rust owns the Python
child process through a Windows Job and stdin shutdown handshake. Single-instance
handling focuses an existing window. Loopback ports are dynamically assigned.

`runtime-manifest.json` pins download URLs and SHA-256 for Python 3.11.9 and fixed
WebView2. `package.py` builds clean tracked-source ZIPs, excludes private Data and
credentials, writes `release.json`, and emits per-ZIP checksums. Standard/full
share one EXE; full adds `Runtime/WebView2`, standard uses installed WebView2.
Build dependencies include Rust/MSVC, Python, network access and the Tauri Windows
prerequisites; runtime users do not need a development toolchain.

On a Windows build machine, from the repository root:

```powershell
.\Archon\Client\Windows\build.ps1
# Or omit fixed WebView2 packaging:
.\Archon\Client\Windows\build.ps1 -StandardOnly
```

Output is `dist/`. Build prerequisites are exercised by the
[Windows workflow](../../../.github/workflows/windows-client.yml).
`icons/icon.ico` contains multiple sizes; `icons/icon.png` is the shared default
window image. External links open the system browser. Native Save As selects the
WebView2 download destination without buffering the Pod file through the host.

Client logs: `Data/Logs/client/backend.log`; profile: `Data/Runtime/WebView2/`.
Closing the window stops owned local children, not cloud instances. Tests:
`Tests/Client/` and native Rust unit tests. `smoke_windows.ps1` checks extracted
packages, Unicode paths, startup without Python on PATH, single-instance behavior
and shutdown. It does not replace manual GPU/Pod or visual acceptance testing.

User instructions: [Getting started](../../../Docs/Getting-Started.md).
