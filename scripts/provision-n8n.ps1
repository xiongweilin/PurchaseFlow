#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$importDir = Join-Path $local "n8n-import"
$compose = @("-p", "purchaseflow-demo", "-f", (Join-Path $root "docker-compose.yml"))

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

$tokenPath = Join-Path $local "automation-token.txt"
if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) { throw "The PurchaseFlow service-token file is missing." }
$serviceToken = (Get-Content -LiteralPath $tokenPath -Raw -Encoding ascii).Trim()
if ($serviceToken.Length -lt 24) { throw "The PurchaseFlow service token is unexpectedly short." }

$ownerSql = 'SELECT id FROM "user" WHERE email = ''automation-admin@demo.local'' LIMIT 1'
$ownerId = Invoke-ComposeText -Arguments @(
    "exec", "-T", "db", "psql", "-U", "purchaseflow_admin", "-d", "purchaseflow_n8n", "-Atqc", $ownerSql
)
if ($ownerId -notmatch '^[0-9a-fA-F-]{36}$') { throw "The pre-provisioned n8n owner was not found." }

$credentials = @(
    [ordered]@{
        id = "7af2c27d-7f05-4de0-9a28-91e77018951e"
        name = "PurchaseFlow service API"
        type = "httpHeaderAuth"
        data = [ordered]@{ name = "Authorization"; value = "Bearer $serviceToken" }
    },
    [ordered]@{
        id = "b88e23c1-b1e8-46a5-9572-412cd47bf33f"
        name = "PurchaseFlow Mailpit SMTP"
        type = "smtp"
        data = [ordered]@{
            user = ""
            password = ""
            host = "mailpit"
            port = 1025
            secure = $false
            disableStartTls = $true
            hostName = "purchaseflow-n8n"
        }
    }
)
$json = ConvertTo-Json -InputObject $credentials -Depth 12
$credentialPath = Join-Path $importDir "credentials.json"
[IO.File]::WriteAllText($credentialPath, $json, [Text.UTF8Encoding]::new($false))

Push-Location $root
try {
    Invoke-Compose -Arguments @(
        "exec", "-T", "n8n", "n8n", "import:credentials",
        "--input=/run/purchaseflow-import/credentials.json", "--userId=$ownerId"
    )
    foreach ($workflow in @(
        @{ file = "purchaseflow-intake.json"; id = "9d047287-d2c9-4ee6-9669-1e488d3ef801" },
        @{ file = "procurement-daily-summary.json"; id = "4ca07f03-9e91-443c-9b84-4af611df9a62" }
    )) {
        Invoke-Compose -Arguments @(
            "exec", "-T", "n8n", "n8n", "import:workflow",
            "--input=/run/purchaseflow-workflows/$($workflow.file)", "--userId=$ownerId"
        )
        Invoke-Compose -Arguments @("exec", "-T", "n8n", "n8n", "publish:workflow", "--id=$($workflow.id)")
    }
    Invoke-Compose -Arguments @("up", "-d", "--force-recreate", "n8n")
}
finally {
    if (Test-Path -LiteralPath $credentialPath -PathType Leaf) {
        Remove-Item -LiteralPath $credentialPath -Force
    }
    Pop-Location
}

$deadline = (Get-Date).AddMinutes(3)
$healthy = $false
do {
    $id = (Invoke-ComposeText -Arguments @("ps", "-q", "n8n")).Trim()
    if ($id) { $healthy = ((& docker inspect --format "{{.State.Health.Status}}" $id 2>$null).Trim() -eq "healthy") }
    if (-not $healthy) { Start-Sleep -Seconds 3 }
} while (-not $healthy -and (Get-Date) -lt $deadline)
if (-not $healthy) { throw "n8n did not become healthy after workflow import." }

Write-Host "n8n credentials were imported into encrypted storage; intake and daily summary workflows are published."
