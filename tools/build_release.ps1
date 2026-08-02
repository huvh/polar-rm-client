param(
    [string]$Output = (Join-Path $PSScriptRoot "..\release\POLAR-RM-Client.zip")
)

$clientRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stage = Join-Path ([System.IO.Path]::GetTempPath()) "polar-rm-release"
$destination = Split-Path -Parent $Output

Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -LiteralPath $clientRoot -Destination (Join-Path $stage "rm_custom_client") -Recurse -Force
Get-ChildItem -LiteralPath (Join-Path $stage "rm_custom_client") -Directory -Recurse -Force |
    Where-Object { $_.Name -in @(".venv", "__pycache__", ".pytest_cache", "release", ".git", "tmp_render_checks", "calibrations") } |
    Remove-Item -Recurse -Force
Remove-Item -LiteralPath $Output -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath (Join-Path $stage "rm_custom_client") -DestinationPath $Output -Force
Remove-Item -LiteralPath $stage -Recurse -Force
Write-Host "Release built: $Output"
