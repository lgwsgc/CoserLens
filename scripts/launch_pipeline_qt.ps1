$ErrorActionPreference = "SilentlyContinue"

$root = "D:\AI-Projects\youtube_pipeline"
$script = Join-Path $root "scripts\pipeline_desktop_qt.py"
$pythonw = "D:\anaconda3\envs\ytb\pythonw.exe"
$workdir = Join-Path $root "scripts"

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*pipeline_desktop_qt.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Start-Sleep -Milliseconds 400
Start-Process -FilePath $pythonw -ArgumentList "`"$script`"" -WorkingDirectory $workdir -WindowStyle Normal
