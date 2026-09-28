[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)]
    [int]$Port = 4173,

    [ValidateRange(5, 120)]
    [int]$StartupTimeoutSeconds = 30,

    [switch]$InstallDependencies
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$packageJson = Join-Path $frontendDir "package.json"
$packageLock = Join-Path $frontendDir "package-lock.json"
$viteEntry = Join-Path $frontendDir "node_modules/vite/bin/vite.js"

if (-not (Test-Path -LiteralPath $packageJson) -or -not (Test-Path -LiteralPath $packageLock)) {
    throw "Frontend package files were not found under '$frontendDir'."
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    throw "npm.cmd was not found. Install Node.js with npm, then run this script again."
}

$shouldInstall = $InstallDependencies -or -not (Test-Path -LiteralPath $viteEntry)

if ($shouldInstall) {
    Write-Host "Installing frontend dependencies..."
    $npmCacheDir = Join-Path $repoRoot ".npm-cache"
    Push-Location $frontendDir
    try {
        & $npmCommand.Source ci --cache $npmCacheDir
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

Write-Host "Building the frontend..."
Push-Location $frontendDir
try {
    & $npmCommand.Source run build
    if ($LASTEXITCODE -ne 0) {
        throw "Frontend build failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

$previewUrl = "http://127.0.0.1:$Port/"
function Test-KnowledgeBasePreview {
    try {
        $response = Invoke-WebRequest -Uri $previewUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains("<title>KnowledgeBase</title>")
    }
    catch {
        return $false
    }
}

$previewProcess = $null
if (-not (Test-KnowledgeBasePreview)) {
    $runId = [guid]::NewGuid().ToString("N")
    $previewLogDir = Join-Path $repoRoot "runtime/frontend-preview"
    New-Item -ItemType Directory -Path $previewLogDir -Force | Out-Null
    $stdoutLog = Join-Path $previewLogDir "$Port-$runId.out.log"
    $stderrLog = Join-Path $previewLogDir "$Port-$runId.err.log"

    $previewProcess = Start-Process `
        -FilePath $npmCommand.Source `
        -ArgumentList @("run", "preview", "--", "--host", "127.0.0.1", "--port", "$Port", "--strictPort") `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $ready = $false
    do {
        if ($previewProcess.HasExited) {
            $details = @()
            if (Test-Path -LiteralPath $stderrLog) { $details += Get-Content -Raw -LiteralPath $stderrLog }
            if (Test-Path -LiteralPath $stdoutLog) { $details += Get-Content -Raw -LiteralPath $stdoutLog }
            $message = ($details -join [Environment]::NewLine).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) { $message = "Preview process exited with code $($previewProcess.ExitCode)." }
            throw "Could not start the frontend preview on port $Port. $message"
        }

        if (Test-KnowledgeBasePreview) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    if (-not $ready) {
        throw "Frontend preview did not become ready within $StartupTimeoutSeconds seconds. Check '$stderrLog'."
    }
}

Start-Process -FilePath $previewUrl
Write-Host "KnowledgeBase frontend is open at $previewUrl"
