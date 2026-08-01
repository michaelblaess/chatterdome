#Requires -Version 5.1
<#
.SYNOPSIS
    Richtet die Entwicklungsumgebung fuer die Sanctuary-Oberflaeche ein.
.DESCRIPTION
    Legt die virtuelle Umgebung an und installiert Laufzeit- und
    Entwicklungsabhaengigkeiten. Mehrfach aufrufbar.
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv fehlt. Installation: https://docs.astral.sh/uv/"
}

# Hinter einem TLS-aufbrechenden Firmen-Proxy kennt uv die Root-CA nicht.
$env:UV_SYSTEM_CERTS = "1"
$env:SSL_CERT_FILE = $null

if (-not (Test-Path (Join-Path $root ".venv"))) {
    Write-Host "Lege .venv an..." -ForegroundColor Cyan
    & uv venv --project $root
    if ($LASTEXITCODE -ne 0) { throw "uv venv fehlgeschlagen" }
}

Write-Host "Installiere Abhaengigkeiten..." -ForegroundColor Cyan
& uv pip install --python (Join-Path $root ".venv\Scripts\python.exe") -e "$root[dev]"
if ($LASTEXITCODE -ne 0) { throw "Installation fehlgeschlagen" }

Write-Host "Fertig. Start mit .\run.ps1" -ForegroundColor Green
