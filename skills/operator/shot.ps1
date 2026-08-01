# Bildschirmfoto des gesamten virtuellen Desktops.
#
# Als eigene Datei und nicht als -Command-Einzeiler, weil der Aufruf sonst
# ueber ssh durch zwei Shells laeuft und jedes $ und " neu zerlegt wird.
#
# Parameter Ziel: Pfad der PNG-Datei.

param([Parameter(Mandatory = $true)][string]$Ziel)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing

$bereich = [Windows.Forms.SystemInformation]::VirtualScreen

# In einer Dienst-Sitzung (Session 0, etwa ueber sshd) gibt es keinen echten
# Desktop. Windows meldet dann einen Ersatzbereich von 1024x768 und
# CopyFromScreen scheitert mit "Das Handle ist ungueltig". Das hier frueh und
# verstaendlich melden, statt den Win32-Fehler durchzureichen.
if ($bereich.Width -le 0 -or $bereich.Height -le 0) {
    throw 'Kein Desktop sichtbar (Dienst-Sitzung?).'
}

$bild = New-Object Drawing.Bitmap $bereich.Width, $bereich.Height
$zeichen = [Drawing.Graphics]::FromImage($bild)
try {
    $zeichen.CopyFromScreen($bereich.Location, [Drawing.Point]::Empty, $bereich.Size)
    $ordner = Split-Path -Parent $Ziel
    if (-not (Test-Path $ordner)) { New-Item -ItemType Directory -Force $ordner | Out-Null }
    $bild.Save($Ziel, [Drawing.Imaging.ImageFormat]::Png)
    "$($bereich.Width)x$($bereich.Height)"
} finally {
    $zeichen.Dispose()
    $bild.Dispose()
}
