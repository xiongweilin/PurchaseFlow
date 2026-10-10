#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$base = "http://127.0.0.1"
$scenarioPath = Join-Path $root ".local\unknown-demo.json"

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}

function Wait-ServiceHealthy {
    param([Parameter(Mandatory)][string]$Service, [int]$TimeoutMinutes = 4)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    do {
        $id = (& docker compose @compose ps -q $Service).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to inspect PurchaseFlow $Service." }
        if ($id) {
            $health = (& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim()
            if ($health -eq "healthy") { return }
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    & docker compose @compose logs --tail 60 $Service
    throw "PurchaseFlow $Service did not become healthy after restart."
}

function Ensure-ProjectRunning {
    & docker compose @compose up -d db odoo api worker frontend mailpit n8n
    if ($LASTEXITCODE -ne 0) { throw "Unable to restore the PurchaseFlow-only service stack." }
    foreach ($service in @("db", "odoo", "api", "frontend", "n8n", "mailpit")) {
        Wait-ServiceHealthy -Service $service
    }
    $workerId = (& docker compose @compose ps -q worker).Trim()
    if (-not $workerId -or (& docker inspect --format "{{.State.Status}}" $workerId 2>$null).Trim() -ne "running") {
        throw "PurchaseFlow worker is not running after service restoration."
    }
}

if (-not (Test-Path -LiteralPath $scenarioPath -PathType Leaf)) {
    throw "Run scripts/run-erp-unknown-demo.ps1 and the browser recovery before checking persistence."
}
$scenario = Get-Content -LiteralPath $scenarioPath -Raw -Encoding utf8 | ConvertFrom-Json
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$null = Invoke-RestMethod -Uri "$base`:18000/api/demo/sessions" -Method Post `
    -WebSession $session -ContentType "application/json" `
    -Body (@{ role = "procurement"; email = "procurement@demo.local" } | ConvertTo-Json -Compress)
$before = Invoke-RestMethod -Uri "$base`:18000/api/procurements/$($scenario.id)" -WebSession $session -TimeoutSec 20
if ($before.status -ne "closed" -or $before.erp.state -ne "verified" -or
    $before.erp.external_intent_id -ne $scenario.external_intent_id) {
    throw "The pre-restart scenario is not closed with the expected verified ERP intent."
}
$mailBefore = Invoke-RestMethod -Uri "$base`:18025/api/v1/messages" -TimeoutSec 15
$mailCountBefore = @($mailBefore.messages).Count

$restartStarted = $false
$completed = $false
Push-Location $root
try {
    $restartStarted = $true
    Write-Host "Restarting only PurchaseFlow PostgreSQL, Odoo, API, worker, frontend, n8n, and Mailpit containers; no volume is removed."
    Invoke-Compose -Arguments @("restart", "db")
    Wait-ServiceHealthy -Service "db"
    Invoke-Compose -Arguments @("restart", "odoo")
    Wait-ServiceHealthy -Service "odoo"
    foreach ($service in @("api", "worker", "frontend", "n8n", "mailpit")) {
        Invoke-Compose -Arguments @("restart", $service)
        if ($service -eq "worker") {
            $workerId = (& docker compose @compose ps -q worker).Trim()
            if (-not $workerId -or (& docker inspect --format "{{.State.Status}}" $workerId 2>$null).Trim() -ne "running") {
                throw "PurchaseFlow worker is not running after restart."
            }
        }
        else {
            Wait-ServiceHealthy -Service $service
        }
    }

    $ready = Invoke-RestMethod -Uri "$base`:18000/health/ready" -TimeoutSec 20
    if ($ready.status -ne "ready") { throw "PurchaseFlow API did not become ready after restart." }
    & (Join-Path $PSScriptRoot "verify-demo.ps1")

    $after = Invoke-RestMethod -Uri "$base`:18000/api/procurements/$($scenario.id)" -WebSession $session -TimeoutSec 20
    if ($after.request_number -ne $before.request_number -or $after.status -ne "closed" -or
        $after.erp.state -ne "verified" -or $after.erp.external_intent_id -ne $scenario.external_intent_id) {
        throw "The PurchaseFlow request or verified ERP intent changed across container restart."
    }
    Invoke-Compose -Arguments @("exec", "-T", "api", "python", "-m", "app.verify_persisted_intent", "--external-intent-id", $scenario.external_intent_id)

    $mailAfter = Invoke-RestMethod -Uri "$base`:18025/api/v1/messages" -TimeoutSec 15
    if (@($mailAfter.messages).Count -lt $mailCountBefore) {
        throw "Mailpit messages were lost across container restart."
    }
    Write-Host "PASS: PostgreSQL-backed request, live Odoo draft, active n8n workflows, and Mailpit messages persisted across service restarts."
    $completed = $true
}
finally {
    try {
        if ($restartStarted -and -not $completed) { Ensure-ProjectRunning }
    }
    catch {
        Write-Warning "Could not verify full service health during cleanup: $($_.Exception.Message)"
    }
    finally { Pop-Location }
}
