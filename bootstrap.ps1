#Requires -Version 5.1
<#
.SYNOPSIS
    Richtet die Entwicklungsumgebung fuer die Chatterdome-Oberflaeche ein.
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

        KEIN param()-Block. Ein [Parameter()]-Attribut macht daraus eine
        advanced function, und die bekommt die Common-Parameter dazu. Danach
        bindet PowerShell jedes Argument an SICH, das ein Praefix eines
        solchen Parameters ist, statt es durchzureichen:

          uv pip install -e <pfad>   -> Abbruch, "-e" ist zwischen
                                        -ErrorAction und -ErrorVariable
                                        nicht eindeutig
          uv -v run                  -> SCHLIMMER, "-v" wird still als
                                        -Verbose geschluckt und kommt bei uv
                                        nie an. Kein Fehler, keine Warnung.

        Ueber $args gibt es kein Binding, alles geht unveraendert weiter.
    #>
    $liste = @($args)
    if ($liste.Count -eq 0) {
        throw "Invoke-Nativ ohne Programm aufgerufen"
    }
    $datei = $liste[0]
    # Direkte Zuweisung mit @(...), kein if-Ausdruck: der gibt ueber die
    # Pipeline zurueck und packt ein einelementiges Array zu einem String
    # aus - @rest wuerde ihn danach zeichenweise splatten.
    $rest = @()
    if ($liste.Count -gt 1) {
        $rest = @($liste[1..($liste.Count - 1)])
    }
    $ErrorActionPreference = "Continue"
    & $datei @rest
    if ($LASTEXITCODE -ne 0) {
        throw "$datei $($rest -join ' ') scheiterte (Exit $LASTEXITCODE)"
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
