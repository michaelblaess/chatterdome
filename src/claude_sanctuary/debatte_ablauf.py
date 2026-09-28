"""Der Ablauf einer Diskussion rund um den Moderator.

Frische Agenten starten und auf ihre Namen warten, moderieren, die selbst
gestarteten Fenster wieder schliessen, zusammenfassen und das Protokoll
ablegen. Kurzbefehl und Oberflaeche benutzen denselben Ablauf - frueher stand
er nur im Kurzbefehl.

Bewusst NICHT in ``kern``: der Start frischer Agenten braucht den Starter der
Oberflaeche (Terminalwahl, Startdatei), und der Kern kennt keine Oberflaeche.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from claude_sanctuary.kern.debatte import (
    Beitrag,
    BusKanal,
    Diskussion,
    Teilnehmer,
    als_markdown,
    moderieren,
    zusammenfassen,
)
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.prozessbaum import fenster_beenden
from claude_sanctuary.tui.starter import saubere_umgebung, starte_lokal

STARTFRIST = 120.0
"""Sekunden, bis eine frisch gestartete Sitzung im Bestand auftauchen muss."""

ANLAUF = 15.0
"""Nach dem Auftauchen: Zeit fuer SessionStart-Hook und Inbox-Socket."""

ZUSAMMENFASSUNG_FRIST = 240.0
"""Sekunden fuer den einmaligen Aufruf, der die Diskussion zusammenfasst."""

ZUSAMMENFASSUNG_LAEUFT = "Zusammenfassung wird erstellt ..."
"""Meldung waehrend der Zusammenfassung. Der Ablauf ist sprachneutral, die Oberflaeche
erkennt die Meldung an dieser Konstante und zeigt ihren eigenen Text."""


@dataclass
class Ergebnis:
    """Was nach dem Ablauf bleibt."""

    diskussion: Diskussion
    protokoll: Path | None = None
    """Die abgelegte Markdown-Datei, None wenn der Ablauf vor dem Start scheiterte."""
    fehler: str = ""
    """Warum der Ablauf gar nicht erst in die Diskussion kam."""


def rechner() -> str:
    """Der eigene Rechnername wie im Bus."""
    # COMPUTERNAME zuerst, weil node() Suffixe wie .local liefern kann.
    return (os.environ.get("COMPUTERNAME") or platform.node().split(".")[0]).upper()


def ablage() -> Path:
    """Arbeitsordner der Diskussionen und Ablage der Protokolle.

    Immer derselbe Ordner: Claude Code fragt nur beim ersten Mal, ob man ihm
    vertraut. Ein neuer Ordner je Diskussion haette die Abfrage jedes Mal.
    """
    ordner = Path.home() / ".claude" / "bus" / rechner() / "diskussionen"
    ordner.mkdir(parents=True, exist_ok=True)
    return ordner


def laufende(quelle: LokaleQuelle) -> dict[str, str]:
    """Laufende Agenten als Sitzungskennung auf Namen."""
    return {a.session_id: a.name for a in quelle.bestand().agenten if a.session_id}


def warte_auf_neue(quelle: LokaleQuelle, vorher: set[str], anzahl: int) -> list[str]:
    """Wartet, bis ``anzahl`` neue Sitzungen im Bestand stehen. Liefert deren Namen.

    Die Namen vergibt der SessionStart-Hook. Welche Sitzung neu ist, verraet
    nur der Vergleich mit dem Stand vor dem Start.
    """
    ende = time.monotonic() + STARTFRIST
    neue: dict[str, str] = {}
    while len(neue) < anzahl and time.monotonic() < ende:
        neue = {s: n for s, n in laufende(quelle).items() if s not in vorher}
        if len(neue) < anzahl:
            time.sleep(3)
    return list(neue.values())


def ohne_kontext(ordner: Path, *, hooks: bool = True) -> tuple[list[str], dict[str, str]]:
    """Claude-Argumente und Umgebung fuer eine Sitzung ohne CLAUDE.md und Memory.

    Nicht ``--bare``: das laesst auch alle Hooks weg (kein Name, kein Socket,
    also kein Bus) und liest kein OAuth. Stattdessen die drei dokumentierten
    Stellschrauben aus code.claude.com/docs/en/memory.md. Am 28.09.2026 mit
    einer Kontrollsitzung gegengeprueft. Die Einstellungen gehen als Datei
    hinein, weil JSON mit Anfuehrungszeichen den Weg durch die .cmd-Startdatei
    nicht heil uebersteht.
    """
    global_md = Path.home() / ".claude" / "CLAUDE.md"
    einstellungen: dict[str, object] = {
        "autoMemoryEnabled": False,
        # Beide Schreibweisen, weil die Doku von Glob-Mustern auf absolute
        # Pfade spricht und offen laesst, wie Windows-Trenner verglichen werden.
        "claudeMdExcludes": [str(global_md), global_md.as_posix()],
    }
    if not hooks:
        # Nur fuer Einmal-Aufrufe. Eine Diskussionssitzung braucht ihre Hooks,
        # sonst hat sie weder Namen noch Socket.
        einstellungen["disableAllHooks"] = True
    datei = ordner / ("ohne-kontext.json" if hooks else "ohne-kontext-ohne-hooks.json")
    datei.write_text(json.dumps(einstellungen, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ["--settings", str(datei)], {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def claude_einmal(auftrag: str, ordner: Path) -> tuple[str, str]:
    """Ein einmaliger ``claude -p``-Aufruf ohne Fenster, ohne Bus und ohne eigenen Kontext.

    Der Auftrag geht ueber stdin, nicht als Argument: der Wrapper claude.cmd
    wuerde ihn sonst am ersten Zeilenumbruch abschneiden, wie es bei
    sanctuary.CMD geschehen ist. Hooks sind abgeschaltet, sonst vergaebe der
    Namens-Hook dem Einmal-Aufruf einen Namen aus dem Pool.

    :returns: ``(text, "")`` bei Erfolg, sonst ``("", grund)``.
    """
    claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
    argumente, umgebung = ohne_kontext(ordner, hooks=False)
    befehl = [claude, "-p", *argumente, "--disallowedTools", "WebSearch", "WebFetch",
              "Bash", "Read", "Write", "Edit"]
    try:
        lauf = subprocess.run(  # fester Befehl, keine Shell
            befehl,
            input=auftrag,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**saubere_umgebung(), **umgebung},
            cwd=str(ordner),
            timeout=ZUSAMMENFASSUNG_FRIST,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        return "", str(fehler)
    if lauf.returncode != 0:
        return "", (lauf.stderr or lauf.stdout).strip()[:500] or f"Exit-Code {lauf.returncode}"
    return lauf.stdout.strip(), ""


def aufraeumen(quelle: LokaleQuelle, namen: list[str]) -> list[str]:
    """Beendet die selbst gestarteten Sitzungen samt ihrem Fenster.

    Erst das ganze Fenster, weil ``stop`` allein unter Windows die
    Mausverfolgung eingeschaltet laesst, siehe ``kern.prozessbaum``. Findet
    sich die Startdatei nicht, bleibt ``stop`` als Rueckfall.

    :returns: je Sitzung, die sich nicht beenden liess, eine Meldung.
    """
    if not namen:
        return []
    meldungen: list[str] = []
    pids = {a.name.lower(): a.pid for a in quelle.bestand().agenten if a.pid}
    for name in namen:
        pid = pids.get(name.lower())
        grund = fenster_beenden(pid) if pid else "PID unbekannt"
        if not grund:
            continue
        fehler = quelle.stoppen(name)
        if fehler:
            meldungen.append(f"{name}: {grund}; {fehler}")
    return meldungen


def ausfuehren(
    diskussion: Diskussion,
    neu: list[Teilnehmer],
    *,
    ohne_eigenen_kontext: bool = False,
    melden: Callable[[str], None] = lambda _text: None,
    beim_beitrag: Callable[[Beitrag], None] | None = None,
    beim_wort: Callable[[Teilnehmer, int], None] | None = None,
    beim_start: Callable[[Diskussion], None] | None = None,
    stopp: threading.Event | None = None,
    quelle: LokaleQuelle | None = None,
) -> Ergebnis:
    """Fuehrt eine Diskussion von Anfang bis Ende aus. Blockiert, gehoert in einen Thread.

    :param diskussion: mit den laufenden Agenten als Teilnehmer, die frischen fehlen noch.
    :param neu: je frische Sitzung ein Teilnehmer, dessen Name ein Platzhalter ist.
        Seite und Rolle werden auf die tatsaechlich vergebenen Namen uebertragen.
    :param ohne_eigenen_kontext: frische Sitzungen ohne eigene CLAUDE.md und Memory.
    :param melden: Fortschrittsmeldungen ausserhalb der Beitraege.
    :param beim_wort: siehe ``moderieren``.
    :param beim_start: bekommt die Diskussion, sobald alle Teilnehmer ihre Namen haben.
    """
    quelle = quelle or LokaleQuelle()
    stopp = stopp or threading.Event()
    ordner = ablage()
    gestartet: list[str] = []

    try:
        if neu:
            vorher = set(laufende(quelle))
            for _ in neu:
                argumente, umgebung = ohne_kontext(ordner) if ohne_eigenen_kontext else ([], {})
                if not diskussion.recherche:
                    # Bei frischen Sitzungen hart gesperrt, bei laufenden Agenten
                    # bleibt es bei der Bitte in der Anweisung.
                    argumente = [*argumente, "--disallowedTools", "WebSearch", "WebFetch"]
                fehler = starte_lokal(
                    verzeichnis=str(ordner), claude_argumente=argumente, umgebung=umgebung
                )
                if fehler:
                    return Ergebnis(diskussion, fehler=f"Start fehlgeschlagen: {fehler}")
            melden(f"{len(neu)} Sitzung(en) gestartet, warte auf die Namen ...")
            gestartet = warte_auf_neue(quelle, vorher, len(neu))
            if len(gestartet) < len(neu):
                return Ergebnis(diskussion, fehler=(
                    f"Nach {STARTFRIST:.0f} s erst {len(gestartet)} von {len(neu)} "
                    "Sitzungen im Bestand."
                ))
            # Kurz warten, damit Hook und Inbox-Socket stehen - aber abbrechbar.
            if stopp.wait(ANLAUF):
                diskussion.ende = "von Hand gestoppt"
                return Ergebnis(diskussion, fehler="Vor dem Start gestoppt.")
            diskussion.teilnehmer = diskussion.teilnehmer + [
                Teilnehmer(name, t.rolle, t.seite)
                for name, t in zip(gestartet, neu, strict=True)
            ]

        namen = ", ".join(t.name for t in diskussion.teilnehmer)
        melden(f'Diskussion: "{diskussion.thema}" mit {namen}')
        if beim_start is not None:
            beim_start(diskussion)
        moderieren(diskussion, BusKanal(quelle, rechner()), beim_beitrag=beim_beitrag,
                   beim_wort=beim_wort, stopp=stopp)
    finally:
        for meldung in aufraeumen(quelle, gestartet):
            melden(f"Nicht beendet: {meldung}")

    if any(b.art in ("beitrag", "schlusswort") for b in diskussion.beitraege):
        melden(ZUSAMMENFASSUNG_LAEUFT)
        grund = zusammenfassen(diskussion, lambda auftrag: claude_einmal(auftrag, ordner))
        if grund:
            melden(f"Keine Zusammenfassung: {grund}")

    datei = ordner / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    datei.write_text(als_markdown(diskussion), encoding="utf-8", newline="\n")
    return Ergebnis(diskussion, protokoll=datei)
