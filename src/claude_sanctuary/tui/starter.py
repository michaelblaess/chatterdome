"""Startet einen neuen Agenten in einem eigenen Terminalfenster.

Nur lokal. Ein Fernstart braeuchte ein TTY, das ``ssh host "befehl"`` nicht
liefert - dafuer waere tmux noetig, und das ist bewusst nicht Teil dieser
Fassung.

Welches Terminal genommen wird und was vorher darin laufen soll, steht in den
Einstellungen. Der eigentliche Aufruf laeuft ueber eine erzeugte Startdatei,
siehe ``kern.terminals`` - dort steht auch, warum.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from claude_sanctuary.kern.einstellungen import Einstellungen
from claude_sanctuary.kern.lokale_quelle import finde_befehl
from claude_sanctuary.kern.terminals import Terminal, finde, startdatei, vorbereitung


def starte_lokal(
    name: str = "",
    verzeichnis: str = "",
    einstellungen: dict[str, Any] | None = None,
) -> str:
    """Oeffnet ein Terminalfenster und startet dort eine neue Sitzung.

    :param name: gewuenschter Agentenname, leer fuer den naechsten freien.
    :param verzeichnis: Arbeitsverzeichnis, leer fuer das aktuelle.
    :param einstellungen: geladene Einstellungen, sonst werden sie geholt.
    :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
    """
    befehl = [*finde_befehl(), "start"]
    if name:
        befehl.append(name)
    return _oeffne(befehl, verzeichnis, einstellungen)


def starte_resume(session_id: str, verzeichnis: str = "",
                  einstellungen: dict[str, Any] | None = None) -> str:
    """Setzt eine bestehende Sitzung in einem neuen Terminalfenster fort.

    Bewusst NICHT ueber ``sanctuary start``: das vergibt einen Namen aus dem
    Pool und lehnt einen bereits vergebenen ab - und beim Fortsetzen ist der
    Name ja noch vergeben, er gehoert dieser Sitzung. ``claude --resume``
    behaelt die Sitzungskennung, und daran haengt die Namenszuordnung. Der
    Agent kommt also unter seinem alten Namen zurueck.

    :param session_id: Kennung der fortzusetzenden Sitzung.
    :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
    """
    if not session_id:
        return "Keine Sitzungskennung bekannt - ohne sie gibt es nichts fortzusetzen."
    claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
    return _oeffne([claude, "--resume", session_id], verzeichnis, einstellungen)


def _oeffne(befehl: list[str], verzeichnis: str, einstellungen: dict[str, Any] | None) -> str:
    """Gemeinsamer Weg: Startdatei schreiben, Terminal damit oeffnen."""
    werte = einstellungen if einstellungen is not None else Einstellungen().laden()
    ordner = verzeichnis or str(Path.cwd())
    terminal = finde(str(werte.get("terminal", "")))
    if terminal is None:
        return "Kein Terminalprogramm gefunden - in den Einstellungen eines auswaehlen."

    try:
        datei = startdatei(vorbereitung(werte), ordner, befehl)
        # Der Terminalname stammt aus der festen Liste in kern.terminals,
        # die Nutzereingaben stehen in der Startdatei - nicht in der Zeile.
        subprocess.Popen(
            _zeile(terminal, datei, ordner),
            close_fds=True,
            start_new_session=sys.platform != "win32",
        )
    except OSError as fehler:
        return str(fehler)
    return ""


def _zeile(terminal: Terminal, datei: Path, ordner: str) -> list[str]:
    """Baut den Aufruf, der das Terminal mit der Startdatei oeffnet."""
    pfad = str(datei)
    programm = shutil.which(terminal.programm) or terminal.programm

    if terminal.schluessel == "wt":
        # -w 0 haengt den Tab an ein bereits offenes Fenster an.
        return [programm, "-w", "0", "nt", "-d", ordner, "cmd", "/k", pfad]
    if terminal.schluessel in {"wezterm", "wezterm-linux"}:
        # start --cwd oeffnet ein neues Fenster im gewuenschten Verzeichnis.
        if sys.platform == "win32":
            return [programm, "start", "--cwd", ordner, "--", "cmd", "/k", pfad]
        return [programm, "start", "--cwd", ordner, "--", "bash", "-lc", f"{pfad}; exec bash"]
    if terminal.schluessel in {"pwsh", "powershell"}:
        return [programm, "-NoExit", "-NoProfile", "-File", pfad]
    if terminal.schluessel == "cmd":
        return ["cmd", "/c", "start", "", "cmd", "/k", pfad]
    if terminal.schluessel == "gnome-terminal":
        return [programm, "--working-directory", ordner, "--",
                "bash", "-lc", f"{pfad}; exec bash"]
    if terminal.schluessel == "konsole":
        return [programm, "--workdir", ordner, "-e", "bash", "-lc", f"{pfad}; exec bash"]
    if terminal.schluessel in {"alacritty", "kitty"}:
        return [programm, "-e", "bash", "-lc", f"{pfad}; exec bash"]
    if terminal.schluessel == "xfce4-terminal":
        return [programm, "--working-directory", ordner, "-e",
                f"bash -lc '{pfad}; exec bash'"]
    if terminal.schluessel == "terminal-app":
        return [programm, "-a", "Terminal", pfad]
    return [programm, "-e", "bash", "-lc", f"{pfad}; exec bash"]


def terminal_vorhanden() -> bool:
    """Wahr, wenn ueberhaupt ein Terminal gestartet werden kann."""
    if sys.platform == "win32":
        return True  # cmd gibt es immer
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return finde("") is not None
    return False


def oeffne_ordner(pfad: str) -> None:
    """Zeigt ein Verzeichnis im Dateimanager des Systems."""
    if not pfad or not Path(pfad).exists():
        return
    if sys.platform == "win32":
        os.startfile(pfad)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", pfad], close_fds=True)
    else:
        subprocess.Popen(["xdg-open", pfad], close_fds=True, start_new_session=True)
