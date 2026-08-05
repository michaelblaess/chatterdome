"""Die PowerShell-Skripte des Repos gegen eine wiederkehrende Falle sichern.

`Invoke-Nativ` reicht Argumente an ein Programm durch. Bekommt die Funktion
einen `param()`-Block mit `[Parameter()]`-Attribut, wird sie zur advanced
function und erbt die Common-Parameter - danach bindet PowerShell jedes
Argument an SICH, das ein Praefix davon ist, statt es weiterzugeben:

    uv pip install -e <pfad>   Abbruch, "-e" ist zwischen -ErrorAction und
                               -ErrorVariable nicht eindeutig
    uv -v run                  still geschluckt als -Verbose, kommt beim
                               Programm nie an - kein Fehler, keine Warnung

Der zweite Fall ist der gefaehrliche und faellt ohne Test nie auf. Geprueft
wird deshalb das Verhalten, nicht der Quelltext: die echte Funktion wird aus
dem Skript geladen und mit genau diesen Argumenten aufgerufen.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
SKRIPTE = ("bootstrap.ps1", "compile-win64.ps1")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell") is None,
    reason="Windows PowerShell nicht vorhanden",
)


def _funktion(skript: str) -> str:
    """Schneidet die Definition von Invoke-Nativ aus einem Skript."""
    text = (WURZEL / skript).read_text(encoding="utf-8")
    treffer = re.search(r"^function Invoke-Nativ \{.*?^\}", text, re.S | re.M)
    assert treffer is not None, f"Invoke-Nativ fehlt in {skript}"
    return treffer.group(0)


def _durchgereicht(skript: str, argumente: str, ordner: Path) -> str:
    """Ruft die echte Funktion auf und meldet, was beim Programm ankam.

    Als Programm dient ein Platzhalter-Skript, das seine Argumente ausgibt -
    so misst der Test die Durchreichung und nicht uv. Bewusst eine echte
    Datei und kein Skriptblock: die alte Fassung castet den ersten Parameter
    nach [string], und ein Skriptblock wuerde daran schon scheitern. Der Test
    waere dann zwar rot, aber aus dem falschen Grund.
    """
    platzhalter = ordner / "echo.ps1"
    platzhalter.write_text("$args -join '|'\n", encoding="utf-8", newline="\n")
    befehl = (
        f"{_funktion(skript)}\n"
        "$global:LASTEXITCODE = 0\n"
        f"Invoke-Nativ '{platzhalter}' {argumente}\n"
    )
    lauf = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", befehl],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    return (lauf.stdout or "") + (lauf.stderr or "")


@pytest.mark.parametrize("skript", SKRIPTE)
class TestInvokeNativ:
    def test_bindestrich_e_kommt_an(self, skript: str, tmp_path: Path) -> None:
        """Der Fall, an dem bootstrap.ps1 real abgebrochen ist."""
        ausgabe = _durchgereicht(skript, 'pip install -e "C:\\x[dev]"', tmp_path)

        assert "nicht eindeutig" not in ausgabe, ausgabe
        assert "-e" in ausgabe, f"-e wurde verschluckt: {ausgabe}"
        assert "C:\\x[dev]" in ausgabe

    def test_bindestrich_v_wird_nicht_still_geschluckt(
        self, skript: str, tmp_path: Path
    ) -> None:
        """Der stille und deshalb gefaehrlichere Fall.

        Mit param()-Block bindet PowerShell -v an -Verbose, und der Aufruf
        laeuft ohne dieses Flag weiter - ohne jede Meldung.
        """
        ausgabe = _durchgereicht(skript, "-v run", tmp_path)

        assert "-v" in ausgabe, f"-v wurde still geschluckt: {ausgabe}"

    def test_einzelnes_argument_wird_nicht_zeichenweise_gesplattet(
        self, skript: str, tmp_path: Path
    ) -> None:
        """Die Auspack-Falle beim Zerlegen der Argumentliste.

        Wird der Rest ueber einen if-Ausdruck zugewiesen, macht die Pipeline
        aus einem einelementigen Array einen String, und das Splatten
        zerlegt ihn in einzelne Zeichen: aus --version wird - - v e r s i o n.
        """
        ausgabe = _durchgereicht(skript, "--version", tmp_path)

        assert "--version" in ausgabe, ausgabe
        assert "-|-|v|e|r" not in ausgabe, f"zeichenweise gesplattet: {ausgabe}"
