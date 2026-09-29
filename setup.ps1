<#
  setup.ps1 - Haengt ~/.claude/skills/<name> auf dieses Repo (Windows)

  Verwendung:
    git clone https://github.com/michaelblaess/chatterdome.git
    cd chatterdome
    powershell -ExecutionPolicy Bypass -File .\setup.ps1

  Es werden JUNCTIONS benutzt, keine SymbolicLinks: Junctions auf Verzeichnisse
  darf jeder Benutzer anlegen, echte Symlinks brauchen Adminrechte oder den
  Entwicklermodus. Fuer Verzeichnisse verhalten sich beide gleich.

  Die Skills liegen in diesem Repo, damit die Anwendung ihr eigenes Repo hat.
  Fuer Claude Code aendert sich nichts - die Junctions stellen sie an genau der
  Stelle bereit, an der sie vorher lagen.
#>
$ErrorActionPreference = 'Stop'

$repoDir  = $PSScriptRoot
$skillDir = Join-Path $env:USERPROFILE '.claude\skills'
New-Item -ItemType Directory -Force $skillDir | Out-Null

function Set-SkillLink {
    param([string]$Name)

    $ziel = Join-Path $repoDir "skills\$Name"
    $link = Join-Path $skillDir $Name

    if (-not (Test-Path $ziel)) {
        Write-Host "[SKIP] $Name - Quelle fehlt: $ziel"
        return
    }

    $vorhanden = Get-Item $link -ErrorAction SilentlyContinue
    if ($null -ne $vorhanden) {
        if ($vorhanden.LinkType) {
            # Zeigt der Link schon hierher, ist nichts zu tun.
            $altesZiel = $vorhanden.Target | Select-Object -First 1
            if ($altesZiel -eq $ziel) {
                Write-Host "[OK]   $Name - zeigt bereits hierher"
                return
            }
            (Get-Item $link).Delete()
            Write-Host "[UM]   $Name - war: $altesZiel"
        } else {
            # Echtes Verzeichnis: niemals loeschen, nur beiseite legen.
            Move-Item $link "$link.vor-chatterdome" -Force
            Write-Host "[!]    $Name war ein echtes Verzeichnis - gesichert als $Name.vor-chatterdome"
        }
    }

    cmd /c mklink /J "$link" "$ziel" | Out-Null
    if (0 -eq $LASTEXITCODE) {
        Write-Host "[OK]   $Name -> $ziel"
    } else {
        Write-Warning "mklink fehlgeschlagen (Exit $LASTEXITCODE) fuer $Name"
    }
}

Write-Host 'Chatterdome - Setup'
Write-Host '========================'
Write-Host "Repo:   $repoDir"
Write-Host "Skills: $skillDir"
Write-Host ''

Set-SkillLink -Name 'operator'
Set-SkillLink -Name 'claude-bus'

# --- Kurzbefehl "chatterdome" ins PATH-Verzeichnis ---
#
# Zwei Dateien, weil Michael beide Shells benutzt: die .cmd greift in
# PowerShell und cmd, die endungslose Datei in Git Bash. Beide rufen dasselbe
# Skript auf.
$binDir = Join-Path $env:USERPROFILE '.local\bin'
New-Item -ItemType Directory -Force $binDir | Out-Null

$mjsPfad = Join-Path $repoDir 'bin\chatterdome.mjs'
$shMjs = $mjsPfad -replace '\\', '/'
# "sanctuary" ist der alte Name und bleibt als Alias: andere Rechner rufen ihn
# ueber ssh auf, und deren Stand kann aelter sein als dieser.
foreach ($kurz in @('chatterdome', 'sanctuary')) {
    $cmdPfad = Join-Path $binDir "$kurz.cmd"
    "@echo off`r`nnode `"$mjsPfad`" %*" | Out-File $cmdPfad -Encoding ascii
    Write-Host "[OK]   $kurz.cmd -> $cmdPfad"

    $shPfad = Join-Path $binDir $kurz
    # LF-Zeilenenden, sonst stolpert bash ueber das Wagenruecklauf-Zeichen im Shebang.
    $shInhalt = "#!/usr/bin/env bash`nexec node `"$shMjs`" `"`$@`"`n"
    [System.IO.File]::WriteAllText($shPfad, $shInhalt, [System.Text.UTF8Encoding]::new($false))
    Write-Host "[OK]   $kurz (Git Bash) -> $shPfad"
}

# --- ~/.local/bin in den Benutzer-PATH, falls es fehlt ---
#
# Ohne diesen Eintrag findet nur die eigene Shell den Kurzbefehl. Entscheidend
# ist er aber fuer "status --mesh": der sshd unter Windows reicht den
# Benutzer-PATH an eingehende Verbindungen weiter, und ohne ihn scheitert die
# Fernabfrage mit "Command failed" (auf DELL am 01.08.2026 genau so gesehen,
# obwohl der Kurzbefehl mit vollem Pfad einwandfrei lief).
#
# Nur ANHAENGEN, niemals den PATH neu setzen - ein zerschossener Benutzer-PATH
# ist teuer zu reparieren.
$pfadJetzt = [Environment]::GetEnvironmentVariable('PATH', 'User')
if ($pfadJetzt -notlike "*$binDir*") {
    $neu = if ([string]::IsNullOrWhiteSpace($pfadJetzt)) { $binDir } else { "$pfadJetzt;$binDir" }
    [Environment]::SetEnvironmentVariable('PATH', $neu, 'User')
    Write-Host "[OK]   $binDir in den Benutzer-PATH aufgenommen"
    Write-Host '       (wirkt in neuen Konsolen - die aktuelle kennt ihn noch nicht)'
} else {
    Write-Host "[OK]   $binDir liegt bereits im PATH"
}

Write-Host ''
Write-Host 'Fertig. Probe:'
Write-Host '  chatterdome status'
Write-Host '  chatterdome doctor'
