#Requires -Version 5.1
<#
.SYNOPSIS
    Déploie GeoTax / Paiement Fiscal sur VPS Hostinger (PostGIS + Redis + Worker).

.USAGE
    cd "D:\Nos logiciels\Paiement fisc"
    .\deploy\hostinger\deploy-to-vps.ps1 -VpsHost root@76.13.36.246
    .\deploy\hostinger\deploy-to-vps.ps1 -SkipDump -SkipRestore
#>
param(
    [string]$VpsHost = "root@76.13.36.246",
    [string]$RemoteDir = "/opt/paiement-fisc",
    [string]$PgDumpPath = "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
    [switch]$SkipDump,
    [switch]$SkipRestore
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $ProjectRoot

$SshBaseArgs = @(
    '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ConnectTimeout=30',
    '-o', 'ServerAliveInterval=15',
    '-o', 'ServerAliveCountMax=40'
)

function Convert-FileToUnixLf {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }
    $text = [System.IO.File]::ReadAllText($Path)
    $text = $text -replace "`r`n", "`n" -replace "`r", "`n"
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $text, $utf8)
}

function Convert-DeployScriptsToUnixLf {
    Get-ChildItem -Path (Join-Path $ProjectRoot "deploy") -Recurse -Filter "*.sh" -File | ForEach-Object {
        Convert-FileToUnixLf $_.FullName
    }
}

Write-Host "=== GeoTax — déploiement VPS Hostinger ===" -ForegroundColor Cyan
Write-Host "Cible : $VpsHost -> $RemoteDir" -ForegroundColor Gray

# --- 1. Export PostgreSQL local ---
$DumpFile = Join-Path $PSScriptRoot "backup.dump"
if (-not $SkipDump) {
    Write-Host "`n=== 1/6 Export PostgreSQL local ===" -ForegroundColor Cyan
    if (-not (Test-Path $DumpFile) -or ((Get-Item $DumpFile).LastWriteTime -lt (Get-Date).AddHours(-1))) {
        if (-not (Test-Path $PgDumpPath)) {
            Write-Error "pg_dump introuvable : $PgDumpPath — installez PostgreSQL ou passez -SkipDump"
        }
        $envFile = Join-Path $ProjectRoot ".env"
        if (-not (Test-Path $envFile)) { Write-Error ".env manquant à la racine du projet" }
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^\s*([^#=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), 'Process')
            }
        }
        $dbUrl = $env:DATABASE_URL
        if (-not $dbUrl) { Write-Error "DATABASE_URL absent de .env" }
        & $PgDumpPath $dbUrl -Fc -f $DumpFile
        if ($LASTEXITCODE -ne 0) { Write-Error "Échec pg_dump" }
    }
    Write-Host "Dump : $DumpFile ($([math]::Round((Get-Item $DumpFile).Length/1KB)) Ko)" -ForegroundColor Green
} else {
    Write-Host "`n=== 1/6 Export ignoré (-SkipDump) ===" -ForegroundColor Yellow
}

# --- 2. Archive projet ---
Write-Host "`n=== 2/6 Création archive projet ===" -ForegroundColor Cyan
Convert-DeployScriptsToUnixLf
Write-Host "Scripts .sh convertis en LF (Unix)" -ForegroundColor Gray

$Archive = Join-Path $env:TEMP "paiement-fisc-deploy.tar.gz"
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) {
    Write-Error "tar requis (Windows 10+). Installez tar ou utilisez Git Bash."
}

$tarArgs = @(
    '-czf', $Archive,
    '--exclude=.env',
    '--exclude=.git',
    '--exclude=instance',
    '--exclude=venv',
    '--exclude=.venv',
    '--exclude=__pycache__',
    '--exclude=qr_codes',
    '--exclude=static/uploads/poi/*',
    '-C', $ProjectRoot,
    '.'
)
& tar @tarArgs
if ($LASTEXITCODE -ne 0) { Write-Error "Échec création archive tar" }

Write-Host "Archive : $Archive ($([math]::Round((Get-Item $Archive).Length/1KB)) Ko)" -ForegroundColor Green

# --- 3. Transfert SSH ---
Write-Host "`n=== 3/6 Transfert vers le VPS (mot de passe SSH requis) ===" -ForegroundColor Cyan
ssh @SshBaseArgs $VpsHost "mkdir -p $RemoteDir/deploy/hostinger"
scp @SshBaseArgs $Archive "${VpsHost}:${RemoteDir}/app.tar.gz"
if (-not $SkipDump -and (Test-Path $DumpFile)) {
    scp @SshBaseArgs $DumpFile "${VpsHost}:${RemoteDir}/deploy/hostinger/backup.dump"
}

# --- 4. Déploiement distant ---
Write-Host "`n=== 4/6 Installation Docker + conteneurs ===" -ForegroundColor Cyan

$restoreFlag = if ($SkipRestore) { "--skip-restore" } else { "" }

# sed AVANT bash (corrige CRLF résiduels) — une seule ligne pour éviter problèmes SSH
$remoteCmd = "cd $RemoteDir && tar -xzf app.tar.gz && rm -f app.tar.gz && find deploy -name '*.sh' -type f -exec sed -i 's/\r$//' {} + && bash deploy/hostinger/remote-update.sh $restoreFlag"

ssh @SshBaseArgs $VpsHost $remoteCmd
if ($LASTEXITCODE -ne 0) {
    Write-Error "Échec déploiement distant (étape 4). Voir les messages ci-dessus."
}

# --- 5. Vérification ---
Write-Host "`n=== 5/6 Vérification ===" -ForegroundColor Cyan
$verifyCmd = "cd $RemoteDir && docker compose --env-file .env ps && echo HEALTH: && curl -sS --max-time 15 http://127.0.0.1:8080/health/ready && echo && docker compose --env-file .env exec -T app python deploy/verify_migration_status.py 2>/dev/null || true"
ssh @SshBaseArgs $VpsHost $verifyCmd

# --- 6. Résumé ---
Write-Host "`n=== 6/6 Terminé ===" -ForegroundColor Green
$ip = ($VpsHost -split '@')[-1]
Write-Host ""
Write-Host "Accès direct  : http://${ip}:8080"
Write-Host "Domaine HTTPS : https://geotax.ittechmed.com"
Write-Host "Admin         : admin / admin123  -> changez le mot de passe !"
Write-Host "Logs          : ssh $VpsHost 'cd $RemoteDir && docker compose --env-file .env logs -f app'"
