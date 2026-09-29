"""Startet einen neuen Agenten in einem eigenen Terminalfenster.

Nur lokal. Ein Fernstart braeuchte ein TTY, das ``ssh host "befehl"`` nicht
liefert - dafuer waere tmux noetig. Ohne Anzeige - der Browser-Zugang als
Dienst - startet der Agent dagegen lokal in einer tmux-Sitzung, siehe ``_zeile``.

Welches Terminal genommen wird und was vorher darin laufen soll, steht in den
Einstellungen. Der eigentliche Aufruf laeuft ueber eine erzeugte Startdatei,
siehe ``kern.terminals`` - dort steht auch, warum.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from chatterdome.kern.einstellungen import Einstellungen
from chatterdome.kern.lokale_quelle import finde_befehl
from chatterdome.kern.terminals import (
    Terminal,
    finde,
    ist_powershell,
    startdatei,
    vorbereitung,
)


def starte_lokal(
    name: str = "",
    verzeichnis: str = "",
    einstellungen: dict[str, Any] | None = None,
    *,
    claude_argumente: list[str] | None = None,
    umgebung: dict[str, str] | None = None,
) -> str:
    """Oeffnet ein Terminalfenster und startet dort eine neue Sitzung.

    :param name: gewuenschter Agentenname, leer fuer den naechsten freien.
    :param verzeichnis: Arbeitsverzeichnis, leer fuer das aktuelle.
    :param einstellungen: geladene Einstellungen, sonst werden sie geholt.
    :param claude_argumente: gehen hinter ``--`` unveraendert an claude, siehe starte.mjs.
    :param umgebung: zusaetzliche Umgebungsvariablen fuer die neue Sitzung.
    :returns: leere Zeichenkette bei Erfolg, sonst die Fehlermeldung.
    """
    befehl = [*finde_befehl(), "start"]
    if name:
        befehl.append(name)
    if claude_argumente:
        befehl += ["--", *claude_argumente]
    return _oeffne(befehl, verzeichnis, einstellungen, umgebung)


def starte_resume(session_id: str, verzeichnis: str = "",
                  einstellungen: dict[str, Any] | None = None) -> str:
    """Setzt eine bestehende Sitzung in einem neuen Terminalfenster fort.

    Bewusst NICHT ueber ``chatterdome start``: das vergibt einen Namen aus dem
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


def _oeffne(
    befehl: list[str],
    verzeichnis: str,
    einstellungen: dict[str, Any] | None,
    umgebung: dict[str, str] | None = None,
) -> str:
    """Gemeinsamer Weg: Startdatei schreiben, Terminal damit oeffnen."""
    werte = einstellungen if einstellungen is not None else Einstellungen().laden()
    ordner = verzeichnis or str(Path.cwd())
    terminal = finde(str(werte.get("terminal", "")))
    if terminal is None:
        return "Kein Terminalprogramm gefunden - in den Einstellungen eines auswaehlen."

    try:
        # PowerShell-Terminals brauchen eine .ps1 mit PowerShell-Syntax; cmd
        # eine .cmd. Die Vorbereitungsbefehle richten sich danach.
        ps = ist_powershell(terminal.schluessel)
        datei = startdatei(vorbereitung(werte, ps), ordner, befehl, ps)
        # Der Terminalname stammt aus der festen Liste in kern.terminals,
        # die Nutzereingaben stehen in der Startdatei - nicht in der Zeile.
        subprocess.Popen(
            _zeile(terminal, datei, ordner),
            env={**saubere_umgebung(), **(umgebung or {})},
            close_fds=True,
            start_new_session=sys.platform != "win32",
        )
    except OSError as fehler:
        return str(fehler)
    return ""


SITZUNGSMARKER = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")
"""Variablen, die eine laufende Claude-Sitzung an ihre Kindprozesse vererbt.

Dazu alles mit ``CLAUDE_CODE_``, siehe ``saubere_umgebung``.
"""

BEHALTEN = ("CLAUDE_CODE_EXECPATH",)
"""Ausnahme: der Pfad zur Claude-Binaerdatei ist kein Sitzungsmarker.

``starte.mjs`` startet damit ohne Shell. Fehlt er, geht der Start ueber den
Wrapper im PATH - am 28.09.2026 kam auf diesem Weg die Namensvorgabe nicht beim
SessionStart-Hook an. Ob das die Ursache war, ist nicht belegt.
"""


def saubere_umgebung() -> dict[str, str]:
    """Die eigene Umgebung ohne die Marker einer laufenden Claude-Sitzung.

    Belegt am 28.09.2026: Aus einer Claude-Sitzung heraus gestartet, erbten
    die neuen Agenten ``CLAUDE_CODE_CHILD_SESSION`` und hielten sich fuer
    Kind-Sitzungen - kein Transkript, keine ``sessions/<pid>.json``, also
    unsichtbar fuer den Operator. Schlimmer noch ``CLAUDE_CODE_MESSAGING_SOCKET``
    und ``_TOKEN``: der neue Agent haette den Inbox-Socket der startenden
    Sitzung fuer seinen eigenen gehalten. Aus der TUI heraus fiel das nie auf,
    weil die ueblicherweise nicht in einer Claude-Sitzung laeuft.
    """
    return {
        schluessel: wert
        for schluessel, wert in os.environ.items()
        if schluessel.upper() in BEHALTEN
        or (
            not schluessel.upper().startswith("CLAUDE_CODE_")
            and schluessel.upper() not in SITZUNGSMARKER
        )
    }


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
        # start oeffnet ein NEUES Fenster - ohne das laeuft PowerShell in der
        # Konsole der Oberflaeche und schreibt seine Ausgabe dort hinein.
        return ["cmd", "/c", "start", "", programm, "-NoExit", "-NoProfile", "-File", pfad]
    if terminal.schluessel == "cmd":
        return ["cmd", "/c", "start", "", "cmd", "/k", pfad]
    if terminal.schluessel == "tmux":
        # Ohne Fenster: eigene Sitzung im Hintergrund, spaeter mit
        # "tmux attach -t agent-..." anzusehen. exec bash haelt die Sitzung
        # offen, wenn Claude endet - wie bei den Fenster-Terminals.
        sitzung = f"agent-{time.strftime('%H%M%S')}"
        return [programm, "new-session", "-d", "-s", sitzung, "-c", ordner,
                "bash", "-lc", f"{pfad}; exec bash"]
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
    return finde("") is not None


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
