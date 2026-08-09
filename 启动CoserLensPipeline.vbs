Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "D:\AI-Projects\youtube_pipeline"
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""D:\AI-Projects\youtube_pipeline\scripts\launch_pipeline_qt.ps1""", 0, False
