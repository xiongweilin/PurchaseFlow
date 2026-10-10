#Requires -Version 7.0
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root ".local"
$envPath = Join-Path $local "n8n.env"
$passwordPath = Join-Path $local "n8n-owner-password"
$hashPath = Join-Path $local "n8n-owner-password-hash"
$n8nImage = "docker.n8n.io/n8nio/n8n:2.42.6@sha256:526daa38b68e923cc00c5280d18b4da5d489f115a73bdbf3b8e452b184197a9a"

function New-OwnerPassword {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_") + "A7"
}

& (Join-Path $PSScriptRoot "bootstrap-n8n-db.ps1")
if ($LASTEXITCODE -ne 0) { throw "n8n database bootstrap failed." }

if (-not (Test-Path -LiteralPath $passwordPath -PathType Leaf)) {
    Set-Content -LiteralPath $passwordPath -Encoding ascii -NoNewline -Value (New-OwnerPassword)
}
$password = (Get-Content -LiteralPath $passwordPath -Raw -Encoding ascii).Trim()
if ($password.Length -lt 16 -or $password -notmatch '[A-Z]' -or $password -notmatch '[0-9]') {
    throw "The local n8n owner password does not meet the configured password policy."
}

$nodeScript = "const bcrypt = require('/usr/local/lib/node_modules/n8n/node_modules/bcryptjs'); process.stdout.write(bcrypt.hashSync(process.argv[1], 12));"
$hash = (& docker run --rm --entrypoint node $n8nImage -e $nodeScript $password)
if ($LASTEXITCODE -ne 0 -or $hash -notmatch '^\$2[aby]\$12\$[./A-Za-z0-9]{53}$') {
    throw "Could not create the n8n owner bcrypt password hash."
}

$values = @{}
foreach ($line in Get-Content -LiteralPath $envPath -Encoding ascii) {
    if ($line -match '^([A-Z0-9_]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
}
$values["N8N_INSTANCE_OWNER_MANAGED_BY_ENV"] = "true"
$values["N8N_INSTANCE_OWNER_EMAIL"] = "automation-admin@demo.local"
$values["N8N_INSTANCE_OWNER_FIRST_NAME"] = "PurchaseFlow"
$values["N8N_INSTANCE_OWNER_LAST_NAME"] = "Automation"
$values.Remove("N8N_INSTANCE_OWNER_PASSWORD_HASH") | Out-Null
Set-Content -LiteralPath $hashPath -Encoding ascii -NoNewline -Value $hash
$lines = foreach ($key in ($values.Keys | Sort-Object)) { "$key=$($values[$key])" }
Set-Content -LiteralPath $envPath -Encoding ascii -Value $lines
Write-Host "n8n owner is pre-provisioned as automation-admin@demo.local. The generated password is in .local/n8n-owner-password."
