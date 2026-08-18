$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
$python = if ($pythonw) { $pythonw.Source } else { (Get-Command python.exe -ErrorAction Stop).Source }

Start-Process `
    -FilePath $python `
    -ArgumentList @('-m', 'desktop.control_center') `
    -WorkingDirectory $root `
    -WindowStyle Hidden
