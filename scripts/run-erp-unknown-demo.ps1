#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$apiBase = "http://127.0.0.1:18000"

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}

function Save-ScenarioReference {
    param([Parameter(Mandatory)]$Procurement)
    $scenarioPath = Join-Path $local "unknown-demo.json"
    $null = New-Item -ItemType Directory -Force -Path $local
    $scenario = @{
        id = $Procurement.id
        request_number = $Procurement.request_number
        external_intent_id = $Procurement.erp.external_intent_id
    }
    Set-Content -LiteralPath $scenarioPath -Encoding utf8NoBOM -Value ($scenario | ConvertTo-Json -Compress)
}

if ((Invoke-RestMethod -Uri "$apiBase/health/ready" -TimeoutSec 15).status -ne "ready") {
    throw "PurchaseFlow API is not ready. Run scripts/start-demo.ps1 first."
}

$procurementSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$null = Invoke-RestMethod -Uri "$apiBase/api/demo/sessions" -Method Post `
    -WebSession $procurementSession -ContentType "application/json" `
    -Body (@{ role = "procurement"; email = "procurement@demo.local" } | ConvertTo-Json -Compress)
$existing = Invoke-RestMethod -Uri "$apiBase/api/procurements" -WebSession $procurementSession -TimeoutSec 20
$reusable = @($existing | Where-Object {
    $_.reason -eq "Controlled demo: recover an Odoo draft after its create response is lost." -and
    $_.status -eq "erp_unknown" -and $_.erp.state -eq "unknown" -and $_.erp.attempts -eq 1
} | Select-Object -First 1)
if ($reusable.Count -gt 0 -and $reusable[0].erp.external_intent_id) {
    Save-ScenarioReference -Procurement $reusable[0]
    Write-Host "PASS: Reused existing real-Odoo UNKNOWN scenario $($reusable[0].request_number); no new draft was created."
    return
}

$workerId = (& docker compose @compose ps -q worker).Trim()
if ($LASTEXITCODE -ne 0 -or -not $workerId) { throw "PurchaseFlow worker is not running." }
$workerState = (& docker inspect --format "{{.State.Status}}" $workerId 2>$null).Trim()
if ($workerState -ne "running") { throw "PurchaseFlow worker must be running before this demo starts." }

$workerPaused = $false
Push-Location $root
try {
    Invoke-Compose -Arguments @("stop", "--timeout", "20", "worker")
    $workerPaused = $true

    $requesterSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $null = Invoke-RestMethod -Uri "$apiBase/api/demo/sessions" -Method Post `
        -WebSession $requesterSession -ContentType "application/json" `
        -Body (@{ role = "requester"; email = "requester.ops@demo.local"; department_code = "operations" } | ConvertTo-Json -Compress)

    $requestBody = [ordered]@{
        department_code = "operations"
        supplier_ref = "PF-VENDOR-OFFICE"
        reason = "Controlled demo: recover an Odoo draft after its create response is lost."
        currency_code = "CNY"
        lines = @(@{ sku = "PF-OFFICE-SET"; quantity = 1; unit_price = "1200.00" })
    } | ConvertTo-Json -Depth 6 -Compress
    $request = Invoke-RestMethod -Uri "$apiBase/api/procurements" -Method Post `
        -WebSession $requesterSession -ContentType "application/json" `
        -Headers @{ "Idempotency-Key" = "unknown-demo-$([guid]::NewGuid().ToString('N'))" } -Body $requestBody -TimeoutSec 20
    if ($request.status -ne "draft") { throw "The controlled request did not start as a draft." }
    $submitted = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($request.id)/submit" -Method Post `
        -WebSession $requesterSession -ContentType "application/json" `
        -Body (@{ expected_version = $request.version } | ConvertTo-Json -Compress) -TimeoutSec 20

    $managerSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $null = Invoke-RestMethod -Uri "$apiBase/api/demo/sessions" -Method Post `
        -WebSession $managerSession -ContentType "application/json" `
        -Body (@{ role = "manager"; email = "manager.ops@demo.local"; department_code = "operations" } | ConvertTo-Json -Compress)
    $approved = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($request.id)/decision" -Method Post `
        -WebSession $managerSession -ContentType "application/json" `
        -Headers @{ "Idempotency-Key" = "unknown-demo-approval-$([guid]::NewGuid().ToString('N'))" } `
        -Body (@{ decision = "approve"; expected_version = $submitted.version; reason = "Approved for controlled response-loss recovery." } | ConvertTo-Json -Compress) `
        -TimeoutSec 20
    if ($approved.status -ne "approved") { throw "The manager approval did not create a pending ERP intent." }

    Invoke-Compose -Arguments @("exec", "-T", "api", "python", "-m", "app.unknown_demo", "--procurement-id", $request.id)
    $observed = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($request.id)" -WebSession $procurementSession -TimeoutSec 20
    if ($observed.status -ne "erp_unknown" -or $observed.erp.state -ne "unknown" -or $observed.erp.attempts -ne 1) {
        throw "The app did not retain the one-attempt UNKNOWN state after the Odoo response was dropped."
    }

    Save-ScenarioReference -Procurement $observed
    Write-Host "PASS: Real Odoo created the draft, PurchaseFlow recorded UNKNOWN after one dispatch, and the procurement UI can now reconcile it."
    Write-Host "Synthetic request: $($request.request_number). The scenario reference is in ignored .local/unknown-demo.json."
}
finally {
    if ($workerPaused) { Invoke-Compose -Arguments @("start", "worker") }
    Pop-Location
}
