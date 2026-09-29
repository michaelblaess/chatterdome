# Startet die Chatterdome-Oberflaeche aus dem Quellcode.
# Kein param()-Block: dann landen Argumente wie --lang in $args, statt dass
# PowerShell sie als Skript-Parameter zu binden versucht.
$ErrorActionPreference = "Continue"

$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

$forward = $args
& $python -m chatterdome @forward
exit $LASTEXITCODE
