#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$confirmationPhrase = "RESET PURCHASEFLOW DEMO DATA"

Write-Host "This removes only the purchaseflow-demo containers, its network, and these named volumes:"
Write-Host "  purchaseflow-demo-odoo-postgres"
Write-Host "  purchaseflow-demo-odoo-filestore"
Write-Host "  purchaseflow-demo-n8n-data"
Write-Host "  purchaseflow-demo-mailpit-data"
Write-Host "The ignored .local configuration and all other Compose projects are retained."
$confirmation = Read-Host "Type '$confirmationPhrase' to continue"
if ($confirmation -cne $confirmationPhrase) {
    throw "Reset cancelled; no PurchaseFlow resources were removed."
}

Push-Location $root
try {
    & docker compose @compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "The PurchaseFlow Compose configuration could not be validated." }
    & docker compose @compose down --volumes --remove-orphans --timeout 45
    if ($LASTEXITCODE -ne 0) { throw "The PurchaseFlow project did not reset cleanly." }
    Write-Host "PurchaseFlow demo data volumes were removed. Run scripts/start-demo.ps1 to initialize again."
}
finally {
    Pop-Location
}
