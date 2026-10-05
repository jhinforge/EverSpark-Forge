param([switch]$StandardOnly)
$ErrorActionPreference = 'Stop'
$client = $PSScriptRoot
$root = (Resolve-Path (Join-Path $client '../../..')).Path
Push-Location $client
try {
    cargo build --release --locked
    if ($LASTEXITCODE -ne 0) { throw 'Windows client compilation failed' }
    $arguments = @((Join-Path $client 'package.py'), '--exe', (Join-Path $client 'target/release/everspark-client.exe'), '--output', (Join-Path $root 'dist'))
    if ($StandardOnly) { $arguments += '--standard-only' }
    python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Portable ZIP packaging failed' }
} finally { Pop-Location }
