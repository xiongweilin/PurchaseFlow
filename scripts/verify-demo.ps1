#Requires -Version 7.0
param([switch]$ExerciseN8nWorkflows)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$base = "http://127.0.0.1"

function Assert-Status {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][int]$Actual, [Parameter(Mandatory)][int]$Expected)
    if ($Actual -ne $Expected) { throw "$Name returned HTTP $Actual; expected $Expected." }
}
function Get-HttpStatus {
    param([Parameter(Mandatory)][string]$Uri)
    (Get-HttpResponse -Uri $Uri).StatusCode
}
function Get-HttpResponse {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [string]$Method = "GET",
        [hashtable]$Headers,
        [string]$Body,
        [string]$ContentType
    )
    $request = @{ Uri = $Uri; Method = $Method; TimeoutSec = 30; SkipHttpErrorCheck = $true }
    if ($Headers) { $request.Headers = $Headers }
    if ($PSBoundParameters.ContainsKey("Body")) { $request.Body = $Body }
    if ($ContentType) { $request.ContentType = $ContentType }
    Invoke-WebRequest @request
}

$apiHealth = Invoke-RestMethod -Uri "$($base):18000/health/ready" -TimeoutSec 15
if ($apiHealth.status -ne "ready") { throw "PurchaseFlow readiness check did not return ready." }

$ui = Invoke-WebRequest -Uri "$($base):18081/" -TimeoutSec 15
Assert-Status -Name "Frontend" -Actual $ui.StatusCode -Expected 200

$odooLogin = Invoke-WebRequest -Uri "$($base):18069/web/login" -TimeoutSec 15
Assert-Status -Name "Odoo login" -Actual $odooLogin.StatusCode -Expected 200

$n8nHealth = Invoke-WebRequest -Uri "$($base):18082/healthz" -TimeoutSec 15
Assert-Status -Name "n8n" -Actual $n8nHealth.StatusCode -Expected 200

$mailpitHealth = Invoke-WebRequest -Uri "$($base):18025/api/v1/messages" -TimeoutSec 15
Assert-Status -Name "Mailpit API" -Actual $mailpitHealth.StatusCode -Expected 200

$unauthenticated = Get-HttpStatus -Uri "$($base):18000/api/me"
Assert-Status -Name "Unauthenticated app session" -Actual $unauthenticated -Expected 401

$identities = Invoke-RestMethod -Uri "$($base):18000/api/demo/identities" -TimeoutSec 15
if (@($identities).Count -lt 8) { throw "Expected all seeded role-specific demo identities." }

$tokenPath = Join-Path $root ".local\automation-token.txt"
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) { throw "n8n service credential file is missing." }
$token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding ascii).Trim()
$summary = Invoke-RestMethod -Uri "$($base):18000/api/integrations/summary" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 15
if ($null -eq $summary.counts -or $null -eq $summary.attention) { throw "The scoped n8n integration summary did not return its expected shape." }

$workflowCount = (& docker compose @compose exec -T db psql -U purchaseflow_admin -d purchaseflow_n8n -Atqc "SELECT count(*) FROM workflow_entity WHERE active IS TRUE AND name IN ('PurchaseFlow · Authenticated procurement intake','PurchaseFlow · Daily approval and ERP digest')").Trim()
if ($LASTEXITCODE -ne 0 -or $workflowCount -ne "2") { throw "Expected both versioned n8n workflows to be active; found $workflowCount." }
$intakePath = (& docker compose @compose exec -T db psql -U purchaseflow_admin -d purchaseflow_n8n -Atqc "SELECT ""webhookPath"" FROM webhook_entity WHERE ""workflowId""='9d047287-d2c9-4ee6-9669-1e488d3ef801' LIMIT 1").Trim()
$summaryPath = (& docker compose @compose exec -T db psql -U purchaseflow_admin -d purchaseflow_n8n -Atqc "SELECT ""webhookPath"" FROM webhook_entity WHERE ""workflowId""='4ca07f03-9e91-443c-9b84-4af611df9a62' LIMIT 1").Trim()
if ($LASTEXITCODE -ne 0 -or $intakePath -ne "purchaseflow/intake" -or $summaryPath -ne "purchaseflow/summary") {
    throw "The authenticated n8n intake or summary webhook is not registered at its documented path."
}

if ($ExerciseN8nWorkflows) {
    $eventId = "verify-" + [guid]::NewGuid().ToString("N")
    $payload = [ordered]@{
        external_event_id = $eventId
        requester_email = "requester.ops@demo.local"
        department_code = "operations"
        supplier_ref = "PF-VENDOR-OFFICE"
        reason = "Local n8n integration smoke test."
        lines = @(@{ sku = "PF-OFFICE-SET"; quantity = 1; unit_price = 1200 })
    } | ConvertTo-Json -Depth 8
    $headers = @{ Authorization = "Bearer $token" }
    $intakeUrl = "$($base):18082/webhook/purchaseflow/intake"
    $unauthorized = Get-HttpResponse -Uri $intakeUrl -Method Post -ContentType "application/json" -Body $payload
    Assert-Status -Name "Unauthenticated n8n intake" -Actual $unauthorized.StatusCode -Expected 403

    $invalidPayload = [ordered]@{
        external_event_id = "verify-invalid-" + [guid]::NewGuid().ToString("N")
        requester_email = "requester.ops@demo.local"
        department_code = "operations"
        supplier_ref = "PF-NOT-A-MAPPED-SUPPLIER"
        reason = "Reject an unmapped supplier without creating a request."
        lines = @(@{ sku = "PF-OFFICE-SET"; quantity = 1; unit_price = 1200 })
    } | ConvertTo-Json -Depth 8
    $invalid = Get-HttpResponse -Uri $intakeUrl -Method Post -Headers $headers -ContentType "application/json" -Body $invalidPayload
    if ($invalid.StatusCode -ne 422) { throw "The n8n intake returned HTTP $($invalid.StatusCode) for an invalid supplier mapping; expected the API's 422 validation response." }

    $first = Invoke-RestMethod -Uri $intakeUrl -Method Post -Headers $headers -ContentType "application/json" -Body $payload -TimeoutSec 30
    $replay = Invoke-RestMethod -Uri $intakeUrl -Method Post -Headers $headers -ContentType "application/json" -Body $payload -TimeoutSec 30
    if ($first.id -ne $replay.id -or $first.request_number -ne $replay.request_number -or $first.status -ne "pending_manager") {
        throw "The n8n intake workflow failed its idempotency or requester-scoped submit check."
    }
    $conflictingPayload = [ordered]@{
        external_event_id = $eventId
        requester_email = "requester.ops@demo.local"
        department_code = "operations"
        supplier_ref = "PF-VENDOR-OFFICE"
        reason = "Reusing an event identifier with changed procurement content must conflict."
        lines = @(@{ sku = "PF-OFFICE-SET"; quantity = 1; unit_price = 1201 })
    } | ConvertTo-Json -Depth 8
    $conflict = Get-HttpResponse -Uri $intakeUrl -Method Post -Headers $headers -ContentType "application/json" -Body $conflictingPayload
    if ($conflict.StatusCode -ne 409) { throw "The n8n intake returned HTTP $($conflict.StatusCode) for changed idempotent content; expected the API's 409." }
    Write-Host "PASS: n8n returns 403 for missing authorization, 422 for invalid supplier input, and 409 for conflicting replay; identical replay returns the same request."

    $before = Invoke-RestMethod -Uri "$($base):18025/api/v1/messages" -TimeoutSec 15
    $previousCount = @($before.messages).Count
    $summaryUrl = "$($base):18082/webhook/purchaseflow/summary"
    $null = Invoke-RestMethod -Uri $summaryUrl -Method Post -Headers $headers -ContentType "application/json" -Body "{}" -TimeoutSec 30
    $deadline = (Get-Date).AddSeconds(30)
    $digestFound = $false
    do {
        $mail = Invoke-RestMethod -Uri "$($base):18025/api/v1/messages" -TimeoutSec 10
        $messages = @($mail.messages)
        $digestFound = $messages.Count -gt $previousCount -and @($messages | Where-Object { $_.Subject -eq "PurchaseFlow · Daily approval and ERP digest" }).Count -gt 0
        if (-not $digestFound) { Start-Sleep -Seconds 2 }
    } while (-not $digestFound -and (Get-Date) -lt $deadline)
    if (-not $digestFound) { throw "The n8n digest workflow did not deliver to local Mailpit." }
    Write-Host "PASS: n8n intake idempotency and Mailpit digest ($($first.request_number))."
}

Write-Host "PASS: API, frontend, Odoo, n8n, Mailpit, role identities, scoped automation token, active n8n workflows, and webhooks."
