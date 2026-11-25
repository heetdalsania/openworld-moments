# SPDX-License-Identifier: AGPL-3.0-or-later
# CI only: install FFmpeg and FFprobe (>= 6.0) on a GitHub-hosted Windows runner.
#
# Chocolatey is tried first, up to three times with backoff. If it still has not put
# ffmpeg on PATH (community.chocolatey.org returned 504s on 2026-11-25 while choco
# exited 0), a pinned Gyan.dev essentials build is downloaded from its GitHub release
# and checked against a fixed SHA-256 before it is extracted. The step fails here,
# loudly, unless both tools run and report a supported version.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MinimumMajor = 6
$FallbackVersion = '9.1'
$FallbackUrl = "https://github.com/GyanD/codexffmpeg/releases/download/$FallbackVersion/ffmpeg-$FallbackVersion-essentials_build.zip"
$FallbackSha256 = 'b9bbbb3acece000cbeec994f856649354e52c773807841e78908374b24d658fd'

function Test-Tool([string] $Name) {
  $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
  if (-not $command) { return $false }
  & $command.Source -version *> $null
  return $LASTEXITCODE -eq 0
}

function Test-FFmpeg { (Test-Tool 'ffmpeg') -and (Test-Tool 'ffprobe') }

$delays = @() # TEMPORARY: force the pinned fallback to test it
for ($attempt = 1; $attempt -le $delays.Count -and -not (Test-FFmpeg); $attempt++) {
  if ($delays[$attempt - 1] -gt 0) {
    Write-Host "Waiting $($delays[$attempt - 1]) s before Chocolatey attempt $attempt"
    Start-Sleep -Seconds $delays[$attempt - 1]
  }
  Write-Host "::group::choco install ffmpeg (attempt $attempt of $($delays.Count))"
  & choco install ffmpeg -y --no-progress
  $chocoExit = $LASTEXITCODE
  Write-Host '::endgroup::'
  if (-not (Test-FFmpeg)) {
    Write-Host "::warning::Chocolatey attempt $attempt did not install ffmpeg (exit $chocoExit)"
  }
}

if (-not (Test-FFmpeg)) {
  Write-Host "::warning::Chocolatey failed; using the pinned FFmpeg $FallbackVersion build from GitHub"
  $root = Join-Path $env:RUNNER_TEMP 'owm-ffmpeg'
  $zip = Join-Path $root 'ffmpeg.zip'
  $extracted = Join-Path $root 'extracted'
  New-Item -ItemType Directory -Force -Path $root | Out-Null

  $downloaded = $false
  foreach ($delay in @(0, 15, 45)) {
    if ($delay -gt 0) { Start-Sleep -Seconds $delay }
    try {
      Invoke-WebRequest -Uri $FallbackUrl -OutFile $zip -UseBasicParsing
      $downloaded = $true
      break
    } catch {
      Write-Host "::warning::Download failed: $($_.Exception.Message)"
    }
  }
  if (-not $downloaded) { throw "Could not download $FallbackUrl" }

  $actual = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLowerInvariant()
  if ($actual -ne $FallbackSha256) {
    throw "SHA-256 mismatch for $FallbackUrl`: expected $FallbackSha256, got $actual"
  }
  Expand-Archive -Path $zip -DestinationPath $extracted -Force
  $exe = Get-ChildItem -Path $extracted -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
  if (-not $exe) { throw 'ffmpeg.exe not found in the pinned archive' }
  $bin = $exe.DirectoryName
  $env:PATH = "$bin;$env:PATH"
  Add-Content -Path $env:GITHUB_PATH -Value $bin
}

foreach ($tool in 'ffmpeg', 'ffprobe') {
  $command = Get-Command $tool -CommandType Application -ErrorAction SilentlyContinue
  if (-not $command) { throw "$tool is not on PATH after installation" }
  $banner = & $command.Source -version 2>&1
  if ($LASTEXITCODE -ne 0) { throw "$tool -version failed with exit code $LASTEXITCODE" }
  $first = ($banner | Select-Object -First 1).ToString()
  Write-Host "$($command.Source): $first"
  if ($first -notmatch '\bversion\s+n?(\d+)\.') {
    throw "Could not read the $tool version from: $first"
  }
  if ([int]$Matches[1] -lt $MinimumMajor) {
    throw "$tool $($Matches[1]).x is older than the required $MinimumMajor.0"
  }
}
