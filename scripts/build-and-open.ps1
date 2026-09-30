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
$venvPython = Join-Path $repoRoot ".venv/Scripts/python.exe"
$packageJson = Join-Path $frontendDir "package.json"
$packageLock = Join-Path $frontendDir "package-lock.json"
$viteEntry = Join-Path $frontendDir "node_modules/vite/bin/vite.js"
$reactPackage = Join-Path $frontendDir "node_modules/react/package.json"
$backendPort = 8000
$backendUrl = "http://127.0.0.1:$backendPort"
$backendOpenApiUrl = "$backendUrl/openapi.json"
$requiredBackendPaths = @(
    "/api/imports/blank-document",
    "/api/annotations/stale",
    "/api/context/export"
)
$incompatibleBackendMessage = "Port 8000 is running an incompatible/outdated KnowledgeBase backend. Stop the old backend and run this script again."

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "The repository .venv is missing. Create it and install the backend requirements first:"
    Write-Host "  python -m venv .venv"
    Write-Host "  .\.venv\Scripts\Activate.ps1"
    Write-Host "  python -m pip install -r backend/requirements-dev.txt"
    exit 1
}

& $venvPython -c "import uvicorn"
if ($LASTEXITCODE -ne 0) {
    Write-Host "The repository .venv is missing backend dependencies. Activate it and run:"
    Write-Host "  python -m pip install -r backend/requirements-dev.txt"
    exit 1
}

if (-not (Test-Path -LiteralPath $packageJson) -or -not (Test-Path -LiteralPath $packageLock)) {
    throw "Frontend package files were not found under '$frontendDir'."
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    throw "npm.cmd was not found. Install Node.js with npm, then run this script again."
}

$shouldInstall = $InstallDependencies -or
    -not (Test-Path -LiteralPath $viteEntry) -or
    -not (Test-Path -LiteralPath $reactPackage)

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

function Test-LocalTcpPort {
    param([int]$PortNumber)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect("127.0.0.1", $PortNumber, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(700)) { return $false }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-MissingBackendPaths {
    param([object]$OpenApi, [string[]]$RequiredPaths)

    if (-not $OpenApi -or -not $OpenApi.paths) { return $RequiredPaths }
    $actualPaths = @($OpenApi.paths.PSObject.Properties | ForEach-Object { $_.Name })
    return @($RequiredPaths | Where-Object { $_ -notin $actualPaths })
}

$backendLogDir = Join-Path $repoRoot "runtime/backend-local"
$backendProcess = $null
if (Test-LocalTcpPort -PortNumber $backendPort) {
    try {
        $openApi = Invoke-RestMethod -Uri $backendOpenApiUrl -TimeoutSec 3 -ErrorAction Stop
    }
    catch {
        throw $incompatibleBackendMessage
    }

    if ((Get-MissingBackendPaths -OpenApi $openApi -RequiredPaths $requiredBackendPaths).Count -gt 0) {
        throw $incompatibleBackendMessage
    }
}
else {
    New-Item -ItemType Directory -Path $backendLogDir -Force | Out-Null
    $runId = [guid]::NewGuid().ToString("N")
    $backendStdout = Join-Path $backendLogDir "$runId.out.log"
    $backendStderr = Join-Path $backendLogDir "$runId.err.log"
    $backendProcess = Start-Process `
        -FilePath $venvPython `
        -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "$backendPort") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendStdout `
        -RedirectStandardError $backendStderr `
        -PassThru

    $backendDeadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $backendReady = $false
    do {
        if ($backendProcess.HasExited) {
            $details = @()
            if (Test-Path -LiteralPath $backendStderr) { $details += Get-Content -Raw -LiteralPath $backendStderr }
            if (Test-Path -LiteralPath $backendStdout) { $details += Get-Content -Raw -LiteralPath $backendStdout }
            $message = ($details -join [Environment]::NewLine).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) { $message = "Backend process exited with code $($backendProcess.ExitCode)." }
            throw "Could not start the backend. $message"
        }

        if (Test-LocalTcpPort -PortNumber $backendPort) {
            try {
                $openApi = Invoke-RestMethod -Uri $backendOpenApiUrl -TimeoutSec 2 -ErrorAction Stop
                if ((Get-MissingBackendPaths -OpenApi $openApi -RequiredPaths $requiredBackendPaths).Count -gt 0) {
                    throw $incompatibleBackendMessage
                }
                $backendReady = $true
                break
            }
            catch {
                if ($_.Exception.Message -eq $incompatibleBackendMessage) { throw }
            }
        }

        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $backendDeadline)

    if (-not $backendReady) {
        throw "Backend did not become ready within $StartupTimeoutSeconds seconds. Check '$backendStderr'."
    }
}

Write-Host "Backend Ready: $backendUrl"

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
Write-Host "Frontend Ready: $previewUrl"
Write-Host "Browser Open"
