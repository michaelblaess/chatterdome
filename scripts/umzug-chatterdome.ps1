# Umzug claude-sanctuary -> chatterdome auf diesem Rechner (Windows).
#
# Aufruf aus dem ALTEN Ordner, nachdem der neue Stand gezogen ist:
#   git pull
#   powershell -ExecutionPolicy Bypass -File scripts\umzug-chatterdome.ps1
#
# Vorher alles schliessen, was im Ordner laeuft: Claude-Sitzungen, Sanctuary,
# Terminals. Windows laesst einen Ordner nicht umbenennen, der das aktuelle
# Verzeichnis eines Prozesses ist.
#
# Was passiert:
#   1. Ordner claude-sanctuary -> chatterdome (daneben, gleicher Elternordner)
#   2. git remote auf github.com/michaelblaess/chatterdome
#   3. .venv neu - ihre Startdateien enthalten den alten Pfad
#   4. setup.ps1: Skill-Links, Kurzbefehle chatterdome und sanctuary (Alias)
#   5. bootstrap.ps1: Abhaengigkeiten in die neue .venv
# Der Datenordner ~/.claude-sanctuary wird beim ersten Start kopiert, nicht hier.

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$eltern = Split-Path -Parent $repo
$neu = Join-Path $eltern 'chatterdome'

if ((Split-Path -Leaf $repo) -ne 'chatterdome') {
    if (Test-Path $neu) {
        throw "Es gibt schon $neu - bitte erst nachsehen, was dort liegt."
    }
    # Den Ordner verlassen, sonst haelt diese Sitzung ihn selbst fest.
    Set-Location $eltern
    try {
        Rename-Item -LiteralPath $repo -NewName 'chatterdome'
    } catch {
        Write-Host ''
        Write-Host "Der Ordner laesst sich nicht umbenennen: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'Meist laeuft noch etwas darin: eine Claude-Sitzung, Sanctuary oder ein Terminal.'
        Write-Host 'Alles schliessen und das Skript noch einmal aufrufen.'
        exit 1
    }
    Write-Host "[OK]   Ordner: $repo -> $neu"
} else {
    Write-Host "[OK]   Ordner heisst schon chatterdome"
}

$url = (git -C $neu remote get-url origin).Trim()
if ($url -match 'claude-sanctuary') {
    $neueUrl = $url -replace 'claude-sanctuary', 'chatterdome'
    git -C $neu remote set-url origin $neueUrl
    Write-Host "[OK]   Remote: $neueUrl"
} else {
    Write-Host "[OK]   Remote: $url"
}

$venv = Join-Path $neu '.venv'
if (Test-Path $venv) {
    Remove-Item -LiteralPath $venv -Recurse -Force
    Write-Host '[OK]   alte .venv entfernt'
}

& (Join-Path $neu 'setup.ps1')
& (Join-Path $neu 'bootstrap.ps1')

Write-Host ''
Write-Host 'Umzug fertig. Neue Konsole oeffnen, dann:'
Write-Host "  cd $neu"
Write-Host '  chatterdome status'
Write-Host '  .\run.ps1'
