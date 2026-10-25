param([ValidateRange(1024,65535)][int]$Port, [string]$Config, [string]$DataDir)
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
    $launchArgs = @('-m', 'personalai')
    if ($PSBoundParameters.ContainsKey('Port')) { $launchArgs += @('--port', $Port) }
    if ($Config) { $launchArgs += @('--config', $Config) }
    if ($DataDir) { $launchArgs += @('--data-dir', $DataDir) }
    & $pythonPath @launchArgs
    if ($LASTEXITCODE -ne 0) { throw 'PersonalAI did not start. See the message above.' }
} finally { Pop-Location }
