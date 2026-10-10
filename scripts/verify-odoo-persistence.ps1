#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$composeFile = Join-Path $repositoryRoot "docker-compose.yml"
$composeArgs = @("-p", "purchaseflow-demo", "-f", $composeFile)

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments[0]) failed with exit code $LASTEXITCODE." }
}

function Invoke-ComposeQuery {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose @composeArgs @Arguments
    $nativeExitCode = $LASTEXITCODE
    if ($nativeExitCode -ne 0) { throw "docker compose query failed with exit code $nativeExitCode." }
    return (@($output) -join "").Trim()
}

function Wait-ServiceHealthy {
    param([Parameter(Mandatory)][string]$Service, [int]$TimeoutMinutes = 5)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $containerId = (Invoke-ComposeQuery -Arguments @("ps", "-q", $Service)).Trim()
    while ((Get-Date) -lt $deadline) {
        if ($containerId) {
            $health = (& docker inspect --format "{{.State.Health.Status}}" $containerId 2>$null).Trim()
            if ($health -eq "healthy") { return }
        }
        Start-Sleep -Seconds 3
        $containerId = (Invoke-ComposeQuery -Arguments @("ps", "-q", $Service)).Trim()
    }
    throw "PurchaseFlow $Service did not become healthy within $TimeoutMinutes minutes."
}

Push-Location $repositoryRoot
try {
    Invoke-Compose -Arguments @("restart", "db")
    Wait-ServiceHealthy -Service "db"
    Invoke-Compose -Arguments @("restart", "odoo")
    Wait-ServiceHealthy -Service "odoo"

    $login = Invoke-WebRequest -Uri "http://127.0.0.1:18069/web/login" -TimeoutSec 10
    if ($login.StatusCode -ne 200) { throw "Odoo login page returned HTTP $($login.StatusCode) after restart." }

    Invoke-Compose -Arguments @("restart", "api")
    Wait-ServiceHealthy -Service "api"
    Invoke-Compose -Arguments @("exec", "-T", "api", "python3", "/opt/purchaseflow/odoo-scripts/acceptance_json2.py")

    $orders = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "purchaseflow_odoo",
        "-Atqc", "SELECT count(*) FROM purchase_order WHERE purchaseflow_intent_id='PF-STAGE1-ODOO-JSON2'"
    )
    if ($orders -ne "1") { throw "Expected exactly one stable Odoo acceptance order after restart; found $orders." }

    $constraint = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "purchaseflow_odoo",
        "-Atqc", "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='purchase_order'::regclass AND pg_get_constraintdef(oid) ILIKE '%purchaseflow_intent_id%'"
    )
    if ($constraint -notmatch "UNIQUE \(purchaseflow_intent_id\)") {
        throw "The Odoo uniqueness constraint is missing after restart."
    }

    Write-Host "PostgreSQL and Odoo restarted; the same verified Odoo draft remains readable and unique."
}
finally {
    Pop-Location
}
