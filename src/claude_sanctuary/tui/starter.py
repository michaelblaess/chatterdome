"""Startet einen neuen Agenten in einem eigenen Terminalfenster.

Nur lokal. Ein Fernstart braeuchte ein TTY, das ``ssh host "befehl"`` nicht
liefert - dafuer waere tmux noetig, und das ist bewusst nicht Teil dieser
Fassung.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from claude_sanctuary.kern.lokale_quelle import finde_befehl


def starte_lokal(name: str = "", verzeichnis: str = "") -> str:
    """Oeffnet ein Terminalfenster und startet dort eine neue Sitzung.

    :param name: gewuenschter Agentenname, leer fuer den naechsten freien.
    :param verzeichnis: Arbeitsverzeichnis, leer fuer das aktuelle.
    :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
    """
    ordner = verzeichnis or str(Path.cwd())
    befehl = [*finde_befehl(), "start"]
    if name:
        befehl.append(name)

    try:
        if sys.platform == "win32":
            return _windows(befehl, ordner)
        return _unix(befehl, ordner)
    except OSError as fehler:
        return str(fehler)


def _windows(befehl: list[str], ordner: str) -> str:
    """Neuer Tab im laufenden Windows Terminal, sonst ein eigenes Fenster."""
    wt = shutil.which("wt")
    if wt:
        # -w 0 haengt den Tab an das bereits offene Fenster an.
        subprocess.Popen(
            [wt, "-w", "0", "nt", "-d", ordner, "cmd", "/k", *befehl],
            close_fds=True,
        )
        return ""
    subprocess.Popen(
        ["cmd", "/c", "start", "", "cmd", "/k", *befehl],
        cwd=ordner,
        close_fds=True,
    )
    return ""


def _unix(befehl: list[str], ordner: str) -> str:
    """Erster verfuegbarer Terminal-Emulator gewinnt."""
    zeile = " ".join(_quote(teil) for teil in befehl)
    kandidaten: list[list[str]] = [
        ["gnome-terminal", "--working-directory", ordner, "--",
         "bash", "-lc", f"{zeile}; exec bash"],
        ["konsole", "--workdir", ordner, "-e", "bash", "-lc", f"{zeile}; exec bash"],
        ["xfce4-terminal", "--working-directory", ordner, "-e", f"bash -lc '{zeile}; exec bash'"],
        ["xterm", "-e", f"bash -lc 'cd {_quote(ordner)}; {zeile}; exec bash'"],
    ]
    for kandidat in kandidaten:
        if shutil.which(kandidat[0]):
            subprocess.Popen(kandidat, close_fds=True, start_new_session=True)
            return ""
    return "Kein Terminal-Emulator gefunden (gnome-terminal, konsole, xfce4-terminal, xterm)"


def _quote(text: str) -> str:
    """Minimales Quoting fuer die Shell-Zeile."""
    if not text or any(zeichen in text for zeichen in " \t\"'"):
        return "'" + text.replace("'", "'\\''") + "'"
    return text


def terminal_vorhanden() -> bool:
    """Wahr, wenn ueberhaupt ein Terminal gestartet werden kann."""
    if sys.platform == "win32":
        return True  # cmd gibt es immer
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return any(
            shutil.which(name)
            for name in ("gnome-terminal", "konsole", "xfce4-terminal", "xterm")
        )
    return False
