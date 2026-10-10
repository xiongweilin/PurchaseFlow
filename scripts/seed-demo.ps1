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
    $bootstrapUserArgs = @()
    if ($IsLinux -or $IsMacOS) {
        $hostUid = (& id -u).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to read the host UID for the bootstrap container." }
        $hostGid = (& id -g).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to read the host GID for the bootstrap container." }
        if ($hostUid -notmatch '^\d+$' -or $hostGid -notmatch '^\d+$') {
            throw "The host UID/GID for the bootstrap container is invalid."
        }
        $bootstrapUserArgs = @("--user", "${hostUid}:${hostGid}")
    }
    $bootstrapBaseArgs = @("--profile", "tools", "run", "--rm", "-T") + $bootstrapUserArgs + @("bootstrap")
    & docker compose @compose @bootstrapBaseArgs alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "PurchaseFlow Alembic migrations failed." }
    & docker compose @compose @bootstrapBaseArgs
    if ($LASTEXITCODE -ne 0) { throw "The idempotent PurchaseFlow demo seed failed." }
    Write-Host "PurchaseFlow migrations and idempotent demo seed completed."
}
finally {
    Pop-Location
}
