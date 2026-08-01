<#
  setup.ps1 - Haengt ~/.claude/skills/<name> auf dieses Repo (Windows)

  Verwendung:
    git clone https://github.com/michaelblaess/claude-sanctuary.git
    cd claude-sanctuary
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
            Move-Item $link "$link.vor-sanctuary" -Force
            Write-Host "[!]    $Name war ein echtes Verzeichnis - gesichert als $Name.vor-sanctuary"
        }
    }

    cmd /c mklink /J "$link" "$ziel" | Out-Null
    if (0 -eq $LASTEXITCODE) {
        Write-Host "[OK]   $Name -> $ziel"
    } else {
        Write-Warning "mklink fehlgeschlagen (Exit $LASTEXITCODE) fuer $Name"
    }
}

Write-Host 'Claude Sanctuary - Setup'
Write-Host '========================'
Write-Host "Repo:   $repoDir"
Write-Host "Skills: $skillDir"
Write-Host ''

Set-SkillLink -Name 'operator'
Set-SkillLink -Name 'claude-bus'

Write-Host ''
Write-Host 'Fertig. Probe:'
Write-Host '  node ~/.claude/skills/operator/operator.mjs status'
Write-Host '  node ~/.claude/skills/claude-bus/bus.mjs doctor'
