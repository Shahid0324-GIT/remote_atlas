$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectDirectory '.share\processes.json'
if (-not (Test-Path -LiteralPath $processFile)) {
    Write-Host 'No demo sharing session is recorded.'
    exit
}
$records = Get-Content -LiteralPath $processFile -Raw | ConvertFrom-Json
foreach ($record in $records) {
    $demoProcess = Get-Process -Id $record.id -ErrorAction SilentlyContinue
    if ($demoProcess -and $demoProcess.Path -eq $record.path -and $demoProcess.StartTime.ToUniversalTime().Ticks -eq $record.started) {
        Stop-Process -Id $demoProcess.Id
    }
}
Remove-Item -LiteralPath $processFile
Write-Host 'Demo sharing stopped. Your personal tracker is unaffected.'
