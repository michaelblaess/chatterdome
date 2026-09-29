# Setzt eine Claude-Sitzung in einem neuen Fenster fort.
#
# Wird von der geplanten Aufgabe ClaudeChatterdomeNeustart aufgerufen, damit der
# Start im angemeldeten Benutzerkontext passiert. Ueber ssh laeuft der Aufruf
# sonst in Session 0 und kommt an keinen Desktop.
#
# Die Parameter stehen in einer Datei, nicht in der Befehlszeile: schtasks
# haelt einen festen Befehl fest, die Sitzungskennung wechselt aber bei jedem
# Neustart.

$ErrorActionPreference = 'Stop'

$rechner = $env:COMPUTERNAME.ToUpper()
$ordner = Join-Path $env:USERPROFILE ".claude\bus\$rechner"
$auftragsDatei = Join-Path $ordner 'neustart-auftrag.json'
$ergebnisDatei = Join-Path $ordner 'neustart-ergebnis.json'

function Melde([bool]$ok, [string]$fehler) {
    $inhalt = @{ ok = $ok; fehler = $fehler } | ConvertTo-Json -Compress
    # OHNE Stueckliste schreiben: Set-Content -Encoding utf8 setzt in
    # PowerShell 5.1 eine BOM davor, und daran scheitert JSON.parse auf der
    # Node-Seite mit "Unexpected token".
    [System.IO.File]::WriteAllText($ergebnisDatei, $inhalt, (New-Object System.Text.UTF8Encoding $false))
}

try {
    if (-not (Test-Path $auftragsDatei)) { throw 'Keine Auftragsdatei gefunden.' }
    $auftrag = Get-Content -Raw -Encoding UTF8 $auftragsDatei | ConvertFrom-Json
    if (-not $auftrag.session) { throw 'Auftrag ohne Sitzungskennung.' }

    $verzeichnis = $env:USERPROFILE
    if ($auftrag.cwd -and (Test-Path $auftrag.cwd)) { $verzeichnis = $auftrag.cwd }

    $wt = Get-Command wt -ErrorAction SilentlyContinue
    if ($null -ne $wt) {
        Start-Process 'wt' -ArgumentList @('-d', $verzeichnis, 'claude', '--resume', $auftrag.session)
    } else {
        # Rueckfall ohne Windows Terminal. /k haelt das Fenster offen, falls
        # claude sofort abbricht - sonst waere der Grund nicht zu sehen.
        Start-Process 'cmd' -WorkingDirectory $verzeichnis `
            -ArgumentList @('/k', "claude --resume $($auftrag.session)")
    }
    Melde $true ''
} catch {
    Melde $false $_.Exception.Message
}
