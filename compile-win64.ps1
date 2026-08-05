#Requires -Version 5.1
<#
.SYNOPSIS
    Baut die Sanctuary-Oberflaeche zu einer eigenstaendigen Windows-Binary.
.DESCRIPTION
    Nuitka --standalone, also ein Ordner statt einer selbstentpackenden
    Datei: --onefile entpackt sich bei JEDEM Start nach Temp und frisst den
    Startvorteil wieder auf. Verteilt wird das erzeugte ZIP.

    Ergebnis: dist\claude-sanctuary\sanctuary-tui.exe
              dist\claude-sanctuary-vX.Y.Z-win64.zip
#>
$ErrorActionPreference = "Stop"

function Invoke-Nativ {
    <#
    .SYNOPSIS
        Ruft ein Programm auf und bewertet ausschliesslich dessen Exit-Code.
    .DESCRIPTION
        PowerShell 5.1 verpackt jede stderr-Zeile eines nativen Programms in
        einen ErrorRecord, sobald die Ausgabe umgeleitet wird - in einer
        CI-Umgebung ist sie das immer. Mit ErrorActionPreference = Stop
        bricht das Skript dann schon bei einer Fortschrittsmeldung ab, und
        genau solche schreibt uv nach stderr ("Resolved 30 packages in 3ms").
        Innerhalb dieser Funktion gilt deshalb Continue - das wirkt nur hier.

        KEIN param()-Block. Ein [Parameter()]-Attribut macht daraus eine
        advanced function samt Common-Parametern, und danach bindet
        PowerShell jedes Argument an SICH, das ein Praefix eines solchen
        Parameters ist: "-e" bricht mit "nicht eindeutig" ab, "-v" wird still
        als -Verbose geschluckt und kommt beim Programm nie an. Ueber $args
        gibt es kein Binding. Dieselbe Funktion steht in bootstrap.ps1.
    #>
    $liste = @($args)
    if ($liste.Count -eq 0) {
        throw "Invoke-Nativ ohne Programm aufgerufen"
    }
    $datei = $liste[0]
    # Direkte Zuweisung mit @(...), kein if-Ausdruck: der packt ein
    # einelementiges Array zu einem String aus, den @rest danach zeichenweise
    # splattet.
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
$entry = Join-Path $root "src\claude_sanctuary\__main__.py"
$initPy = Join-Path $root "src\claude_sanctuary\__init__.py"
$outDir = Join-Path $root "dist"
$distDir = Join-Path $outDir "claude-sanctuary"

$version = ([regex]'__version__\s*=\s*"([^"]+)"').Match((Get-Content -Raw $initPy)).Groups[1].Value
if (-not $version) { throw "Konnte __version__ nicht aus $initPy lesen" }

# Hinter einem TLS-aufbrechenden Firmen-Proxy kennt uv die Root-CA nicht.
$env:UV_SYSTEM_CERTS = "1"
$env:SSL_CERT_FILE = $null

# VOR der Python-Ermittlung: bei einem frischen Checkout (CI) gibt es noch
# keine .venv, sonst faellt der naechste Schritt auf das System-Python
# zurueck und Nuitka kompiliert die falsche Umgebung. --inexact laesst
# zusaetzlich installierte Pakete wie Nuitka selbst unangetastet.
if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Host "Gleiche die Umgebung mit uv.lock ab..." -ForegroundColor Cyan
    Invoke-Nativ uv sync --extra dev --inexact --project $root
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

# Nuitka ist bewusst keine Abhaengigkeit im pyproject - es ist Werkzeug,
# nicht Laufzeit. Deshalb hier bei Bedarf nachinstallieren.
$vorhanden = $true
try {
    $ErrorActionPreference = "Continue"
    & $python -m nuitka --version 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { $vorhanden = $false }
} catch {
    $vorhanden = $false
} finally {
    $ErrorActionPreference = "Stop"
}
if (-not $vorhanden) {
    Write-Host "Nuitka fehlt in der Umgebung - installiere..." -ForegroundColor Yellow
    Invoke-Nativ uv pip install --python $python nuitka
}

Write-Host "Kompiliere claude-sanctuary v$version..." -ForegroundColor Cyan
if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
$started = Get-Date

$nuitkaArgs = @(
    "--standalone",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--include-package=claude_sanctuary",
    # Ohne das fehlen locale\*.json und tui\*.tcss zur Laufzeit - die App
    # startet dann ohne Beschriftungen und ohne Layout.
    "--include-package-data=claude_sanctuary",
    # textual_image wird erst innerhalb einer Funktion importiert. Explizit
    # mitnehmen, sonst fehlt die Bildanzeige im fertigen Paket.
    "--include-package=textual_image",
    "--output-dir=$outDir",
    "--output-filename=sanctuary-tui.exe",
    "--company-name=Michael Blaess",
    "--product-name=claude-sanctuary",
    "--file-version=$version",
    "--product-version=$version"
)

$iconPath = Join-Path $root "assets\icon.ico"
if (Test-Path $iconPath) {
    $nuitkaArgs += "--windows-icon-from-ico=$iconPath"
} else {
    Write-Host "Hinweis: $iconPath fehlt - Binary ohne Symbol." -ForegroundColor Yellow
}

Invoke-Nativ $python -m nuitka @nuitkaArgs $entry

# Nuitka benennt den Ordner nach dem Hauptmodul.
$nuitkaDist = Join-Path $outDir "__main__.dist"
if (Test-Path $nuitkaDist) { Rename-Item -Path $nuitkaDist -NewName "claude-sanctuary" }

# Selbsttest gegen die FERTIGE Binary: ein gruener Compile beweist nicht,
# dass die Sprachdateien und das Layout mitgekommen sind.
$exe = Join-Path $distDir "sanctuary-tui.exe"
Write-Host "Selbsttest..." -ForegroundColor Cyan
$ErrorActionPreference = "Continue"
$ausgabe = (& $exe --version 2>&1 | Out-String).Trim()
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "Selbsttest fehlgeschlagen (Exit $code): $ausgabe" }
if ($ausgabe -notmatch [regex]::Escape($version)) {
    throw "Selbsttest lieferte '$ausgabe', erwartet wurde $version"
}
Write-Host "  $ausgabe" -ForegroundColor Green

$elapsed = [int]((Get-Date) - $started).TotalSeconds
$zip = Join-Path $outDir "claude-sanctuary-v$version-win64.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path $distDir -DestinationPath $zip

Write-Host "Fertig in ${elapsed}s" -ForegroundColor Green
Write-Host "  Archiv: $zip"
Write-Host "  Start:  $exe"
