$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot 'output\server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No recorded server process.'; exit 0 }
$serverPid = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
$serverProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid"
$expectedServerPath = Join-Path $PSScriptRoot 'server.py'
if ($serverProcess -and $serverProcess.CommandLine.Contains($expectedServerPath)) {
    $expectedWorkerPath = Join-Path $PSScriptRoot 'cut_worker.py'
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$serverPid" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($expectedWorkerPath) } | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
    Stop-Process -Id $serverPid
    Write-Output 'Cutting Engine stopped.'
} elseif ($serverProcess) { throw 'The recorded process belongs to another application; it was left running.' }
