#Requires -Version 5.1
<#
.SYNOPSIS
    Richtet die Entwicklungsumgebung fuer die Sanctuary-Oberflaeche ein.
.DESCRIPTION
    Legt die virtuelle Umgebung an und installiert Laufzeit- und
    Entwicklungsabhaengigkeiten. Mehrfach aufrufbar.
#>
$ErrorActionPreference = "Stop"

function Invoke-Nativ {
    <#
    .SYNOPSIS
        Ruft ein Programm auf und bewertet ausschliesslich dessen Exit-Code.
    .DESCRIPTION
        PowerShell 5.1 verpackt jede stderr-Zeile eines nativen Programms in
        einen ErrorRecord, sobald die Ausgabe umgeleitet wird. In einer
        CI-Umgebung ist sie das immer, und uv meldet seinen Fortschritt nach
        stderr - ohne diese Kapselung bricht das Skript dort bei einer
        blossen Statuszeile ab. Continue gilt nur innerhalb der Funktion.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Datei,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumente
    )
    $ErrorActionPreference = "Continue"
    & $Datei @Argumente
    if ($LASTEXITCODE -ne 0) {
        throw "$Datei $($Argumente -join ' ') scheiterte (Exit $LASTEXITCODE)"
    }
}

$root = $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv fehlt. Installation: https://docs.astral.sh/uv/"
}

# Hinter einem TLS-aufbrechenden Firmen-Proxy kennt uv die Root-CA nicht.
$env:UV_SYSTEM_CERTS = "1"
$env:SSL_CERT_FILE = $null

if (-not (Test-Path (Join-Path $root ".venv"))) {
    Write-Host "Lege .venv an..." -ForegroundColor Cyan
    Invoke-Nativ uv venv --project $root
}

Write-Host "Installiere Abhaengigkeiten..." -ForegroundColor Cyan
Invoke-Nativ uv pip install --python (Join-Path $root ".venv\Scripts\python.exe") -e "$root[dev]"

Write-Host "Fertig. Start mit .\run.ps1" -ForegroundColor Green
