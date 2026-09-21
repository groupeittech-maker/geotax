#Requires -Version 5.1
<#
.SYNOPSIS
    Déploie GeoTax sur le VPS Hostinger (raccourci).

.DESCRIPTION
    Mise à jour code uniquement (recommandé) :
        .\deploy-vps.ps1

    Première installation ou restauration base locale :
        .\deploy-vps.ps1 -Full

    Autre serveur :
        .\deploy-vps.ps1 -VpsHost root@MON.IP

.EXAMPLE
    cd "D:\Nos logiciels\Paiement fisc"
    .\deploy-vps.ps1
#>
param(
    [string]$VpsHost = "root@76.13.36.246",
    [string]$RemoteDir = "/opt/paiement-fisc",
    [switch]$Full,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$DeployScript = Join-Path $ProjectRoot "deploy\hostinger\deploy-to-vps.ps1"

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Full
    exit 0
}

if (-not (Test-Path $DeployScript)) {
    Write-Error "Script introuvable : $DeployScript"
}

Write-Host ""
Write-Host "  GeoTax — déploiement VPS" -ForegroundColor Cyan
Write-Host "  Cible : $VpsHost" -ForegroundColor Gray
if ($Full) {
    Write-Host "  Mode  : complet (export PG local + restauration sur VPS)" -ForegroundColor Yellow
} else {
    Write-Host "  Mode  : mise à jour code (sans toucher à la base)" -ForegroundColor Green
}
Write-Host ""

$params = @{
    VpsHost   = $VpsHost
    RemoteDir = $RemoteDir
}

if (-not $Full) {
    $params.SkipDump = $true
    $params.SkipRestore = $true
}

& $DeployScript @params

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "  Astuce : si la page ne se met pas à jour, videz le cache (Ctrl+F5)." -ForegroundColor Gray
Write-Host "  Site   : https://geotax.ittechmed.com" -ForegroundColor Gray
Write-Host ""
