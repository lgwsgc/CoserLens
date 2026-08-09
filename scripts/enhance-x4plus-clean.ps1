param(
  [Parameter(Mandatory = $true)]
  [string]$InputVideo,

  [string]$OutputRoot = "D:\AI-Projects\youtube_pipeline\enhanced_outputs",
  [int]$BaseWidth = 540,
  [int]$BaseHeight = 960,
  [int]$GpuId = 1,
  [int]$TileSize = 512,
  [int]$Cq = 16,
  [string]$Bitrate = "30M",
  [string]$Maxrate = "48M"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $InputVideo)) {
  throw "Input video not found: $InputVideo"
}

$repoRoot = "D:\AI-Projects\youtube_pipeline"
$realesrganDir = Join-Path $repoRoot "tools\realesrgan-ncnn-vulkan-20220424-windows"
$realesrganExe = Join-Path $realesrganDir "realesrgan-ncnn-vulkan.exe"
$modelDir = Join-Path $realesrganDir "models"

if (!(Test-Path -LiteralPath $realesrganExe)) {
  throw "Real-ESRGAN executable not found: $realesrganExe"
}

$ffmpegCmd = Get-Command ffmpeg -ErrorAction Stop
$ffmpeg = $ffmpegCmd.Source
$ffprobe = Join-Path (Split-Path -Parent $ffmpeg) "ffprobe.exe"

$inputItem = Get-Item -LiteralPath $InputVideo
$safeName = [IO.Path]::GetFileNameWithoutExtension($inputItem.Name)
$safeName = $safeName -replace '[\\/:*?"<>|]', '_'
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$jobDir = Join-Path $OutputRoot "${safeName}_x4plus_clean_${stamp}"
$framesSmall = Join-Path $jobDir "frames_${BaseWidth}x${BaseHeight}"
$framesAI = Join-Path $jobDir "frames_x4plus_4x"
$logFile = Join-Path $jobDir "run.log"
$outputVideo = Join-Path $jobDir "${safeName}_x4plus-clean_${BaseWidth}x${BaseHeight}_to_4x_h265.mp4"
$compareVideo = Join-Path $jobDir "${safeName}_compare_left-original_right-x4plus-clean.mp4"

New-Item -ItemType Directory -Force -Path $jobDir, $framesSmall, $framesAI | Out-Null

function Write-Step {
  param([string]$Message)
  $line = "[$(Get-Date -Format o)] $Message"
  Write-Host $line
  $line | Out-File -LiteralPath $logFile -Encoding utf8 -Append
}

function Invoke-Logged {
  param(
    [string]$FilePath,
    [string[]]$Arguments
  )
  Write-Step ("RUN " + $FilePath + " " + ($Arguments -join " "))
  $tmpOutput = Join-Path $jobDir ("command_" + [guid]::NewGuid().ToString("N") + ".log")
  $oldErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  try {
    & $FilePath @Arguments *> $tmpOutput
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $oldErrorActionPreference
  }
  if (Test-Path -LiteralPath $tmpOutput) {
    Get-Content -LiteralPath $tmpOutput | Out-File -LiteralPath $logFile -Encoding utf8 -Append
    Remove-Item -LiteralPath $tmpOutput -Force -ErrorAction SilentlyContinue
  }
  if ($exitCode -ne 0) {
    throw "Command failed with exit code ${exitCode}: $FilePath"
  }
}

function Get-VideoFps {
  if (Test-Path -LiteralPath $ffprobe) {
    $raw = & $ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 $InputVideo
    if ($raw -match '^(\d+)\/(\d+)$' -and [int]$Matches[2] -ne 0) {
      return [double]$Matches[1] / [double]$Matches[2]
    }
    if ($raw -match '^\d+(\.\d+)?$') {
      return [double]$raw
    }
  }
  return 60.0
}

$fps = Get-VideoFps
$fpsText = [Globalization.CultureInfo]::InvariantCulture.TextInfo.ToTitleCase(("{0:0.###}" -f $fps))

Write-Step "Input: $InputVideo"
Write-Step "Output directory: $jobDir"
Write-Step "Detected FPS: $fpsText"
Write-Step "GPU ID: $GpuId"

Write-Step "Extracting downscaled frames"
Invoke-Logged $ffmpeg @(
  "-y",
  "-hide_banner",
  "-loglevel", "error",
  "-i", $InputVideo,
  "-vf", "scale=${BaseWidth}:${BaseHeight}:flags=lanczos",
  (Join-Path $framesSmall "%08d.png")
)

$smallCount = (Get-ChildItem -LiteralPath $framesSmall -File -Filter "*.png" | Measure-Object).Count
Write-Step "Extracted frames: $smallCount"
if ($smallCount -eq 0) {
  throw "No frames extracted."
}

Write-Step "Running Real-ESRGAN x4plus native 4x"
Invoke-Logged $realesrganExe @(
  "-i", $framesSmall,
  "-o", $framesAI,
  "-n", "realesrgan-x4plus",
  "-s", "4",
  "-t", "$TileSize",
  "-m", $modelDir,
  "-g", "$GpuId",
  "-j", "1:1:1",
  "-f", "png"
)

$aiCount = (Get-ChildItem -LiteralPath $framesAI -File -Filter "*.png" | Measure-Object).Count
Write-Step "AI frames: $aiCount"
if ($aiCount -ne $smallCount) {
  throw "Frame count mismatch. Extracted $smallCount, AI output $aiCount."
}

Write-Step "Encoding enhanced video"
Invoke-Logged $ffmpeg @(
  "-y",
  "-hide_banner",
  "-loglevel", "error",
  "-framerate", $fpsText,
  "-i", (Join-Path $framesAI "%08d.png"),
  "-i", $InputVideo,
  "-map", "0:v:0",
  "-map", "1:a?",
  "-c:v", "hevc_nvenc",
  "-preset", "p7",
  "-tune", "hq",
  "-rc", "vbr",
  "-cq", "$Cq",
  "-b:v", $Bitrate,
  "-maxrate", $Maxrate,
  "-bufsize", "96M",
  "-pix_fmt", "yuv420p",
  "-c:a", "copy",
  "-shortest",
  $outputVideo
)

Write-Step "Encoding comparison video"
Invoke-Logged $ffmpeg @(
  "-y",
  "-hide_banner",
  "-loglevel", "error",
  "-i", $InputVideo,
  "-i", $outputVideo,
  "-filter_complex", "[0:v]scale=1080:1920:flags=lanczos[left];[1:v]scale=1080:1920:flags=lanczos[right];[left][right]hstack=inputs=2",
  "-map", "0:a?",
  "-c:v", "hevc_nvenc",
  "-preset", "p7",
  "-tune", "hq",
  "-rc", "vbr",
  "-cq", "18",
  "-b:v", "24M",
  "-maxrate", "40M",
  "-bufsize", "80M",
  "-pix_fmt", "yuv420p",
  "-c:a", "copy",
  "-shortest",
  $compareVideo
)

Write-Step "Done"
Write-Host ""
Write-Host "Enhanced video: $outputVideo"
Write-Host "Comparison video: $compareVideo"
Write-Host "Log: $logFile"
