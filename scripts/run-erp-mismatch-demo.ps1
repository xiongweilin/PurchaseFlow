#Requires -Version 7.0
param(
    [switch]$Prepare,
    [switch]$Restore
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([int]$Prepare + [int]$Restore -ne 1) {
    throw "Specify exactly one of -Prepare or -Restore."
}

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$scenarioPath = Join-Path $local "erp-mismatch-demo.json"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$apiBase = "http://127.0.0.1:18000"
$reason = "Controlled demo: recover from a real Odoo field mismatch."

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}

function New-DemoSession {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][string]$Email,
        [string]$DepartmentCode
    )
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $body = @{ role = $Role; email = $Email }
    if ($DepartmentCode) { $body.department_code = $DepartmentCode }
    $null = Invoke-RestMethod -Uri "$apiBase/api/demo/sessions" -Method Post `
        -WebSession $session -ContentType "application/json" `
        -Body ($body | ConvertTo-Json -Compress) -TimeoutSec 15
    return $session
}

function Get-Request {
    param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)]$Session)
    return Invoke-RestMethod -Uri "$apiBase/api/procurements/$Id" -WebSession $Session -TimeoutSec 15
}

function Invoke-OdooMismatchTool {
    param([Parameter(Mandatory)][string]$Mode, [Parameter(Mandatory)][string]$ProcurementId)
    Invoke-Compose -Arguments @("exec", "-T", "api", "python", "-m", "app.odoo_mismatch_demo", "--mode", $Mode, "--procurement-id", $ProcurementId)
}

function Assert-Ready {
    $health = Invoke-RestMethod -Uri "$apiBase/health/ready" -TimeoutSec 15
    if ($health.status -ne "ready") { throw "PurchaseFlow API is not ready." }
}

if ($Restore) {
    if (-not (Test-Path -LiteralPath $scenarioPath)) {
        Write-Host "SKIP: no Odoo mismatch scenario needs restoration."
        return
    }
    Assert-Ready
    $scenario = Get-Content -LiteralPath $scenarioPath -Raw | ConvertFrom-Json
    $procurementSession = New-DemoSession -Role "procurement" -Email "procurement@demo.local"
    Invoke-OdooMismatchTool -Mode "restore" -ProcurementId $scenario.id
    $restored = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($scenario.id)/reconcile" `
        -Method Post -WebSession $procurementSession -TimeoutSec 30
    if ($restored.status -ne "erp_verified" -or $restored.erp.state -ne "verified" -or
        $restored.erp.observation.disposition -ne "VERIFIED" -or
        $restored.erp.remote_order_id -ne $scenario.remote_order_id -or
        $restored.erp.remote_order_name -ne $scenario.remote_order_name) {
        throw "The restored real Odoo draft did not independently return to the same verified order."
    }
    if ($restored.erp.observation.differences -and
        @($restored.erp.observation.differences.PSObject.Properties).Count -gt 0) {
        throw "Differences remain after restoring the real Odoo draft."
    }
    Remove-Item -LiteralPath $scenarioPath
    Write-Host "PASS: Odoo draft restored and independently reverified as $($scenario.remote_order_name)."
    return
}

Assert-Ready
$requesterSession = New-DemoSession -Role "requester" -Email "requester.ops@demo.local" -DepartmentCode "operations"
$requestBody = [ordered]@{
    department_code = "operations"
    supplier_ref = "PF-VENDOR-OFFICE"
    reason = $reason
    currency_code = "CNY"
    lines = @(@{ sku = "PF-OFFICE-SET"; quantity = 1; unit_price = "1200.00" })
} | ConvertTo-Json -Depth 6 -Compress
$request = Invoke-RestMethod -Uri "$apiBase/api/procurements" -Method Post `
    -WebSession $requesterSession -ContentType "application/json" `
    -Headers @{ "Idempotency-Key" = "mismatch-demo-$([guid]::NewGuid().ToString('N'))" } `
    -Body $requestBody -TimeoutSec 20
if ($request.status -ne "draft") { throw "The mismatch request did not start as a draft." }
$submitted = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($request.id)/submit" -Method Post `
    -WebSession $requesterSession -ContentType "application/json" `
    -Body (@{ expected_version = $request.version } | ConvertTo-Json -Compress) -TimeoutSec 20

$managerSession = New-DemoSession -Role "manager" -Email "manager.ops@demo.local" -DepartmentCode "operations"
$null = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($request.id)/decision" -Method Post `
    -WebSession $managerSession -ContentType "application/json" `
    -Headers @{ "Idempotency-Key" = "mismatch-approval-$([guid]::NewGuid().ToString('N'))" } `
    -Body (@{ decision = "approve"; expected_version = $submitted.version; reason = "Approved for controlled Odoo mismatch validation." } | ConvertTo-Json -Compress) `
    -TimeoutSec 20

$procurementSession = New-DemoSession -Role "procurement" -Email "procurement@demo.local"
$deadline = (Get-Date).AddSeconds(120)
$verified = $null
do {
    $verified = Get-Request -Id $request.id -Session $procurementSession
    if ($verified.status -in @("erp_failed", "erp_unknown", "erp_mismatch")) {
        throw "The clean Odoo draft did not verify before controlled tampering: $($verified.status)."
    }
    if ($verified.status -ne "erp_verified") { Start-Sleep -Seconds 2 }
} while ($verified.status -ne "erp_verified" -and (Get-Date) -lt $deadline)
if ($verified.status -ne "erp_verified" -or -not $verified.erp.remote_order_id) {
    throw "The approved request did not produce a verified real Odoo draft within 120 seconds."
}

$null = New-Item -ItemType Directory -Force -Path $local
$scenario = [ordered]@{
    id = $verified.id
    request_number = $verified.request_number
    external_intent_id = $verified.erp.external_intent_id
    remote_order_id = $verified.erp.remote_order_id
    remote_order_name = $verified.erp.remote_order_name
}
Set-Content -LiteralPath $scenarioPath -Encoding utf8NoBOM -Value ($scenario | ConvertTo-Json -Compress)

Invoke-OdooMismatchTool -Mode "tamper" -ProcurementId $verified.id
$mismatch = Invoke-RestMethod -Uri "$apiBase/api/procurements/$($verified.id)/reconcile" `
    -Method Post -WebSession $procurementSession -TimeoutSec 30
if ($mismatch.status -ne "erp_mismatch" -or $mismatch.erp.state -ne "mismatch" -or
    $mismatch.erp.observation.disposition -ne "MISMATCH" -or
    -not $mismatch.erp.observation.differences.line_1 -or
    -not $mismatch.erp.observation.differences.amount_total) {
    throw "PurchaseFlow did not preserve the real Odoo line-price and total differences."
}
if ($mismatch.allowed_actions -contains "close") {
    throw "The procurement worklist incorrectly allowed a mismatched request to close."
}
$closeResponse = Invoke-WebRequest -Uri "$apiBase/api/procurements/$($verified.id)/close" -Method Post `
    -WebSession $procurementSession -ContentType "application/json" `
    -Body (@{ expected_version = $mismatch.version } | ConvertTo-Json -Compress) `
    -SkipHttpErrorCheck -TimeoutSec 15
if ([int]$closeResponse.StatusCode -ne 409) {
    throw "Closing an ERP mismatch returned HTTP $($closeResponse.StatusCode), expected 409."
}
$diffText = $mismatch.erp.observation.differences | ConvertTo-Json -Depth 10 -Compress
if (-not $diffText.Contains("1201")) {
    throw "The actual changed Odoo unit price was not included in the mismatch observation."
}
Write-Host "PASS: real Odoo draft $($verified.erp.remote_order_name) was changed; PurchaseFlow reported actual line and total differences and rejected closure (HTTP 409)."
