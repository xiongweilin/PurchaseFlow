#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$envPath = Join-Path $local "n8n.env"
$sqlPath = Join-Path $local "create-n8n-database.sql"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))

function New-Token {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToHexString($bytes).ToLowerInvariant()
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed with exit code $LASTEXITCODE." }
}

function Invoke-ComposeText {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose @compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose query failed with exit code $LASTEXITCODE." }
    (@($output) -join "").Trim()
}

$null = New-Item -ItemType Directory -Force -Path $local, (Join-Path $local "n8n-import"), (Join-Path $root "n8n\workflows")
$values = @{}
if (Test-Path -LiteralPath $envPath -PathType Leaf) {
    foreach ($line in Get-Content -LiteralPath $envPath -Encoding ascii) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
    }
}
if (-not $values.ContainsKey("DB_POSTGRESDB_PASSWORD")) { $values["DB_POSTGRESDB_PASSWORD"] = New-Token }
if (-not $values.ContainsKey("N8N_ENCRYPTION_KEY")) { $values["N8N_ENCRYPTION_KEY"] = New-Token }
$managedKeys = @("DB_TYPE", "DB_POSTGRESDB_HOST", "DB_POSTGRESDB_PORT", "DB_POSTGRESDB_DATABASE", "DB_POSTGRESDB_USER", "DB_POSTGRESDB_PASSWORD", "N8N_ENCRYPTION_KEY")
$envLines = @(
    "DB_TYPE=postgresdb",
    "DB_POSTGRESDB_HOST=db",
    "DB_POSTGRESDB_PORT=5432",
    "DB_POSTGRESDB_DATABASE=purchaseflow_n8n",
    "DB_POSTGRESDB_USER=purchaseflow_n8n",
    "DB_POSTGRESDB_PASSWORD=$($values["DB_POSTGRESDB_PASSWORD"])",
    "N8N_ENCRYPTION_KEY=$($values["N8N_ENCRYPTION_KEY"])"
)
foreach ($key in ($values.Keys | Sort-Object)) {
    if ($key -notin $managedKeys) { $envLines += "$key=$($values[$key])" }
}
Set-Content -LiteralPath $envPath -Encoding ascii -Value $envLines

$pw = $values["DB_POSTGRESDB_PASSWORD"]
$sql = @"
DO __DOLLAR__role__DOLLAR__
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'purchaseflow_n8n') THEN
        EXECUTE format('CREATE ROLE purchaseflow_n8n LOGIN PASSWORD %L', '$pw');
    ELSE
        EXECUTE format('ALTER ROLE purchaseflow_n8n WITH LOGIN PASSWORD %L', '$pw');
    END IF;
END
__DOLLAR__role__DOLLAR__;
SELECT format('CREATE DATABASE %I OWNER %I', 'purchaseflow_n8n', 'purchaseflow_n8n')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'purchaseflow_n8n') \gexec
"@
$sql = $sql.Replace("__DOLLAR__", '$')
Set-Content -LiteralPath $sqlPath -Encoding utf8 -Value $sql

Push-Location $root
try {
    Invoke-Compose -Arguments @("up", "-d", "db")
    $deadline = (Get-Date).AddMinutes(3)
    $healthy = $false
    do {
        $id = (Invoke-ComposeText -Arguments @("ps", "-q", "db")).Trim()
        if ($id) { $healthy = ((& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim() -eq "healthy") }
        if (-not $healthy) { Start-Sleep -Seconds 2 }
    } while (-not $healthy -and (Get-Date) -lt $deadline)
    if (-not $healthy) { throw "PurchaseFlow PostgreSQL did not become healthy." }

    Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-f", "/run/purchaseflow-local/create-n8n-database.sql"
    )
    $owner = Invoke-ComposeText -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='purchaseflow_n8n'"
    )
    $privileges = Invoke-ComposeText -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT rolsuper::text || ':' || rolcreatedb::text || ':' || rolcreaterole::text FROM pg_roles WHERE rolname='purchaseflow_n8n'"
    )
    if ($owner -ne "purchaseflow_n8n" -or $privileges -ne "false:false:false") {
        throw "The isolated n8n database role is not least-privilege."
    }
    Write-Host "n8n has an isolated Postgres database and non-superuser role; secrets are stored in .local/n8n.env."
}
finally {
    Pop-Location
}
