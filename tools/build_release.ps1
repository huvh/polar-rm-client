param(
    [string]$Output = (Join-Path $PSScriptRoot "..\release\POLAR-RM-Client.zip"),
    [string]$GitRef = "HEAD",
    [switch]$SkipFfmpeg
)

$ErrorActionPreference = "Stop"
$clientRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputPath = [System.IO.Path]::GetFullPath($Output)
$destination = Split-Path -Parent $outputPath
$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("polar-rm-release-" + [guid]::NewGuid().ToString("N"))
$stageClient = Join-Path $stageRoot "rm_custom_client"

function Assert-UnderPath([string]$Path, [string]$Root) {
    $full = [System.IO.Path]::GetFullPath($Path)
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $full.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe release path outside expected root: $full"
    }
}

try {
    New-Item -ItemType Directory -Force -Path $stageClient | Out-Null
    New-Item -ItemType Directory -Force -Path $destination | Out-Null

    # Export the immutable Git tree, not working-tree files.  In particular,
    # this prevents an operator's locally edited configs/default.json (or any
    # untracked protocol extracts/cache) from leaking into a release archive.
    $sourceArchive = Join-Path $stageRoot "tracked-source.zip"
    & git -C $clientRoot archive "--format=zip" "--output=$sourceArchive" $GitRef
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sourceArchive -PathType Leaf)) {
        throw "git archive failed for ref '$GitRef'"
    }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $stageClient -Force
    $commit = (& git -C $clientRoot rev-parse $GitRef).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($commit)) {
        throw "git rev-parse failed for ref '$GitRef'"
    }
    Set-Content -LiteralPath (Join-Path $stageClient "BUILD_COMMIT.txt") -Value $commit -Encoding ASCII

    if (-not $SkipFfmpeg) {
        $python = Join-Path $clientRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
        $ffmpeg = & $python -c "from rm_client.backend.video_backend import resolve_ffmpeg_executable; print(resolve_ffmpeg_executable() or '')"
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ffmpeg)) {
            throw "ffmpeg unavailable. Install requirements.txt or pass -SkipFfmpeg for a non-field debug bundle."
        }
        $binDir = Join-Path $stageClient "bin"
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        Copy-Item -LiteralPath $ffmpeg.Trim() -Destination (Join-Path $binDir "ffmpeg.exe") -Force
    }

    $required = @(
        "rm_client\backend\manager.py",
        "rm_client\backend\mqtt_backend.py",
        "rm_client\backend\protocol.py",
        "rm_client\backend\readiness.py",
        "rm_client\backend\safety.py",
        "rm_client\backend\serial_backend.py",
        "rm_client\backend\video_backend.py",
        "rm_client\hero_lob.py",
        "rm_client\auto_spin.py",
        "rm_client\native_viewer_telemetry.py",
        "rm_client\ui\jello_clickgui.py",
        "rm_client\ui\minecraft_hud.py",
        "rm_client\ui\polar_app.py",
        "configs\default.json"
    )
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $stageClient $relative) -PathType Leaf)) {
            throw "Release is incomplete: missing $relative"
        }
    }

    $configPath = Join-Path $stageClient "configs\default.json"
    $null = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $python = Join-Path $clientRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
    & $python -m compileall -q $stageClient
    if ($LASTEXITCODE -ne 0) { throw "Release Python compile check failed" }
    $bytecodeCaches = Get-ChildItem -LiteralPath $stageClient -Directory -Recurse -Force |
        Where-Object { $_.Name -eq "__pycache__" }
    foreach ($cache in $bytecodeCaches) {
        Assert-UnderPath $cache.FullName $stageClient
        Remove-Item -LiteralPath $cache.FullName -Recurse -Force
    }

    if (Test-Path -LiteralPath $outputPath) {
        Assert-UnderPath $outputPath $destination
        Remove-Item -LiteralPath $outputPath -Force
    }
    Compress-Archive -LiteralPath $stageClient -DestinationPath $outputPath -CompressionLevel Optimal
    Write-Host "Release built and verified: $outputPath"
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Assert-UnderPath $stageRoot ([System.IO.Path]::GetTempPath())
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
