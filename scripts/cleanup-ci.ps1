#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:GITHUB_ACTIONS -cne "true") {
    throw "This destructive cleanup is restricted to an ephemeral GitHub Actions runner."
}

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
Push-Location $root
try {
    & docker compose @compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw "The PurchaseFlow Compose configuration could not be validated." }
    & docker compose @compose down --volumes --remove-orphans --timeout 45
    if ($LASTEXITCODE -ne 0) { throw "The ephemeral PurchaseFlow CI project did not clean up cleanly." }
    Write-Host "Removed only this GitHub Actions job's purchaseflow-demo containers, network, and named volumes."
}
finally {
    Pop-Location
}
