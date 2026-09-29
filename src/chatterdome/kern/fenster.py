"""Das Fenster eines Agenten: zusehen und hineinschreiben.

WARUM DAS NOETIG IST: Der Bus transportiert Auftraege, aber nicht die
Bedienung des Fensters. Alles, wofuer ein Mensch in der Zielsitzung sitzen
muss - Berechtigungsdialoge, der Trust-Dialog, ein Slash-Befehl - ist ueber
den Bus grundsaetzlich nicht erreichbar, und das ist Absicht: eine
Busnachricht ist Fremdeingabe und kann keine Zustimmung Michaels sein.

Eine Eingabe im FENSTER des Agenten ist dagegen seine Eingabe. Genau diese
Grenze zieht Claude Code selbst. Dieses Modul stellt sie her, mehr nicht: es
entscheidet nichts, es reicht Tastendruecke weiter.

WARUM UEBER DIE PID UND NICHT UEBER EINEN GEMERKTEN NAMEN: ``starter.py``
erzeugt den tmux-Namen aus der Uhrzeit und wirft ihn weg. Ihn festzuhalten
wuerde nur fuer Agenten wirken, die ab sofort ueber die Oberflaeche starten -
alle bereits laufenden blieben unerreichbar, und nach einem Neustart der
Oberflaeche waere die Zuordnung wieder weg. Die PID steht dagegen ohnehin in
jeder Statusabfrage (``Agent.pid``), und tmux kennt die PID jeder Pane. Der
Weg von der einen zur anderen ist die Elternkette.

Belegt am 16.09.2026 auf senza: Pane ``agent-112803`` hat pane_pid 743298,
und Snorres Prozess 743316 haengt darunter (743316 -> 743315 -> 743308 ->
743307 -> 743298).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

ZEITGRENZE = 5.0
"""Sekunden je tmux-Aufruf. tmux antwortet lokal in Millisekunden - wer hier
haengt, haengt an etwas anderem und soll nicht die Oberflaeche mitnehmen."""

MAX_TIEFE = 16
"""Wie weit die Elternkette verfolgt wird. Schutz gegen eine Schleife, falls
``/proc`` einmal Unsinn liefert. Die echte Kette war vier Glieder lang."""

SITZUNG_ERLAUBT = re.compile(r"\A[A-Za-z0-9_.][A-Za-z0-9_.-]{0,63}\Z")
"""Zulaessige tmux-Sitzungsnamen.

Der Bindestrich ist INNEN erlaubt (``agent-112803``), am Anfang aber nicht:
die Aufrufe laufen zwar ohne Shell, doch tmux selbst liest ein fuehrendes
``-`` als Option. Der Test hat genau das aufgedeckt - die erste Fassung der
Zeichenklasse liess ``-x`` durch.
"""


def verfuegbar() -> bool:
    """Wahr, wenn auf diesem Rechner ueberhaupt tmux-Fenster moeglich sind."""
    return sys.platform != "win32" and shutil.which("tmux") is not None


def panes() -> dict[int, str]:
    """Alle tmux-Panes als Abbildung pane_pid auf Sitzungsname."""
    zeilen = _tmux(["list-panes", "-a", "-F", "#{pane_pid} #{session_name}"])
    ergebnis: dict[int, str] = {}
    for zeile in zeilen.splitlines():
        pid, _, name = zeile.partition(" ")
        if pid.isdigit() and name:
            ergebnis[int(pid)] = name
    return ergebnis


def elternteil(pid: int) -> int | None:
    """Die Eltern-PID eines Prozesses, gelesen aus ``/proc``.

    Bewusst ohne Unterprozess: diese Funktion laeuft je Agent und je
    Aktualisierung, ein ``ps``-Aufruf dafuer waere Verschwendung.

    :returns: None, wenn der Prozess nicht existiert oder die Zeile unlesbar ist.
    """
    try:
        roh = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Feld 4 ist die PPID. Der Prozessname in Feld 2 steht in Klammern und darf
    # Leerzeichen enthalten - deshalb hinter der letzten Klammer schneiden.
    rest = roh.rpartition(")")[2].split()
    if len(rest) < 2 or not rest[1].lstrip("-").isdigit():
        return None
    return int(rest[1])


def sitzung_fuer(
    pid: int | None,
    *,
    tabelle: Mapping[int, str] | None = None,
    eltern: Callable[[int], int | None] | None = None,
) -> str:
    """Die tmux-Sitzung, in der dieser Prozess laeuft.

    :param pid: PID des Agenten, wie sie in der Statusabfrage steht.
    :param tabelle: Abbildung pane_pid auf Sitzung, sonst wird sie geholt.
    :param eltern: Zugriff auf die Eltern-PID, sonst ``elternteil``.
    :returns: Sitzungsname, oder leer wenn der Prozess in keiner Pane liegt.
    """
    if not pid or pid <= 0:
        return ""
    bekannt = panes() if tabelle is None else tabelle
    if not bekannt:
        return ""
    hoch = elternteil if eltern is None else eltern

    aktuell: int | None = pid
    for _ in range(MAX_TIEFE):
        if aktuell is None or aktuell <= 1:
            return ""
        if aktuell in bekannt:
            return bekannt[aktuell]
        aktuell = hoch(aktuell)
    return ""


class TmuxFenster:
    """Ein Agentenfenster, das in einer tmux-Sitzung liegt.

    Kann genau zwei Dinge: den Bildschirm liefern und Tasten annehmen. Mehr
    gehoert hier nicht hinein - Chatterdome wird kein Multiplexer.
    """

    def __init__(self, sitzung: str) -> None:
        if not SITZUNG_ERLAUBT.match(sitzung):
            raise ValueError(f"Unzulaessiger Sitzungsname: {sitzung!r}")
        self._sitzung = sitzung

    @property
    def sitzung(self) -> str:
        return self._sitzung

    def bildschirm(self, *, farben: bool = True) -> str:
        """Der aktuelle Bildschirminhalt.

        tmux hat die Terminalemulation bereits gemacht - was hier herauskommt,
        ist ein flacher Abzug ohne Cursorsteuerung, eine Zeile je Zeile.

        :param farben: Farbcodes mitnehmen (``-e``). Fuer die Mustererkennung
            stoeren sie, fuer die Anzeige braucht man sie.
        """
        args = ["capture-pane", "-p", "-t", self._sitzung]
        if farben:
            args.insert(1, "-e")
        return _tmux(args)

    def schreiben(self, text: str) -> None:
        """Schickt Text buchstaeblich ins Fenster, ohne Abschluss.

        ``-l`` ist wesentlich: ohne das deutet tmux Woerter wie "Enter" oder
        "C-c" als Tastennamen - ein Auftragstext, in dem "Enter" vorkommt,
        wuerde sonst mitten im Satz eine Zeile abschicken.
        """
        if text:
            _tmux(["send-keys", "-t", self._sitzung, "-l", "--", text])

    def taste(self, name: str) -> None:
        """Schickt eine benannte Taste, etwa ``Enter``, ``Escape`` oder ``C-c``."""
        if name:
            _tmux(["send-keys", "-t", self._sitzung, name])

    def groesse_setzen(self, spalten: int, zeilen: int) -> None:
        """Passt das tmux-Fenster an die Groesse der Anzeige an.

        Ohne das bricht tmux nach seiner eigenen Breite um, und im Browser
        steht der Text dann mit fremden Umbruechen.
        """
        if spalten > 0 and zeilen > 0:
            _tmux(["resize-window", "-t", self._sitzung, "-x", str(spalten), "-y", str(zeilen)])


def _tmux(args: list[str]) -> str:
    """Ruft tmux auf und liefert die Ausgabe, oder leer bei jedem Fehler.

    Bewusst ohne Ausnahme nach aussen: ein Fenster, das gerade geschlossen
    wurde, ist ein Normalfall und kein Grund, die Oberflaeche anzuhalten.
    """
    programm = shutil.which("tmux")
    if programm is None:
        return ""
    try:
        lauf = subprocess.run(
            [programm, *args],
            capture_output=True,
            text=True,
            timeout=ZEITGRENZE,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return lauf.stdout if lauf.returncode == 0 else ""
