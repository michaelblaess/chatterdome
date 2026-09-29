"""Ein Agentenfenster als Ganzes beenden, nicht nur den Claude-Prozess.

WARUM: ``chatterdome stop`` beendet unter Windows per TerminateProcess. Claude
Code kommt dann nicht mehr dazu, die eingeschaltete Mausverfolgung des
Terminals abzuschalten, und die wieder aktive Shell bekommt jede Mausbewegung
als Text (``[555;46;2M...``). Belegt am 28.09.2026 an den Fenstern einer
Diskussion. Wird dagegen die Shell mitbeendet, die unsere Startdatei
ausfuehrt, liest niemand mehr diese Ereignisse.

Gesucht wird deshalb vom Claude-Prozess aufwaerts die Shell, deren
Befehlszeile eine unserer Startdateien nennt (``start-*.ps1`` oder
``start-*.cmd`` im Temp-Ordner ``chatterdome``, siehe
``kern.terminals.startdatei``). Fehlt sie, wurde das Fenster nicht von
Chatterdome geoeffnet - dann wird nichts beendet, was nicht uns gehoert.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass

MAX_TIEFE = 12

# "claude-sanctuary" ist der Temp-Ordner vor der Umbenennung am 29.09.2026 -
# Fenster, die davor geoeffnet wurden, sollen sich weiter sauber beenden lassen.
_STARTDATEI = re.compile(r"(?:chatterdome|claude-sanctuary)[\\/]+start-[^\\/\s\"']+\.(ps1|cmd)",
                         re.IGNORECASE)


@dataclass(frozen=True)
class Prozess:
    """Das Noetigste eines Prozesses fuer den Weg nach oben."""

    pid: int
    eltern: int
    name: str
    befehl: str


def fensterwurzel(pid: int, prozesse: dict[int, Prozess]) -> int | None:
    """Die PID der Shell, die unsere Startdatei fuer diesen Prozess ausfuehrt.

    :param pid: der Claude-Prozess.
    :param prozesse: alle Prozesse nach PID, siehe ``prozesse_windows``.
    :returns: None, wenn auf dem Weg nach oben keine unserer Startdateien steht.
    """
    aktuell = prozesse.get(pid)
    for _ in range(MAX_TIEFE):
        if aktuell is None:
            return None
        if _STARTDATEI.search(aktuell.befehl):
            return aktuell.pid
        # Windows verwendet PIDs wieder: ein Elternteil, der juenger ist als
        # das Kind, waere ein fremder Prozess. Die Erstellzeit fehlt hier, der
        # Schutz dagegen ist die Startdatei selbst - sie steht nur in unserer
        # eigenen Kette.
        if aktuell.eltern == aktuell.pid:
            return None
        aktuell = prozesse.get(aktuell.eltern)
    return None


def prozesse_windows() -> dict[int, Prozess]:
    """Alle Prozesse mit Eltern-PID und Befehlszeile, in einem einzigen Aufruf."""
    if sys.platform != "win32":
        return {}
    skript = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        lauf = subprocess.run(  # fester Befehl, keine Shell
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", skript],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        roh = json.loads(lauf.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    liste = roh if isinstance(roh, list) else [roh]
    ergebnis: dict[int, Prozess] = {}
    for eintrag in liste:
        if not isinstance(eintrag, dict) or not eintrag.get("ProcessId"):
            continue
        pid = int(eintrag["ProcessId"])
        ergebnis[pid] = Prozess(
            pid=pid,
            eltern=int(eintrag.get("ParentProcessId") or 0),
            name=str(eintrag.get("Name") or ""),
            befehl=str(eintrag.get("CommandLine") or ""),
        )
    return ergebnis


def fenster_beenden(pid: int) -> str:
    """Beendet die Shell unserer Startdatei samt allem darunter.

    :returns: Leer bei Erfolg, sonst der Grund. Kein Fund ist ein Grund, kein
        Erfolg - der Aufrufer faellt dann auf ``chatterdome stop`` zurueck.
    """
    if sys.platform != "win32":
        return "Nur unter Windows umgesetzt."
    wurzel = fensterwurzel(pid, prozesse_windows())
    if wurzel is None:
        return f"Keine Chatterdome-Startdatei ueber PID {pid} gefunden."
    try:
        lauf = subprocess.run(  # fester Befehl, keine Shell
            ["taskkill", "/PID", str(wurzel), "/T", "/F"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        return str(fehler)
    return "" if lauf.returncode == 0 else (lauf.stderr or lauf.stdout).strip()
