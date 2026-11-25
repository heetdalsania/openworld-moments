# SPDX-License-Identifier: AGPL-3.0-or-later
# CI only: install Tesseract OCR (>= 5, with English data) on a GitHub-hosted Windows runner.
#
# Chocolatey is tried first, up to three times with backoff. If Tesseract still is not
# usable (community.chocolatey.org returned 504s on 2026-11-25 while choco exited 0),
# the pinned official installer is downloaded from the tesseract-ocr GitHub release,
# checked against a fixed SHA-256 and run silently. The step fails here, loudly, unless
# `tesseract --version` reports 5+ and `--list-langs` includes `eng`, which is what the
# worker's OCR doctor requires (openworld_moments/detectors/ocr.py).
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MinimumMajor = 5
$Language = 'eng'
$FallbackVersion = '5.5.3'
$FallbackUrl = "https://github.com/tesseract-ocr/tesseract/releases/download/$FallbackVersion/tesseract-ocr-w64-setup-5.5.3.20260724.exe"
$FallbackSha256 = 'bee9e3434bd94fd65387d9be28cd467a41f61b1275383b55b0f59a1331270ae4'
$InstallDir = Join-Path $env:ProgramFiles 'Tesseract-OCR'

function Find-Tesseract {
  $command = Get-Command 'tesseract' -CommandType Application -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $default = Join-Path $InstallDir 'tesseract.exe'
  if (Test-Path -LiteralPath $default -PathType Leaf) { return $default }
  return $null
}

function Test-Tesseract {
  $exe = Find-Tesseract
  if (-not $exe) { return $false }
  $version = (& $exe --version 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0 -or $version -notmatch 'tesseract v?(\d+)\.\d+\.\d+') { return $false }
  if ([int]$Matches[1] -lt $MinimumMajor) { return $false }
  $langs = @(& $exe --list-langs 2>&1 | ForEach-Object { $_.ToString().Trim() })
  return $LASTEXITCODE -eq 0 -and ($langs -contains $Language)
}

$delays = @(0, 20, 60)
for ($attempt = 1; $attempt -le $delays.Count -and -not (Test-Tesseract); $attempt++) {
  if ($delays[$attempt - 1] -gt 0) {
    Write-Host "Waiting $($delays[$attempt - 1]) s before Chocolatey attempt $attempt"
    Start-Sleep -Seconds $delays[$attempt - 1]
  }
  Write-Host "::group::choco install tesseract (attempt $attempt of $($delays.Count))"
  & choco install tesseract -y --no-progress
  $chocoExit = $LASTEXITCODE
  Write-Host '::endgroup::'
  if (-not (Test-Tesseract)) {
    Write-Host "::warning::Chocolatey attempt $attempt did not install tesseract (exit $chocoExit)"
  }
}

if (-not (Test-Tesseract)) {
  Write-Host "::warning::Chocolatey failed; using the pinned Tesseract $FallbackVersion installer from GitHub"
  $root = Join-Path $env:RUNNER_TEMP 'owm-tesseract'
  $installer = Join-Path $root 'tesseract-setup.exe'
  New-Item -ItemType Directory -Force -Path $root | Out-Null

  $downloaded = $false
  foreach ($delay in @(0, 15, 45)) {
    if ($delay -gt 0) { Start-Sleep -Seconds $delay }
    try {
      Invoke-WebRequest -Uri $FallbackUrl -OutFile $installer -UseBasicParsing
      $downloaded = $true
      break
    } catch {
      Write-Host "::warning::Download failed: $($_.Exception.Message)"
    }
  }
  if (-not $downloaded) { throw "Could not download $FallbackUrl" }

  $actual = (Get-FileHash -Algorithm SHA256 -Path $installer).Hash.ToLowerInvariant()
  if ($actual -ne $FallbackSha256) {
    throw "SHA-256 mismatch for $FallbackUrl`: expected $FallbackSha256, got $actual"
  }
  # NSIS installer: /S is silent; /D must be the last argument and unquoted.
  $process = Start-Process -FilePath $installer -ArgumentList '/S', "/D=$InstallDir" -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Tesseract installer exited with code $($process.ExitCode)" }
}

$exe = Find-Tesseract
if (-not $exe) { throw 'tesseract is not installed after all install attempts' }
$bin = Split-Path -Parent $exe
if (-not (Get-Command 'tesseract' -CommandType Application -ErrorAction SilentlyContinue)) {
  $env:PATH = "$bin;$env:PATH"
  Add-Content -Path $env:GITHUB_PATH -Value $bin
}

$version = (& $exe --version 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) { throw "tesseract --version failed with exit code $LASTEXITCODE" }
Write-Host "${exe}: $(($version -split "`r?`n")[0])"
if ($version -notmatch 'tesseract v?(\d+)\.\d+\.\d+') { throw "Could not read the tesseract version from: $version" }
if ([int]$Matches[1] -lt $MinimumMajor) {
  throw "tesseract $($Matches[1]).x is older than the required $MinimumMajor.0"
}
$langs = @(& $exe --list-langs 2>&1 | ForEach-Object { $_.ToString().Trim() })
if ($LASTEXITCODE -ne 0) { throw "tesseract --list-langs failed with exit code $LASTEXITCODE" }
Write-Host ($langs -join ' | ')
if ($langs -notcontains $Language) { throw "Tesseract language data '$Language' is not installed" }
