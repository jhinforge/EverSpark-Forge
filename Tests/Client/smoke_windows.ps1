param([Parameter(Mandatory=$true)][string]$Zip)
$ErrorActionPreference = 'Stop'
$directory = Join-Path $env:RUNNER_TEMP ('EverSpark 中文 path ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $directory | Out-Null
Expand-Archive -LiteralPath $Zip -DestinationPath $directory
$root = Join-Path $directory 'EverSpark-Forge'
$application = $null
$backendId = $null
$oldPath = $env:PATH
try {
    # No Python on PATH: the application must use its own runtime.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:EVERSPARK_NODE_PORT = '0'
    $env:EVERSPARK_NODE_HOST = '127.0.0.1'
    $env:EVERSPARK_NODE_STATE = Join-Path $directory 'nodes.json'
    $application = Start-Process -FilePath (Join-Path $root 'EverSpark.exe') -WorkingDirectory $env:SystemRoot -PassThru
    $deadline = (Get-Date).AddSeconds(90)
    $ready = $null
    while ((Get-Date) -lt $deadline) {
        $application.Refresh()
        if ($application.HasExited) { throw 'Desktop client exited before readiness' }
        $file = Get-ChildItem -LiteralPath (Join-Path $root 'Data/Runtime') -Filter 'desktop-*.json' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($file) { $ready = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) {
        Get-Content -LiteralPath (Join-Path $root 'Data/Logs/client/backend.log') -ErrorAction SilentlyContinue
        throw 'Desktop backend readiness timed out'
    }
    $backendId = $ready.pid
    $status = Invoke-RestMethod -Uri ($ready.url + '/api/runtime/status') -TimeoutSec 10
    if (-not $status.services.archon_backend.online) { throw 'Control backend is not ready' }
    $duplicate = Start-Process -FilePath (Join-Path $root 'EverSpark.exe') -PassThru
    if (-not $duplicate.WaitForExit(15000)) { $duplicate.Kill(); throw 'Second desktop instance did not exit' }
    $application.Refresh()
    if ($application.HasExited) { throw 'Original desktop instance was lost' }
    $files = @(Get-ChildItem -LiteralPath (Join-Path $root 'Data/Runtime') -Filter 'desktop-*.json')
    if ($files.Count -ne 1) { throw 'Duplicate backend was started' }
    if (-not $application.CloseMainWindow()) { throw 'Client has no main window to close' }
    if (-not $application.WaitForExit(20000)) { throw 'Desktop failed to exit gracefully' }
    Start-Sleep -Milliseconds 300
    if (Get-Process -Id $backendId -ErrorAction SilentlyContinue) { throw 'Owned backend remained after window close' }
    Write-Host ('PASS: ' + (Split-Path $Zip -Leaf) + ' — no system Python, Unicode path, single instance, graceful shutdown')
} finally {
    $env:PATH = $oldPath
    if ($application -and -not $application.HasExited) { $application.Kill(); $application.WaitForExit(10000) | Out-Null }
    Remove-Item Env:EVERSPARK_NODE_PORT -ErrorAction SilentlyContinue
    Remove-Item Env:EVERSPARK_NODE_HOST -ErrorAction SilentlyContinue
    Remove-Item Env:EVERSPARK_NODE_STATE -ErrorAction SilentlyContinue
}
