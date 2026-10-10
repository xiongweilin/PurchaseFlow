#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
Push-Location $root
try {
    & docker compose @compose stop --timeout 45
    if ($LASTEXITCODE -ne 0) { throw "PurchaseFlow stack did not stop cleanly." }
    Write-Host "PurchaseFlow demo services are stopped. Persistent database, Odoo, n8n, and Mailpit volumes were retained."
    Write-Host "Restart with scripts/start-demo.ps1."
}
finally {
    Pop-Location
}
