#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
if (-not (Test-Path -LiteralPath (Join-Path $root ".local\app.env") -PathType Leaf)) {
    throw "PurchaseFlow is not initialized. Run scripts/start-demo.ps1 first."
}

Push-Location $root
try {
    & docker compose @compose --profile tools run --rm -T bootstrap alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "PurchaseFlow Alembic migrations failed." }
    & docker compose @compose --profile tools run --rm -T bootstrap
    if ($LASTEXITCODE -ne 0) { throw "The idempotent PurchaseFlow demo seed failed." }
    Write-Host "PurchaseFlow migrations and idempotent demo seed completed."
}
finally {
    Pop-Location
}
