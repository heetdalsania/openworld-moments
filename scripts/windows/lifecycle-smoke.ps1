# SPDX-License-Identifier: AGPL-3.0-or-later
# Scratch CI VM only. Refuse existing app data rather than risking a user's library.
$ErrorActionPreference = 'Stop'
$install = Join-Path $env:RUNNER_TEMP 'OWM alpha ✓ 日本語'
$library = Join-Path $env:APPDATA 'org.openworldmoments.desktop'
if (Test-Path $library) { throw 'Refusing to test against an existing application library' }
if (Test-Path $install) { throw 'Scratch installation directory already exists' }
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = '--remote-debugging-port=9223'
$env:OWM_WORKER_PYTHON = 'Z:\missing-python.exe'
$env:OWM_FFMPEG = 'Z:\missing-ffmpeg.exe'
$env:OWM_FFPROBE = 'Z:\missing-ffprobe.exe'
$installer = Get-ChildItem 'target/x86_64-pc-windows-msvc/release/bundle/nsis/*-setup.exe' | Select-Object -First 1
if (-not $installer) { throw 'NSIS installer missing' }
function Install-App($package) {
  $result = Start-Process -FilePath $package -ArgumentList "/S /D=$install" -Wait -PassThru
  if ($result.ExitCode -ne 0) { throw "Installation failed: $($result.ExitCode)" }
}
function Test-App($mode) {
  $application = Get-ChildItem "$install/*.exe" | Where-Object Name -NotMatch 'uninstall' | Select-Object -First 1
  if (-not $application) { throw 'Installed application missing' }
  $process = Start-Process -FilePath $application.FullName -WorkingDirectory $env:RUNNER_TEMP -PassThru
  try {
    uv run --locked --group packaging --directory services/media-worker python ../../scripts/windows/native-smoke.py "$install" $mode
    if ($LASTEXITCODE -ne 0) { throw 'Native WebView2/worker smoke failed' }
  } finally {
    $process.Refresh()
    if (-not $process.HasExited) {
      if (-not $process.CloseMainWindow()) { Stop-Process -Id $process.Id; throw 'Native window did not close gracefully' }
      if (-not $process.WaitForExit(30000)) { Stop-Process -Id $process.Id; throw 'Application shutdown timed out' }
    }
  }
}
Install-App $installer.FullName
Test-App 'import-render'
$sentinel = Join-Path $library 'retention-sentinel.txt'
Set-Content -Path $sentinel -Value 'Keep libraries through repair, upgrade and uninstall' -Encoding utf8
Install-App $installer.FullName
Test-App 'repair'
if (-not (Test-Path $sentinel)) { throw 'Repair removed user data' }
# Build a test-only higher version; source and frozen runtimes remain identical.
python -c "import json,pathlib;p=pathlib.Path('apps/desktop/src-tauri/tauri.packaged.conf.json');d=json.loads(p.read_text());d['version']='0.1.0-alpha.29.1';(p.parent/'bundle-input/upgrade-test.conf.json').write_text(json.dumps(d))"
if ($LASTEXITCODE -ne 0) { throw 'Upgrade test config failed' }
pnpm --filter @openworld-moments/desktop run tauri build --config src-tauri/bundle-input/upgrade-test.conf.json --target x86_64-pc-windows-msvc --bundles nsis
if ($LASTEXITCODE -ne 0) { throw 'Upgrade test build failed' }
$upgrade = Get-ChildItem 'target/x86_64-pc-windows-msvc/release/bundle/nsis/*alpha.29.1*-setup.exe' | Select-Object -First 1
if (-not $upgrade) { throw 'Upgrade package missing' }
Install-App $upgrade.FullName
Test-App 'upgrade'
if (-not (Test-Path $sentinel)) { throw 'Upgrade removed user data' }
$uninstaller = Get-ChildItem "$install/*uninstall*.exe" | Select-Object -First 1
if (-not $uninstaller) { throw 'Uninstaller missing' }
$result = Start-Process -FilePath $uninstaller.FullName -ArgumentList '/S' -Wait -PassThru
if ($result.ExitCode -ne 0) { throw 'Uninstall failed' }
if (-not (Test-Path $sentinel)) { throw 'Uninstall removed user libraries' }
# Only this script's scratch library can reach this cleanup.
Remove-Item $library -Recurse -Force
