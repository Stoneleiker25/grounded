# Grounded — restore, start the API and frontend, health-check, log to BUILD_LOG.md.
#
#   .\start.ps1                        start everything
#   .\start.ps1 -Test                  run the test suite instead
#   .\start.ps1 -ApiPort 8001 -WebPort 5174
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173,
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# --- build log -------------------------------------------------------------
# Appends to BUILD_LOG.md in this folder — one continuous history across every run,
# including the entries from the earlier Flask version of this project.
$LogFile   = Join-Path $Root "BUILD_LOG.md"
$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$SessionId = Get-Date -Format "yyyyMMdd-HHmmss"

function Test-RedFlags([string]$Text) {
    $flags = @()
    $patterns = @{
        "pip install failed"   = "ERROR:|Could not find a version|No matching distribution"
        "missing module"       = "ModuleNotFoundError|ImportError"
        "port in use"          = "Address already in use|WinError 10048|only one usage of each socket"
        "python traceback"     = "Traceback \(most recent call last\)"
        "connection refused"   = "ConnectionRefusedError|ERR_CONNECTION_REFUSED|actively refused"
        "database locked"      = "database is locked"
        "constraint violation" = "IntegrityError|CHECK constraint failed|FOREIGN KEY constraint failed"
        "missing api key"      = "ANTHROPIC_API_KEY is not set|authentication_error|invalid x-api-key"
        "llm request failed"   = "LLM request failed|rate_limit|overloaded_error"
        "cors blocked"         = "CORS|Access-Control-Allow-Origin"
        "server error 500"     = "500 Internal Server Error"
    }
    foreach ($name in $patterns.Keys) {
        if ($Text -match $patterns[$name]) { $flags += $name }
    }
    return $flags
}

function Write-BuildLog {
    param(
        [string]$Overall, [string]$Restore, [string]$Start, [string]$Health,
        [string]$HealthDetail, [string[]]$RestoreOutput, [string[]]$ServerLines, [string[]]$RedFlags
    )
    $unique = $RedFlags | Select-Object -Unique
    $flagLine = if ($unique.Count -gt 0) {
        "RED FLAGS: $($unique -join ', ')"
    } else { "No red flags detected." }

    $entry = @(
        "---", "",
        "### $StartedAt | Session $SessionId", "",
        "| Step | Status |", "|------|--------|",
        "| **Overall** | $Overall |",
        "| Restore (``pip install``) | $Restore |",
        "| Start live (``uvicorn``) | $Start |",
        "| Health check (``GET /api/health``) | $Health |", "",
        "**Stack:** FastAPI + vanilla JS  ",
        "**URL:** ``http://127.0.0.1:$WebPort``  ",
        "**API:** ``http://127.0.0.1:$ApiPort``  ",
        "**Health detail:** $HealthDetail  ",
        "**Logged:** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  ", "",
        $flagLine, "",
        "<details>", "<summary>Restore output</summary>", "", '```',
        (($RestoreOutput | Select-Object -Last 40) -join "`n"), '```', "", "</details>", "",
        "<details>", "<summary>Server output</summary>", "", '```',
        (($ServerLines | Select-Object -Last 40) -join "`n"), '```', "", "</details>", ""
    )
    Add-Content -Path $LogFile -Value ($entry -join "`n")
    Write-Host "Appended run to BUILD_LOG.md" -ForegroundColor DarkGray
}

$restoreOutput = @(); $serverLines = @(); $redFlags = @()
$restoreStatus = "OK"; $startStatus = "OK"; $healthStatus = "SKIPPED"
$overallStatus = "OK"; $healthDetail = "Not run"

function Assert-PortFree([int]$Port, [string]$Label) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "Port $Port ($Label) is already in use." -ForegroundColor Red
        Write-Host "Stop the other process, or re-run with a different port:" -ForegroundColor Yellow
        Write-Host "    .\start.ps1 -ApiPort 8001 -WebPort 5174" -ForegroundColor Yellow
        $script:redFlags += "port in use"
        Write-BuildLog "FAILED" $script:restoreStatus "PORT IN USE" "SKIPPED" `
            "Port $Port ($Label) already in use" $script:restoreOutput `
            @("Port $Port ($Label) is already in use.") $script:redFlags
        exit 1
    }
}

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Installing dependencies..." -ForegroundColor Cyan
& $Py -m pip install --quiet --upgrade pip 2>&1 | Out-Null
$restoreOutput = & $Py -m pip install -r requirements.txt 2>&1 | ForEach-Object { $_.ToString() }
$redFlags += Test-RedFlags ($restoreOutput -join "`n")
if ($LASTEXITCODE -ne 0) {
    $restoreStatus = "FAILED"; $overallStatus = "FAILED"
    Write-BuildLog $overallStatus $restoreStatus "NOT STARTED" "SKIPPED" "Restore failed" $restoreOutput @() $redFlags
    Write-Host "Dependency install failed. See BUILD_LOG.md." -ForegroundColor Red
    exit 1
}

if ($Test) {
    & $Py -m pytest app/tests -q
    exit $LASTEXITCODE
}

if (-not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "No .env file found." -ForegroundColor Red
    Write-Host "  copy .env.example .env" -ForegroundColor Yellow
    Write-Host "  then add your Anthropic API key (https://console.anthropic.com)" -ForegroundColor Yellow
    exit 1
}
if (-not (Select-String -Path ".env" -Pattern "^GROUNDED_ANTHROPIC_API_KEY=sk-" -Quiet)) {
    Write-Host "GROUNDED_ANTHROPIC_API_KEY is not set in .env." -ForegroundColor Red
    exit 1
}

Assert-PortFree $ApiPort "API"
Assert-PortFree $WebPort "frontend"

# The frontend reads the API base from this generated file, so changing -ApiPort
# does not require editing any source.
Set-Content -Path "app\frontend\config.js" `
    -Value "window.GROUNDED_API = 'http://127.0.0.1:$ApiPort';"

$api = Start-Process -FilePath $Py `
    -ArgumentList "-m","uvicorn","app.backend.main:app","--host","127.0.0.1","--port","$ApiPort" `
    -WorkingDirectory $Root -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput "$env:TEMP\grounded-api.log" `
    -RedirectStandardError  "$env:TEMP\grounded-api.err"

Write-Host "Waiting for the API..." -ForegroundColor Cyan
$ready = $false
foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 500
    try {
        if ((Invoke-WebRequest "http://127.0.0.1:$ApiPort/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) {
            $ready = $true; break
        }
    } catch { }
    if ($api.HasExited) { break }
}
$serverLines += Get-Content "$env:TEMP\grounded-api.log" -ErrorAction SilentlyContinue
$serverLines += Get-Content "$env:TEMP\grounded-api.err" -ErrorAction SilentlyContinue
$redFlags += Test-RedFlags ($serverLines -join "`n")

if (-not $ready) {
    $startStatus = "FAILED"; $healthStatus = "FAILED"; $overallStatus = "FAILED"
    $healthDetail = "API never answered /api/health"
    Write-Host "API did not start. Last output:" -ForegroundColor Red
    $serverLines | Select-Object -Last 25 | ForEach-Object { Write-Host "  $_" }
    Write-BuildLog $overallStatus $restoreStatus $startStatus $healthStatus `
        $healthDetail $restoreOutput $serverLines $redFlags
    if (-not $api.HasExited) { Stop-Process -Id $api.Id -Force }
    exit 1
}
$healthStatus = "OK"; $healthDetail = "HTTP 200 from /api/health"
Write-Host "  API ready on http://127.0.0.1:$ApiPort" -ForegroundColor Green
Write-BuildLog $overallStatus $restoreStatus $startStatus $healthStatus `
    $healthDetail $restoreOutput $serverLines $redFlags

$web = Start-Process -FilePath $Py `
    -ArgumentList "-m","http.server","$WebPort","--bind","127.0.0.1","--directory","app/frontend" `
    -WorkingDirectory $Root -PassThru -WindowStyle Hidden

Write-Host ""
Write-Host "  Grounded is running:  http://127.0.0.1:$WebPort" -ForegroundColor Green
Write-Host "  API docs:             http://127.0.0.1:$ApiPort/docs" -ForegroundColor DarkGray
Write-Host "  Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host ""
Start-Process "http://127.0.0.1:$WebPort"

try {
    Wait-Process -Id $api.Id
} finally {
    foreach ($p in @($api, $web)) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "Stopped." -ForegroundColor DarkGray
}
