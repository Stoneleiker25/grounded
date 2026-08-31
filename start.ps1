# Restores dependencies, health-checks the app, starts Flask live, and appends to BUILD_LOG.md
param(
    [int]$Port = 5000,
    [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogFile = Join-Path $ProjectRoot "BUILD_LOG.md"
$Url = "http://${HostName}:$Port/"
$StartedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$SessionId = Get-Date -Format "yyyyMMdd-HHmmss"

Set-Location $ProjectRoot

function Write-LogBlock {
    param([string[]]$Lines)
    Add-Content -Path $LogFile -Value ($Lines -join "`n")
    Add-Content -Path $LogFile -Value ""
}

function Test-RedFlags {
    param([string]$Text)

    $flags = @()
    $patterns = @{
        "pip install failed" = "ERROR:|Could not find a version|No matching distribution"
        "missing module" = "ModuleNotFoundError|ImportError"
        "template missing" = "TemplateNotFound"
        "port in use" = "Address already in use|WinError 10048"
        "python traceback" = "Traceback \(most recent call last\)"
        "connection refused" = "ConnectionRefusedError|ERR_CONNECTION_REFUSED|actively refused"
        "wrong route / 404" = '"GET / HTTP/1\.1" 404|404 Not Found'
        "server error 500" = '"GET / HTTP/1\.1" 500|500 Internal Server Error'
    }

    foreach ($name in $patterns.Keys) {
        if ($Text -match $patterns[$name]) {
            $flags += $name
        }
    }

    return $flags
}

function Write-SessionLog {
    param(
        [string]$OverallStatus,
        [string]$RestoreStatus,
        [string]$StartStatus,
        [string]$HealthStatus,
        [string]$HealthDetail,
        [string[]]$RestoreOutput,
        [string[]]$ServerLines,
        [string[]]$RedFlags,
        [string]$ServerSummary = "Server output"
    )

    $loggedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $uniqueFlags = $RedFlags | Select-Object -Unique
    $flagLine = if ($uniqueFlags.Count -gt 0) { "🚩 **Red flags:** $($uniqueFlags -join ', ')" } else { "No red flags detected." }

    $entry = @(
        "---",
        "",
        "### $StartedAt | Session $SessionId",
        "",
        "| Step | Status |",
        "|------|--------|",
        "| **Overall** | $OverallStatus |",
        "| Restore (`pip install`) | $RestoreStatus |",
        "| Start live (`python app.py`) | $StartStatus |",
        "| Health check (`GET /`) | $HealthStatus |",
        "",
        "**URL:** ``$Url``  ",
        "**Health detail:** $HealthDetail  ",
        "**Logged:** $loggedAt  ",
        "",
        $flagLine,
        "",
        "<details>",
        "<summary>Restore output</summary>",
        "",
        '```',
        ($RestoreOutput -join "`n"),
        '```',
        "",
        "</details>",
        "",
        "<details>",
        "<summary>$ServerSummary</summary>",
        "",
        '```',
        ($ServerLines -join "`n"),
        '```',
        "",
        "</details>"
    )

    Write-LogBlock -Lines $entry
    Write-Host "Log appended to BUILD_LOG.md" -ForegroundColor DarkGray
}

$restoreOutput = @()
$restoreStatus = "✅ OK"
$startStatus = "✅ OK"
$healthStatus = "⚠️ SKIPPED"
$overallStatus = "✅ OK"
$redFlags = @()
$healthDetail = "Not run"
$serverLines = @()
$serverProcess = $null
$logWritten = $false

Write-Host ""
Write-Host "=== Grounded: restore + start live ===" -ForegroundColor Cyan
Write-Host "Logging to BUILD_LOG.md" -ForegroundColor DarkGray
Write-Host ""

# --- RESTORE ---
Write-Host "[1/3] Restore dependencies..." -ForegroundColor Yellow
try {
    $restoreOutput = python -m pip install -r requirements.txt 2>&1 | ForEach-Object { $_.ToString() }
    $restoreText = $restoreOutput -join "`n"
    if ($LASTEXITCODE -ne 0) {
        $restoreStatus = "❌ FAILED"
        $overallStatus = "❌ FAILED"
    }
    $redFlags += Test-RedFlags -Text $restoreText
}
catch {
    $restoreStatus = "❌ FAILED"
    $overallStatus = "❌ FAILED"
    $restoreOutput = @($_.Exception.Message)
    $redFlags += "restore exception"
}

Write-Host "      $restoreStatus"

# --- START LIVE ---
Write-Host "[2/3] Starting Flask on $Url ..." -ForegroundColor Yellow

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $startStatus = "⚠️ PORT IN USE"
    $overallStatus = "❌ FAILED"
    $redFlags += "port in use"
    $serverLines += "Port $Port is already in use. Stop the other process or change the port."
    Write-Host "      ⚠️ Port $Port already in use" -ForegroundColor Red
}
else {
    $serverProcess = Start-Process -FilePath "python" -ArgumentList "app.py" -WorkingDirectory $ProjectRoot -PassThru -RedirectStandardOutput "$env:TEMP\grounded-stdout-$SessionId.log" -RedirectStandardError "$env:TEMP\grounded-stderr-$SessionId.log" -WindowStyle Hidden

    Start-Sleep -Seconds 3

    $stdout = Get-Content "$env:TEMP\grounded-stdout-$SessionId.log" -ErrorAction SilentlyContinue
    $stderr = Get-Content "$env:TEMP\grounded-stderr-$SessionId.log" -ErrorAction SilentlyContinue
    $serverLines += $stdout
    $serverLines += $stderr
    $redFlags += Test-RedFlags -Text (($stdout + $stderr) -join "`n")

    if ($serverProcess.HasExited) {
        $startStatus = "❌ FAILED"
        $overallStatus = "❌ FAILED"
        Write-Host "      ❌ Server exited immediately" -ForegroundColor Red
    }
    else {
        Write-Host "      ✅ Server process started (PID $($serverProcess.Id))"

        Write-Host "[3/3] Health check $Url ..." -ForegroundColor Yellow
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
            if ($response.StatusCode -eq 200) {
                $healthStatus = "✅ OK"
                $healthDetail = "HTTP $($response.StatusCode) - $($response.RawContentLength) bytes"
                Write-Host "      ✅ $healthDetail" -ForegroundColor Green
            }
            else {
                $healthStatus = "🚩 UNEXPECTED STATUS"
                $healthDetail = "HTTP $($response.StatusCode)"
                $overallStatus = "❌ FAILED"
                $redFlags += "unexpected http status"
                Write-Host "      🚩 $healthDetail" -ForegroundColor Red
            }
        }
        catch {
            $healthStatus = "❌ FAILED"
            $healthDetail = $_.Exception.Message
            $overallStatus = "❌ FAILED"
            $redFlags += "health check connection error"
            Write-Host "      ❌ $healthDetail" -ForegroundColor Red
        }

        Write-SessionLog -OverallStatus $overallStatus -RestoreStatus $restoreStatus -StartStatus $startStatus -HealthStatus $healthStatus -HealthDetail $healthDetail -RestoreOutput $restoreOutput -ServerLines $serverLines -RedFlags $redFlags -ServerSummary "Server output (at startup)"
        $logWritten = $true

        Write-Host ""
        Write-Host "=== Live at $Url (Ctrl+C to stop) ===" -ForegroundColor Cyan
        Write-Host ""

        try {
            Wait-Process -Id $serverProcess.Id
        }
        finally {
            if (-not $serverProcess.HasExited) {
                Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

if (-not $logWritten) {
    Write-SessionLog -OverallStatus $overallStatus -RestoreStatus $restoreStatus -StartStatus $startStatus -HealthStatus $healthStatus -HealthDetail $healthDetail -RestoreOutput $restoreOutput -ServerLines $serverLines -RedFlags $redFlags
}

if ($overallStatus -match "FAILED") {
    exit 1
}
