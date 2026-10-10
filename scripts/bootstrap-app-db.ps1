#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$appEnv = Join-Path $local "app.env"
$appUrl = Join-Path $local "app-database-url"
$sqlPath = Join-Path $local "create-app-database.sql"

function New-SecretToken {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}

function Invoke-ComposeQuery {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose @compose @Arguments
    $nativeExitCode = $LASTEXITCODE
    if ($nativeExitCode -ne 0) { throw "docker compose query failed with exit code $nativeExitCode." }
    (@($output) -join "").Trim()
}

function Wait-Db {
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        $id = (Invoke-ComposeQuery -Arguments @("ps", "-q", "db")).Trim()
        if ($id) {
            $health = (& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim()
            if ($health -eq "healthy") { return }
        }
        Start-Sleep -Seconds 2
    }
    throw "PurchaseFlow PostgreSQL did not become healthy."
}

$null = New-Item -ItemType Directory -Force -Path $local
$hasEnv = Test-Path -LiteralPath $appEnv -PathType Leaf
if ($hasEnv -and (Get-Item -LiteralPath $appEnv).Length -eq 0) { $hasEnv = $false }
$hasUrl = Test-Path -LiteralPath $appUrl -PathType Leaf
if (-not $hasEnv -and -not $hasUrl) {
    $password = New-SecretToken
    Set-Content -LiteralPath $appUrl -Encoding ascii -NoNewline -Value "postgresql+psycopg://purchaseflow_app:$password@db:5432/purchaseflow_app"
    $envLines = @(
        "DATABASE_URL_FILE=/run/purchaseflow-secrets/app-database-url",
        "ODOO_BASE_URL=http://odoo:8069",
        "ODOO_DATABASE=purchaseflow_odoo",
        "ODOO_API_KEY_FILE=/run/purchaseflow-secrets/odoo-api-key",
        "ODOO_SEED_MANIFEST_FILE=/run/purchaseflow-secrets/odoo-seed-manifest.json",
        "PURCHASEFLOW_AUTOMATION_TOKEN_FILE=/run/purchaseflow-secrets/automation-token.txt",
        "PURCHASEFLOW_DEMO_MODE=true",
        "PURCHASEFLOW_ENVIRONMENT=demo",
        "PURCHASEFLOW_SESSION_TTL_SECONDS=28800"
    )
    Set-Content -LiteralPath $appEnv -Encoding utf8 -Value $envLines
} elseif (-not $hasEnv -or -not $hasUrl) {
    throw "PurchaseFlow app database credential files are incomplete; refusing to create a mismatched role."
}

$url = (Get-Content -LiteralPath $appUrl -Raw -Encoding ascii).Trim()
$match = [regex]::Match($url, '^postgresql\+psycopg://purchaseflow_app:([^@]+)@db:5432/purchaseflow_app$')
if (-not $match.Success) { throw "The local PurchaseFlow app database URL has an unexpected format." }
$password = $match.Groups[1].Value
$sqlLines = @(
    "DO __DOLLAR____DOLLAR__",
    "BEGIN",
    "    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'purchaseflow_app') THEN",
    "        CREATE ROLE purchaseflow_app LOGIN PASSWORD '__APP_PASSWORD__';",
    "    END IF;",
    "END",
    "__DOLLAR____DOLLAR__;",
    "SELECT format('CREATE DATABASE %I OWNER %I', 'purchaseflow_app', 'purchaseflow_app')",
    "WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'purchaseflow_app') \gexec"
)
$sql = ($sqlLines -join [Environment]::NewLine).Replace("__DOLLAR__", '$').Replace("__APP_PASSWORD__", $password)
Set-Content -LiteralPath $sqlPath -Encoding utf8 -Value $sql

Push-Location $root
try {
    Invoke-Compose -Arguments @("up", "-d", "db")
    Wait-Db
    Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-f", "/run/purchaseflow-local/create-app-database.sql"
    )
    $owner = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='purchaseflow_app'"
    )
    if ($owner -ne "purchaseflow_app") { throw "The app database owner is not the restricted application role." }
    $privileges = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT rolsuper::text || ':' || rolcreatedb::text FROM pg_roles WHERE rolname='purchaseflow_app'"
    )
    if ($privileges -ne "false:false") { throw "The application database role has elevated PostgreSQL privileges." }
    Write-Host "Created and verified the separate, non-superuser PurchaseFlow application database."
}
finally {
    Pop-Location
}
