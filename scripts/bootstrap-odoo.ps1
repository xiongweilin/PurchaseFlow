#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$localRoot = Join-Path $repositoryRoot ".local"
$projectName = "purchaseflow-demo"
$composeFile = Join-Path $repositoryRoot "docker-compose.yml"
$composeArgs = @("-p", $projectName, "-f", $composeFile)
$postgresEnv = Join-Path $localRoot "postgres.env"
$odooEnv = Join-Path $localRoot "odoo.env"
$odooConfig = Join-Path $localRoot "odoo.conf"
$requiredLocalFiles = @($postgresEnv, $odooEnv, $odooConfig)

function New-SecretToken {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-EnvValue {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Name)
    $prefix = $Name + "="
    $line = Get-Content -LiteralPath $Path | Where-Object { $_.StartsWith($prefix) } | Select-Object -First 1
    if (-not $line) { throw "Required local setting $Name is missing from $([IO.Path]::GetFileName($Path))." }
    return $line.Substring($prefix.Length)
}

function Invoke-Compose {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & docker compose @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments[0]) failed with exit code $LASTEXITCODE." }
}

function Invoke-ComposeQuery {
    param([Parameter(Mandatory)][string[]]$Arguments)
    $output = & docker compose @composeArgs @Arguments
    $nativeExitCode = $LASTEXITCODE
    if ($nativeExitCode -ne 0) { throw "docker compose query failed with exit code $nativeExitCode." }
    return (@($output) -join "").Trim()
}

function Wait-ServiceHealthy {
    param([Parameter(Mandatory)][string]$Service, [int]$TimeoutMinutes = 5)
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $containerId = (Invoke-ComposeQuery -Arguments @("ps", "-q", $Service)).Trim()
    while ((Get-Date) -lt $deadline) {
        if ($containerId) {
            $health = (& docker inspect --format "{{.State.Health.Status}}" $containerId 2>$null).Trim()
            if ($health -eq "healthy") { return }
        }
        Start-Sleep -Seconds 3
        $containerId = (Invoke-ComposeQuery -Arguments @("ps", "-q", $Service)).Trim()
    }
    throw "PurchaseFlow $Service did not become healthy within $TimeoutMinutes minutes."
}

$existingFiles = @($requiredLocalFiles | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
if ($existingFiles.Count -eq 0) {
    $ownedVolumes = @(docker volume ls --format "{{.Name}}" | Where-Object {
        $_ -in @("purchaseflow-demo-odoo-postgres", "purchaseflow-demo-odoo-filestore")
    })
    $ownedContainers = @(docker ps -a --format "{{.Names}}" | Where-Object { $_ -like "purchaseflow-demo-*" })
    if ($ownedVolumes.Count -gt 0 -or $ownedContainers.Count -gt 0) {
        throw "PurchaseFlow data exists but local credentials are absent; refusing to regenerate credentials."
    }

    $null = New-Item -ItemType Directory -Force -Path $localRoot
    $postgresPassword = New-SecretToken
    $odooPassword = New-SecretToken
    $adminPassword = New-SecretToken
    $masterPassword = New-SecretToken
    Set-Content -LiteralPath $postgresEnv -Encoding utf8 -Value @"
POSTGRES_USER=purchaseflow_admin
POSTGRES_PASSWORD=$postgresPassword
POSTGRES_DB=postgres
"@
    Set-Content -LiteralPath $odooEnv -Encoding utf8 -Value @"
HOST=db
PORT=5432
USER=purchaseflow_odoo
PASSWORD=$odooPassword
ODOO_DATABASE=purchaseflow_odoo
ODOO_ADMIN_PASSWORD=$adminPassword
"@
    Set-Content -LiteralPath $odooConfig -Encoding utf8 -Value @"
[options]
admin_passwd = $masterPassword
db_host = db
db_port = 5432
db_user = purchaseflow_odoo
db_password = $odooPassword
dbfilter = ^purchaseflow_odoo$
list_db = False
data_dir = /var/lib/odoo
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons
http_interface = 0.0.0.0
"@
    Write-Host "Created ignored credentials for this isolated PurchaseFlow database."
}
elseif ($existingFiles.Count -ne $requiredLocalFiles.Count) {
    throw "PurchaseFlow local credential files are incomplete; refusing automatic credential rotation."
}

$odooPassword = Get-EnvValue -Path $odooEnv -Name "PASSWORD"
$adminPassword = Get-EnvValue -Path $odooEnv -Name "ODOO_ADMIN_PASSWORD"
$sqlPath = Join-Path $localRoot "create-odoo-database.sql"
$sql = @"
DO __DOLLAR____DOLLAR__
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'purchaseflow_odoo') THEN
        CREATE ROLE purchaseflow_odoo LOGIN PASSWORD '$odooPassword';
    END IF;
END
__DOLLAR____DOLLAR__;
SELECT format('CREATE DATABASE %I OWNER %I', 'purchaseflow_odoo', 'purchaseflow_odoo')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'purchaseflow_odoo') \gexec
"@
Set-Content -LiteralPath $sqlPath -Encoding utf8 -Value $sql
$sql = $sql.Replace("__DOLLAR__", '$')

Push-Location $repositoryRoot
try {
    Invoke-Compose -Arguments @("up", "-d", "db")
    Wait-ServiceHealthy -Service "db"

    $databaseExists = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres", "-Atqc",
        "SELECT 1 FROM pg_database WHERE datname='purchaseflow_odoo'"
    )
    if ($databaseExists -ne "1") {
        Invoke-Compose -Arguments @(
            "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-f", "/run/purchaseflow-local/create-odoo-database.sql"
        )
    }

    $baseTableExists = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "purchaseflow_odoo",
        "-Atqc", "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module'"
    )
    if ($baseTableExists -ne "1") {
        Invoke-Compose -Arguments @(
            "run", "--rm", "odoo", "odoo", "--database", "purchaseflow_odoo",
            "--init", "base", "--without-demo", "--stop-after-init"
        )
    }

    Invoke-Compose -Arguments @(
        "run", "--rm", "odoo", "odoo", "--database", "purchaseflow_odoo",
        "--init", "purchase,purchaseflow_link", "--without-demo", "--stop-after-init"
    )

    $moduleState = Invoke-ComposeQuery -Arguments @(
        "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "purchaseflow_odoo",
        "-Atqc", "SELECT name || ':' || state FROM ir_module_module WHERE name IN ('base','account','purchase','purchaseflow_link') ORDER BY name"
    )
    foreach ($module in @("base:installed", "account:installed", "purchase:installed", "purchaseflow_link:installed")) {
        if ($moduleState -notmatch [regex]::Escape($module)) { throw "Expected Odoo module state is missing: $module." }
    }

    Invoke-Compose -Arguments @("up", "-d", "odoo")
    Wait-ServiceHealthy -Service "odoo"

    $login = Invoke-WebRequest -Uri "http://127.0.0.1:18069/web/login" -TimeoutSec 10
    $unauthenticated = Invoke-WebRequest -Uri "http://127.0.0.1:18069/json/2/res.partner/search_read" -Method Post -ContentType "application/json" -Body '{"domain":[],"fields":["id"],"limit":1}' -SkipHttpErrorCheck -TimeoutSec 10
    if ($login.StatusCode -ne 200 -or $unauthenticated.StatusCode -ne 401) {
        throw "Odoo HTTP readiness/authentication check failed (login $($login.StatusCode), JSON-2 $($unauthenticated.StatusCode))."
    }

    $seedPath = Join-Path $repositoryRoot "odoo/scripts/bootstrap_data.py"
    Get-Content -LiteralPath $seedPath -Raw -Encoding utf8 |
        docker compose @composeArgs run --rm -T odoo odoo shell --database purchaseflow_odoo --no-http
    if ($LASTEXITCODE -ne 0) { throw "Odoo seed failed with exit code $LASTEXITCODE." }

    Invoke-Compose -Arguments @("exec", "-T", "odoo", "python3", "/opt/purchaseflow/odoo-scripts/acceptance_json2.py")
    Write-Host "Odoo 19 Community, JSON-2, CNY master data, purchase access, draft read-back, and duplicate-intent guard verified."
}
finally {
    Pop-Location
}
