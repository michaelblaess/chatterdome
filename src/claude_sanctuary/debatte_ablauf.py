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
import sqlite3
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
    Verbrauch,
    als_markdown,
    moderieren,
    zusammenfassen,
)
from claude_sanctuary.kern.diskussionsarchiv import Diskussionsarchiv
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle
from claude_sanctuary.kern.prozessbaum import fenster_beenden
from claude_sanctuary.kern.transkripte import claude_anfragen_ab, claude_transkript
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


def _json_antwort(ausgabe: str) -> tuple[str, Verbrauch]:
    """Zerlegt die Ausgabe von ``claude -p --output-format json`` in Text und Verbrauch.

    Aufbau am 28.09.2026 mit einem echten Aufruf geprueft: ``result`` traegt
    den Text, ``usage`` die vier Token-Arten wie im Transkript. Ist die Ausgabe
    kein JSON, gilt sie als reiner Text - dann eben ohne Verbrauch.
    """
    try:
        daten = json.loads(ausgabe)
    except ValueError:
        return ausgabe.strip(), Verbrauch()
    if not isinstance(daten, dict):
        return ausgabe.strip(), Verbrauch()
    nutzung = daten.get("usage")
    verbrauch = Verbrauch()
    if isinstance(nutzung, dict):
        def zahl(schluessel: str) -> int:
            wert = nutzung.get(schluessel)
            return wert if isinstance(wert, int) else 0
        verbrauch = Verbrauch(
            neu=zahl("input_tokens") + zahl("cache_creation_input_tokens"),
            cache=zahl("cache_read_input_tokens"),
            aus=zahl("output_tokens"),
        )
    return str(daten.get("result") or "").strip(), verbrauch


def claude_einmal(auftrag: str, ordner: Path) -> tuple[str, str, Verbrauch]:
    """Ein einmaliger ``claude -p``-Aufruf ohne Fenster, ohne Bus und ohne eigenen Kontext.

    Der Auftrag geht ueber stdin, nicht als Argument: der Wrapper claude.cmd
    wuerde ihn sonst am ersten Zeilenumbruch abschneiden, wie es bei
    sanctuary.CMD geschehen ist. Hooks sind abgeschaltet, sonst vergaebe der
    Namens-Hook dem Einmal-Aufruf einen Namen aus dem Pool.

    :returns: ``(text, "", verbrauch)`` bei Erfolg, sonst ``("", grund, Verbrauch())``.
    """
    claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
    argumente, umgebung = ohne_kontext(ordner, hooks=False)
    befehl = [claude, "-p", *argumente, "--output-format", "json",
              "--disallowedTools", "WebSearch", "WebFetch", "Bash", "Read", "Write", "Edit"]
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
        return "", str(fehler), Verbrauch()
    if lauf.returncode != 0:
        grund = (lauf.stderr or lauf.stdout).strip()[:500] or f"Exit-Code {lauf.returncode}"
        return "", grund, Verbrauch()
    text, verbrauch = _json_antwort(lauf.stdout)
    return text, "", verbrauch


class Verbrauchszaehler:
    """Zaehlt die Tokens der Teilnehmer seit Beginn der Diskussion.

    Gemerkt wird je Sitzung die Groesse ihres Transkripts beim Eintritt,
    gezaehlt wird nur, was danach dazukam. Eine frisch gestartete Sitzung
    zaehlt ab Byte 0, ihr Anlauf gehoert ja zur Diskussion. Tut ein laufender
    Agent nebenher anderes, zaehlt das mit - die Zahl ist also eher zu hoch
    als zu niedrig.
    """

    def __init__(self, wurzel: Path | None = None) -> None:
        self._wurzel = wurzel
        self._versatz: dict[str, int] = {}

    def merken(self, sitzung: str, *, frisch: bool = False) -> None:
        if not sitzung or sitzung in self._versatz:
            return
        datei = claude_transkript(sitzung, self._wurzel)
        groesse = 0
        if datei is not None and not frisch:
            try:
                groesse = datei.stat().st_size
            except OSError:
                groesse = 0
        self._versatz[sitzung] = groesse

    def stand(self) -> Verbrauch:
        summe = Verbrauch()
        for sitzung, versatz in self._versatz.items():
            datei = claude_transkript(sitzung, self._wurzel)
            if datei is None:
                continue
            for a in claude_anfragen_ab(datei, versatz):
                summe = summe + Verbrauch(a.frisch + a.cache_neu, a.cache_gelesen, a.aus)
        return summe


def namen_zuordnen(wunsch: list[str], vergeben: list[str]) -> list[str]:
    """Ordnet den gestarteten Sitzungen ihre Plaetze zu.

    :param wunsch: je Start der gewuenschte Name, leer fuer "aus dem Pool".
    :param vergeben: die Namen, die tatsaechlich im Bestand auftauchten.
    :returns: je Start der vergebene Name, in der Reihenfolge von ``wunsch``.

    Wer seinen Wunschnamen bekommen hat, behaelt ihn. Die uebrigen Namen gehen
    der Reihe nach an die uebrigen Plaetze - auch an einen Wunsch, den der
    Pool nicht erfuellt hat, dann uebernimmt eben ein anderer Name die Rolle.
    """
    frei = list(vergeben)
    ergebnis = [""] * len(wunsch)
    for i, name in enumerate(wunsch):
        treffer = next((v for v in frei if name and v.lower() == name.lower()), None)
        if treffer is not None:
            ergebnis[i] = treffer
            frei.remove(treffer)
    for i in range(len(wunsch)):
        if not ergebnis[i] and frei:
            ergebnis[i] = frei.pop(0)
    return ergebnis


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
    wiederbeleben: list[Teilnehmer] | None = None,
    melden: Callable[[str], None] = lambda _text: None,
    beim_beitrag: Callable[[Beitrag], None] | None = None,
    beim_wort: Callable[[Teilnehmer, int], None] | None = None,
    beim_start: Callable[[Diskussion], None] | None = None,
    beim_verbrauch: Callable[[Verbrauch], None] | None = None,
    stopp: threading.Event | None = None,
    quelle: LokaleQuelle | None = None,
    archiv: Diskussionsarchiv | None = None,
    protokoll: Path | None = None,
    zaehler: Verbrauchszaehler | None = None,
) -> Ergebnis:
    """Fuehrt eine Diskussion aus, neu oder fortgesetzt. Blockiert, gehoert in einen Thread.

    :param diskussion: mit den laufenden Agenten als Teilnehmer, die frischen fehlen noch.
        Beim Fortsetzen steht das bisherige Protokoll schon darin und ``runden`` ist
        die neue Gesamtzahl.
    :param neu: je frische Sitzung ein Teilnehmer, dessen Name ein Platzhalter ist.
        Seite und Rolle werden auf die tatsaechlich vergebenen Namen uebertragen.
    :param ohne_eigenen_kontext: frische Sitzungen ohne eigene CLAUDE.md und Memory.
    :param wiederbeleben: Teilnehmer aus ``diskussion``, deren Sitzung nicht mehr
        laeuft. Sie werden unter ihrem Namen neu gestartet.
    :param melden: Fortschrittsmeldungen ausserhalb der Beitraege.
    :param beim_wort: siehe ``moderieren``.
    :param beim_start: bekommt die Diskussion, sobald alle Teilnehmer ihre Namen haben.
    :param beim_verbrauch: bekommt nach jedem Beitrag den Verbrauch der ganzen Diskussion.
    :param archiv: wohin gespeichert wird, None fuer das Archiv im Einstellungsordner.
    :param protokoll: die Markdown-Datei einer fortgesetzten Diskussion, sonst eine neue.
    """
    quelle = quelle or LokaleQuelle()
    stopp = stopp or threading.Event()
    archiv = archiv or Diskussionsarchiv()
    zaehler = zaehler or Verbrauchszaehler()
    wiederbeleben = wiederbeleben or []
    ordner = ablage()
    gestartet: list[str] = []
    basis = diskussion.verbrauch
    if not diskussion.beginn:
        diskussion.beginn = datetime.now().isoformat(timespec="seconds")
        diskussion.ohne_kontext = ohne_eigenen_kontext

    def sichern(protokoll_pfad: str = "") -> None:
        # Das Archiv darf die Diskussion nie aufhalten - ein Fehler wird gemeldet.
        try:
            archiv.speichern(diskussion, protokoll_pfad)
        except (sqlite3.Error, OSError) as fehler:
            melden(f"Archiv: {fehler}")

    def nach_beitrag(beitrag: Beitrag) -> None:
        diskussion.verbrauch = basis + zaehler.stand()
        sichern()
        if beim_beitrag is not None:
            beim_beitrag(beitrag)
        if beim_verbrauch is not None:
            beim_verbrauch(diskussion.verbrauch)

    try:
        wunsch = [t.name for t in wiederbeleben] + [""] * len(neu)
        if wunsch:
            vorher = set(laufende(quelle))
            # Ohne Vorbereitung braucht niemand die Websuche - beim Fortsetzen
            # steht sie schon im Protokoll.
            ohne_web = not diskussion.recherche or diskussion.gespielte_runden > 0
            for name in wunsch:
                argumente, umgebung = ohne_kontext(ordner) if ohne_eigenen_kontext else ([], {})
                if ohne_web:
                    # Bei frischen Sitzungen hart gesperrt, bei laufenden Agenten
                    # bleibt es bei der Bitte in der Anweisung.
                    argumente = [*argumente, "--disallowedTools", "WebSearch", "WebFetch"]
                fehler = starte_lokal(
                    name, verzeichnis=str(ordner), claude_argumente=argumente, umgebung=umgebung
                )
                if fehler:
                    return Ergebnis(diskussion, fehler=f"Start fehlgeschlagen: {fehler}")
            melden(f"{len(wunsch)} Sitzung(en) gestartet, warte auf die Namen ...")
            gestartet = warte_auf_neue(quelle, vorher, len(wunsch))
            if len(gestartet) < len(wunsch):
                return Ergebnis(diskussion, fehler=(
                    f"Nach {STARTFRIST:.0f} s erst {len(gestartet)} von {len(wunsch)} "
                    "Sitzungen im Bestand."
                ))
            # Kurz warten, damit Hook und Inbox-Socket stehen - aber abbrechbar.
            if stopp.wait(ANLAUF):
                diskussion.ende = "von Hand gestoppt"
                return Ergebnis(diskussion, fehler="Vor dem Start gestoppt.")
            zugeordnet = namen_zuordnen(wunsch, gestartet)
            for teilnehmer, name in zip(wiederbeleben, zugeordnet, strict=False):
                if name.lower() != teilnehmer.name.lower():
                    melden(f"{name} übernimmt für {teilnehmer.name}")
                    teilnehmer.name = name
            diskussion.teilnehmer = diskussion.teilnehmer + [
                Teilnehmer(name, t.rolle, t.seite)
                for name, t in zip(zugeordnet[len(wiederbeleben):], neu, strict=True)
            ]

        sitzungen = {n.lower(): s for s, n in laufende(quelle).items()}
        frisch = {n.lower() for n in gestartet}
        for teilnehmer in diskussion.teilnehmer:
            teilnehmer.sitzung = sitzungen.get(teilnehmer.name.lower(), teilnehmer.sitzung)
            zaehler.merken(teilnehmer.sitzung, frisch=teilnehmer.name.lower() in frisch)

        namen = ", ".join(t.name for t in diskussion.teilnehmer)
        melden(f'Diskussion: "{diskussion.thema}" mit {namen}')
        sichern()
        if beim_start is not None:
            beim_start(diskussion)
        moderieren(diskussion, BusKanal(quelle, rechner()), beim_beitrag=nach_beitrag,
                   beim_wort=beim_wort, stopp=stopp)
    finally:
        for meldung in aufraeumen(quelle, gestartet):
            melden(f"Nicht beendet: {meldung}")

    diskussion.verbrauch = basis + zaehler.stand()
    if any(b.art in ("beitrag", "schlusswort") for b in diskussion.beitraege):
        melden(ZUSAMMENFASSUNG_LAEUFT)
        extra = Verbrauch()

        def modell(auftrag: str) -> tuple[str, str]:
            nonlocal extra
            text, fehler, extra = claude_einmal(auftrag, ordner)
            return text, fehler

        grund = zusammenfassen(diskussion, modell)
        diskussion.verbrauch = diskussion.verbrauch + extra
        if grund:
            melden(f"Keine Zusammenfassung: {grund}")
    if beim_verbrauch is not None:
        beim_verbrauch(diskussion.verbrauch)

    datei = protokoll or ordner / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    datei.write_text(als_markdown(diskussion), encoding="utf-8", newline="\n")
    sichern(str(datei))
    return Ergebnis(diskussion, protokoll=datei)
