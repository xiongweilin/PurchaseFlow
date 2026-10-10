#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))
$urlPath = Join-Path $local "test-database-url"
$sqlPath = Join-Path $local "create-test-database.sql"

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

$null = New-Item -ItemType Directory -Force -Path $local
if (-not (Test-Path -LiteralPath $urlPath -PathType Leaf)) {
    $password = New-SecretToken
    Set-Content -LiteralPath $urlPath -Encoding ascii -NoNewline -Value "postgresql+psycopg://purchaseflow_test:$password@db:5432/purchaseflow_test"
}
$url = (Get-Content -LiteralPath $urlPath -Raw -Encoding ascii).Trim()
$match = [regex]::Match($url, '^postgresql\+psycopg://purchaseflow_test:([^@]+)@db:5432/purchaseflow_test$')
if (-not $match.Success) { throw "The local PostgreSQL test URL has an unexpected format." }
$password = $match.Groups[1].Value
$sqlLines = @(
    "DO __DOLLAR____DOLLAR__",
    "BEGIN",
    "    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'purchaseflow_test') THEN",
    "        CREATE ROLE purchaseflow_test LOGIN PASSWORD '__TEST_PASSWORD__';",
    "    END IF;",
    "END",
    "__DOLLAR____DOLLAR__;",
    "SELECT format('CREATE DATABASE %I OWNER %I', 'purchaseflow_test', 'purchaseflow_test')",
    "WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'purchaseflow_test') \gexec"
)
$sql = ($sqlLines -join [Environment]::NewLine).Replace("__DOLLAR__", '$').Replace("__TEST_PASSWORD__", $password)
Set-Content -LiteralPath $sqlPath -Encoding utf8 -Value $sql

Push-Location $root
try {
    Invoke-Compose -Arguments @("up", "-d", "db")
    $deadline = (Get-Date).AddMinutes(3)
    do {
        $id = (Invoke-ComposeQuery -Arguments @("ps", "-q", "db")).Trim()
        $healthy = $false
        if ($id) { $healthy = ((& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim() -eq "healthy") }
        if (-not $healthy) { Start-Sleep -Seconds 2 }
    } while (-not $healthy -and (Get-Date) -lt $deadline)
    if (-not $healthy) { throw "PurchaseFlow PostgreSQL did not become healthy." }

    Invoke-Compose -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres",
        "-v", "ON_ERROR_STOP=1", "-f", "/run/purchaseflow-local/create-test-database.sql"
    )
    $owner = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='purchaseflow_test'"
    )
    $privileges = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT rolsuper::text || ':' || rolcreatedb::text FROM pg_roles WHERE rolname='purchaseflow_test'"
    )
    if ($owner -ne "purchaseflow_test" -or $privileges -ne "false:false") {
        throw "The isolated PostgreSQL integration-test role/database is misconfigured."
    }
    Write-Host "Created and verified an isolated, least-privilege PostgreSQL integration-test database."
}
finally {
    Pop-Location
}
