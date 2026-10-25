param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw 'Please run Setup-PersonalAI.ps1 first.'
}
if (!(Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
    throw 'Frontend is not built. Please run Setup-PersonalAI.ps1 first.'
}
Push-Location $projectRoot
try {
    & $pythonPath -m personalai --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'PersonalAI did not start. See the message above.' }
} finally { Pop-Location }
