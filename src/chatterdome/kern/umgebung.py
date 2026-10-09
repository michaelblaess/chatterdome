"""Wo und als wer die Anwendung laeuft - mit dem Demo-Modus als Sonderfall.

Im Demo-Modus zeigt jeder Bildschirm erfundene Daten (Screenshots fuer das
oeffentliche Repo). Der Weg dahin ist nicht, jede Anzeige einzeln zu
bereinigen, sondern die Quellen zu tauschen: ein eigenes Zuhause mit erzeugten
Transkripten, Notizen und Diskussionen, ein fester Rechnername und eine
Quelle ohne Unterprozesse. Was nie geladen wird, kann nicht durchrutschen.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEMO_RECHNER = "WORKSTATION"
"""Rechnername im Demo-Modus, ueberall dort, wo sonst ``platform.node()`` steht."""

EIGENE_KONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
"""``creationflags`` fuer Hilfsprozesse: eine eigene, unsichtbare Konsole.

Ohne das teilt sich ein Kindprozess die Konsole der Oberflaeche und kann deren
Titel aendern. Im Tab stand statt "chatterdome v0.3.1" meistens nur "Claude"
(Michael, 09.10.2026) - der Operator ruft im Takt ``claude`` auf, und der
setzt seinen Prozesstitel. Ausserhalb von Windows ist der Wert 0 und wirkt nicht.
"""

MARKE = ".chatterdome-demo"
"""Datei in der Demo-Wurzel. Nur ein Ordner mit dieser Marke wird geleert."""

_demo = False


def demo() -> bool:
    """Wahr, wenn die Anwendung im Demo-Modus laeuft."""
    return _demo


def rechnername() -> str:
    """Der Name dieses Rechners, im Demo-Modus der erfundene."""
    return DEMO_RECHNER if _demo else platform.node()


def demo_wurzel() -> Path:
    """Wohin der Demo-Modus sein Zuhause legt.

    Bewusst NICHT unter ``%TEMP%``: der Pfad traegt dort den Benutzernamen,
    und der Einstellungen-Dialog zeigt Pfade an. ``CHATTERDOME_DEMO_DIR``
    ueberschreibt die Vorgabe, etwa wenn das Laufwerk nicht beschreibbar ist.
    """
    eigen = os.environ.get("CHATTERDOME_DEMO_DIR", "").strip()
    if eigen:
        return Path(eigen)
    if sys.platform == "win32":
        laufwerk = os.environ.get("SYSTEMDRIVE", "C:")
        return Path(f"{laufwerk}\\") / "chatterdome-demo"
    return Path("/tmp/chatterdome-demo")


def demo_pool_datei() -> Path:
    """Die Kopie des Namenspools, die der Demo-Modus liest und schreibt.

    Der echte Pool liegt im Repo, daneben die lokale Datei mit eigenen Motiven.
    Der Einstellungen-Dialog wuerde beide lesen und beim Speichern schreiben.
    Bewusst am AKTIVEN Einstellungsordner und nicht an ``demo_wurzel()``: mit
    einer eigenen Wurzel (Tests) landete die Kopie sonst im Vorgabe-Ordner.
    """
    from chatterdome.kern import einstellungen

    return einstellungen.VERZEICHNIS / "namenspool.json"


def _leeren(wurzel: Path) -> None:
    """Raeumt eine fruehere Demo weg - aber nur, wenn es eine war."""
    if not wurzel.exists():
        return
    if not (wurzel / MARKE).is_file() and any(wurzel.iterdir()):
        raise RuntimeError(
            f"{wurzel} ist nicht leer und kein Demo-Verzeichnis (Marke {MARKE} fehlt)."
        )
    shutil.rmtree(wurzel)


def demo_aktivieren(wurzel: Path | None = None) -> Path:
    """Schaltet den Demo-Modus ein und liefert das neue Heimatverzeichnis.

    MUSS vor dem ersten Lesen von Einstellungen laufen. Die Konstanten in
    ``einstellungen`` und ``absturz`` stehen schon seit dem Import fest und
    werden hier neu gesetzt - genauso wie es ``tests/conftest.py`` tut. Alles,
    was erst beim Aufruf ``Path.home()`` fragt, folgt der Umgebung von selbst:
    unter Windows zaehlt dafuer ``USERPROFILE``, sonst ``HOME``.

    :param wurzel: eigenes Verzeichnis statt ``demo_wurzel()``, fuer Tests.
    """
    global _demo

    from chatterdome.kern import absturz, einstellungen

    basis = wurzel if wurzel is not None else demo_wurzel()
    _leeren(basis)
    zuhause = basis / "home"
    temp = basis / "temp"
    zuhause.mkdir(parents=True)
    temp.mkdir()
    (basis / MARKE).write_text("Demo-Modus von Chatterdome, wird bei jedem Start neu angelegt.\n",
                               encoding="utf-8")

    for name in ("USERPROFILE", "HOME"):
        os.environ[name] = str(zuhause)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(temp)
    os.environ["COMPUTERNAME"] = DEMO_RECHNER
    tempfile.tempdir = str(temp)

    einstellungen.VERZEICHNIS = zuhause / ".chatterdome"
    einstellungen.DATEI = einstellungen.VERZEICHNIS / "settings.json"
    einstellungen.ZUSTIMMUNG = einstellungen.VERZEICHNIS / "disclaimer.json"
    einstellungen.ALTES_VERZEICHNIS = zuhause / ".claude-sanctuary"
    absturz.PROTOKOLL = einstellungen.VERZEICHNIS / "fault.log"

    _demo = True
    return zuhause
