param([switch]$Release)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$toolRoot = Join-Path $PSScriptRoot '../.cache/toolchains'
if (-not $env:JAVA_HOME) {
    $jdk = Get-ChildItem -LiteralPath $toolRoot -Directory -Filter 'jdk-17*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($jdk) { $env:JAVA_HOME = $jdk.FullName }
}
if (-not $env:ANDROID_HOME -and (Test-Path -LiteralPath "$toolRoot/android-sdk")) {
    $env:ANDROID_HOME = (Resolve-Path "$toolRoot/android-sdk").Path
}
if (-not $env:JAVA_HOME -or -not $env:ANDROID_HOME) { throw '请先配置 JDK 17 的 JAVA_HOME 与 Android SDK 的 ANDROID_HOME，详见 README。' }
$target = if ($Release) { 'assembleRelease' } else { 'assembleDebug' }
& .\gradlew.bat $target testDebugUnitTest --no-daemon
if ($LASTEXITCODE -ne 0) { throw '构建未通过，请检查上面的错误。' }
Write-Host '构建完成；安装包位于 app/build/outputs/apk/。Release 还需私有签名。'
