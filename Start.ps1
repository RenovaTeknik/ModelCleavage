param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$appPath = $PSScriptRoot
$localUrl = 'http://127.0.0.1:8765'
try {
    $health = Invoke-RestMethod -Uri "$localUrl/api/health" -TimeoutSec 2
    if ($health.app -eq 'model-cleavage-local-v1') {
        if (-not $NoBrowser) { Start-Process $localUrl -WindowStyle Hidden }
        Write-Output "Cutting Engine is already running at $localUrl"
        exit 0
    }
    throw 'Port 8765 is occupied by another application.'
} catch {
    if ($_.Exception.Message -like '*occupied*') { throw }
}
$runtimeConfig = Join-Path $appPath '.runtime\python-path.txt'
if (-not (Test-Path -LiteralPath $runtimeConfig)) { throw 'Python runtime configuration is missing. See README.md for setup.' }
$pythonPath = (Get-Content -LiteralPath $runtimeConfig -Raw).Trim()
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Configured Python runtime was not found. Update .runtime\python-path.txt.' }
$outputPath = Join-Path $appPath 'output'
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
$serverPath = Join-Path $appPath 'server.py'
$serverProcess = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + $serverPath + '"'), '--port', '8765') -WorkingDirectory $appPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $outputPath 'server.log') -RedirectStandardError (Join-Path $outputPath 'server-errors.log') -PassThru
Set-Content -LiteralPath (Join-Path $outputPath 'server.pid') -Value $serverProcess.Id
$ready = $false
for ($attempt=0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    try { $health = Invoke-RestMethod -Uri "$localUrl/api/health" -TimeoutSec 1; if ($health.app -eq 'model-cleavage-local-v1') { $ready = $true; break } } catch {}
    if ($serverProcess.HasExited) { break }
}
if (-not $ready) { throw "The local server did not start. Check $outputPath\server-errors.log" }
if (-not $NoBrowser) { Start-Process $localUrl -WindowStyle Hidden }
Write-Output "Cutting Engine ready at $localUrl"
