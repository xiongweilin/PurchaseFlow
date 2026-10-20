#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}
function Wait-ServiceHealthy {
    param([Parameter(Mandatory)][string]$Service, [int]$TimeoutMinutes = 5)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    do {
        $id = (& docker compose @compose ps -q $Service).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Unable to inspect service $Service." }
        if ($id) {
            $health = (& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim()
            if ($health -eq "healthy") { return }
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    & docker compose @compose logs --tail 60 $Service
    throw "PurchaseFlow $Service did not become healthy within $TimeoutMinutes minutes."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "Docker Desktop CLI is required." }
& docker info --format "{{.ServerVersion}}" *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop is not running. Start Docker Desktop and retry." }
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) { throw "Docker Compose v2 is required." }

Push-Location $root
try {
    Write-Host "[1/8] Preparing the Odoo 19 demo database and guarded service credentials..."
    & (Join-Path $PSScriptRoot "bootstrap-odoo.ps1")

    Write-Host "[2/8] Creating the separate PurchaseFlow database role..."
    & (Join-Path $PSScriptRoot "bootstrap-app-db.ps1")

    Write-Host "[3/8] Preparing the isolated n8n database and first local owner..."
    & (Join-Path $PSScriptRoot "bootstrap-n8n-owner.ps1")

    Write-Host "[4/8] Building the API and TypeScript web application..."
    Invoke-Compose -Arguments @("build", "api", "frontend")

    Write-Host "[5/8] Verifying real Odoo JSON-2 draft and idempotency behavior..."
    Invoke-Compose -Arguments @(
        "run", "--rm", "-T", "--no-deps", "api", "python3",
        "/opt/purchaseflow/odoo-scripts/acceptance_json2.py"
    )

    Write-Host "[6/8] Applying Alembic migrations and seeding idempotent demo data..."
    $bootstrapUserArgs = @()
    if ($IsLinux -or $IsMacOS) {
        # Seed 会把 mode-0600 的 automation token 写入 bind mount 的 .local 目录。
        # 匹配宿主 UID/GID，让宿主 provisioner 可读，同时不削弱文件权限。
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
    Invoke-Compose -Arguments ($bootstrapBaseArgs + @("alembic", "upgrade", "head"))
    Invoke-Compose -Arguments $bootstrapBaseArgs

    Write-Host "[7/8] Starting the API and remaining services..."
    Invoke-Compose -Arguments @("up", "-d", "api")
    Wait-ServiceHealthy -Service "api"
    Invoke-Compose -Arguments @("up", "-d", "worker", "frontend", "mailpit", "n8n")
    foreach ($service in @("frontend", "mailpit", "n8n")) { Wait-ServiceHealthy -Service $service }
    $workerId = (& docker compose @compose ps -q worker).Trim()
    if (-not $workerId -or (& docker inspect --format "{{.State.Status}}" $workerId).Trim() -ne "running") {
        throw "The PurchaseFlow outbox worker is not running."
    }

    Write-Host "[8/8] Importing encrypted n8n credentials/workflows and running local acceptance checks..."
    & (Join-Path $PSScriptRoot "provision-n8n.ps1")
    & (Join-Path $PSScriptRoot "verify-demo.ps1")

    Write-Host ""
    Write-Host "PurchaseFlow demo is ready:"
    Write-Host "  PurchaseFlow:  http://127.0.0.1:18081"
    Write-Host "  API docs:      http://127.0.0.1:18000/docs"
    Write-Host "  Odoo 19:       http://127.0.0.1:18069"
    Write-Host "  n8n:           http://127.0.0.1:18082"
    Write-Host "  Mailpit:       http://127.0.0.1:18025"
    Write-Host "  n8n owner:     automation-admin@demo.local"
    Write-Host "  n8n password:  read the ignored local file .local/n8n-owner-password"
    Write-Host "Use scripts/stop-demo.ps1 to stop the stack without deleting persistent data."
}
finally {
    Pop-Location
}
