param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$workspaceRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$workspaceName = Split-Path -Leaf $workspaceRoot
$workspaceParent = Split-Path -Parent $workspaceRoot
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $workspaceParent "${workspaceName}_clean_${timestamp}.zip"
}

$outputFullPath = [System.IO.Path]::GetFullPath($OutputPath)
$stageRoot = Join-Path $workspaceParent "${workspaceName}_package_stage_${timestamp}"

if ($outputFullPath.StartsWith($workspaceRoot + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Output ZIP must be outside the workspace to avoid packaging itself: $outputFullPath"
}

if (Test-Path -LiteralPath $stageRoot) {
    throw "Staging directory already exists: $stageRoot"
}

$excludedDirectories = @(
    (Join-Path $workspaceRoot "backend\venv"),
    (Join-Path $workspaceRoot "frontend\node_modules"),
    (Join-Path $workspaceRoot "frontend\dist"),
    (Join-Path $workspaceRoot "backend\temp"),
    (Join-Path $workspaceRoot "temp"),
    (Join-Path $workspaceRoot "backend\uploads"),
    (Join-Path $workspaceRoot "backend\outputs"),
    (Join-Path $workspaceRoot "uploads"),
    (Join-Path $workspaceRoot "outputs"),
    (Join-Path $workspaceRoot "backups")
)

try {
    New-Item -ItemType Directory -Path $stageRoot | Out-Null

    $robocopyArgs = @(
        $workspaceRoot,
        $stageRoot,
        "/E",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NJH",
        "/NJS",
        "/NP",
        "/XD"
    ) + $excludedDirectories + @(
        "/XF",
        "*.zip",
        "*.pyc"
    )

    & robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed with exit code $LASTEXITCODE."
    }

    Get-ChildItem -LiteralPath $stageRoot -Recurse -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force

    if (Test-Path -LiteralPath $outputFullPath) {
        Remove-Item -LiteralPath $outputFullPath -Force
    }

    Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $outputFullPath -CompressionLevel Optimal

    $sizeMb = [math]::Round((Get-Item -LiteralPath $outputFullPath).Length / 1MB, 2)
    Write-Host "Created clean package:"
    Write-Host "  $outputFullPath"
    Write-Host "Size: $sizeMb MB"
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        $resolvedStage = (Resolve-Path -LiteralPath $stageRoot).Path
        if (-not $resolvedStage.StartsWith($workspaceParent + "\", [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refused to remove staging directory outside workspace parent: $resolvedStage"
        }

        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
