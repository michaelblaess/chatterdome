"""Kurzbefehl fuer eine Diskussion zwischen Agenten.

    uv run python -m claude_sanctuary.debatte_cli "Ist Angular tot?"
        --mit "Agatha=pro" "Lucia=contra:Frontend-Architektin" --runden 3

    uv run python -m claude_sanctuary.debatte_cli "Ist Angular tot?" --neu pro contra

``--mit`` nimmt laufende Agenten. ``--neu`` startet je Angabe eine frische
Sitzung, deren Namen der SessionStart-Hook wie ueblich aus dem Pool vergibt,
und beendet sie am Ende wieder. Beides laesst sich kombinieren.

Eine Angabe ist ``pro``, ``contra``, eine davon mit Rolle (``pro:Rolle``),
nur eine Rolle oder "-" fuer nichts. Ohne Seite verteilt der Moderator PRO
und CONTRA abwechselnd.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from claude_sanctuary.kern.debatte import (
    FORMATE,
    SEITEN,
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


def _rechner() -> str:
    # Wie im Bus: COMPUTERNAME zuerst, weil node() Suffixe wie .local liefern kann.
    return (os.environ.get("COMPUTERNAME") or platform.node().split(".")[0]).upper()


def _haltung(text: str) -> tuple[str, str]:
    """Zerlegt ``pro``, ``contra:Rolle`` oder eine freie Rolle in (seite, rolle)."""
    kopf, _, rest = text.strip().partition(":")
    if kopf.strip().lower() in SEITEN:
        return kopf.strip().lower(), rest.strip()
    return "", "" if text.strip() == "-" else text.strip()


def _teilnehmer(eintraege: list[str]) -> list[Teilnehmer]:
    ergebnis = []
    for eintrag in eintraege:
        name, _, haltung = eintrag.partition("=")
        seite, rolle = _haltung(haltung)
        ergebnis.append(Teilnehmer(name.strip(), rolle, seite))
    return ergebnis


def _laufende(quelle: LokaleQuelle) -> dict[str, str]:
    """Laufende Agenten als Sitzungskennung auf Namen."""
    return {a.session_id: a.name for a in quelle.bestand().agenten if a.session_id}


def _warte_auf_neue(quelle: LokaleQuelle, vorher: set[str], anzahl: int) -> list[str]:
    """Wartet, bis ``anzahl`` neue Sitzungen im Bestand stehen. Liefert deren Namen.

    Die Namen vergibt der SessionStart-Hook. Welche Sitzung neu ist, verraet
    nur der Vergleich mit dem Stand vor dem Start.
    """
    ende = time.monotonic() + STARTFRIST
    neue: dict[str, str] = {}
    while len(neue) < anzahl and time.monotonic() < ende:
        neue = {s: n for s, n in _laufende(quelle).items() if s not in vorher}
        if len(neue) < anzahl:
            time.sleep(3)
    return list(neue.values())


def ohne_kontext(ablage: Path, *, hooks: bool = True) -> tuple[list[str], dict[str, str]]:
    """Claude-Argumente und Umgebung fuer eine Sitzung ohne CLAUDE.md und Memory.

    Nicht ``--bare``: das laesst auch alle Hooks weg (kein Name, kein Socket,
    also kein Bus) und liest kein OAuth. Stattdessen die drei dokumentierten
    Stellschrauben aus code.claude.com/docs/en/memory.md, jeweils einzeln
    abschaltbar. Die Einstellungen gehen als Datei hinein, weil JSON mit
    Anfuehrungszeichen den Weg durch die .cmd-Startdatei nicht heil uebersteht.
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
    datei = ablage / ("ohne-kontext.json" if hooks else "ohne-kontext-ohne-hooks.json")
    datei.write_text(json.dumps(einstellungen, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ["--settings", str(datei)], {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


ZUSAMMENFASSUNG_FRIST = 240.0
"""Sekunden fuer den einmaligen Aufruf, der die Diskussion zusammenfasst."""


def claude_einmal(auftrag: str, ablage: Path) -> tuple[str, str]:
    """Ein einmaliger ``claude -p``-Aufruf ohne Fenster, ohne Bus und ohne eigenen Kontext.

    Der Auftrag geht ueber stdin, nicht als Argument: der Wrapper claude.cmd
    wuerde ihn sonst am ersten Zeilenumbruch abschneiden, wie es bei
    sanctuary.CMD geschehen ist. Hooks sind abgeschaltet, sonst vergaebe der
    Namens-Hook dem Einmal-Aufruf einen Namen aus dem Pool.

    :returns: ``(text, "")`` bei Erfolg, sonst ``("", grund)``.
    """
    claude = os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude") or "claude"
    argumente, umgebung = ohne_kontext(ablage, hooks=False)
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
            cwd=str(ablage),
            timeout=ZUSAMMENFASSUNG_FRIST,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as fehler:
        return "", str(fehler)
    if lauf.returncode != 0:
        return "", (lauf.stderr or lauf.stdout).strip()[:500] or f"Exit-Code {lauf.returncode}"
    return lauf.stdout.strip(), ""


def _aufraeumen(quelle: LokaleQuelle, namen: list[str]) -> None:
    """Beendet die selbst gestarteten Sitzungen samt ihrem Fenster.

    Erst das ganze Fenster, weil ``stop`` allein unter Windows die
    Mausverfolgung eingeschaltet laesst, siehe ``kern.prozessbaum``. Findet
    sich die Startdatei nicht, bleibt ``stop`` als Rueckfall.
    """
    if not namen:
        return
    pids = {a.name.lower(): a.pid for a in quelle.bestand().agenten if a.pid}
    for name in namen:
        pid = pids.get(name.lower())
        grund = fenster_beenden(pid) if pid else "PID unbekannt"
        if not grund:
            continue
        fehler = quelle.stoppen(name)
        if fehler:
            print(f"{name} liess sich nicht beenden: {grund}; {fehler}", file=sys.stderr)


def _ausgeben(beitrag: Beitrag) -> None:
    koepfe = {"schlusswort": "Schlusswort", "vorbereitung": "Recherche",
              "beitrag": f"Runde {beitrag.runde}"}
    if beitrag.art in koepfe:
        kopf = koepfe[beitrag.art]
        print(f"\n[{beitrag.zeit}] {beitrag.name} ({kopf}):\n{beitrag.text}", flush=True)
        if beitrag.hinweis:
            print(f"  (Moderator: {beitrag.hinweis})", flush=True)
    else:
        print(f"\n[{beitrag.zeit}] {beitrag.name}: {beitrag.text}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diskussion zwischen Agenten, moderiert von Sanctuary."
    )
    parser.add_argument("thema")
    parser.add_argument("--mit", nargs="+", default=[], metavar="NAME[=ROLLE]",
                        help="laufende Agenten")
    parser.add_argument("--neu", nargs="+", default=[], metavar="SEITE[:ROLLE]",
                        help="je Angabe eine frische Sitzung, etwa: pro contra")
    parser.add_argument("--format", choices=sorted(FORMATE), default="diskussion")
    parser.add_argument("--runden", type=int, default=3)
    parser.add_argument("--dauer", type=float, default=0.0, help="Minuten, 0 = nur Runden")
    parser.add_argument("--recherche", action="store_true",
                        help="vor Runde 1 eine Vorbereitung mit Websuche")
    parser.add_argument("--ohne-kontext", action="store_true",
                        help="frische Sitzungen ohne eigene CLAUDE.md und ohne Memory")
    args = parser.parse_args(argv)

    rollen_neu = [_haltung(r) for r in args.neu]
    vorhandene = _teilnehmer(args.mit)
    # Vorab pruefen, bevor irgendein Fenster aufgeht. Die frischen Teilnehmer
    # stehen dafuer mit Platzhaltern drin, ihre Namen kennt noch niemand.
    diskussion = Diskussion(
        thema=args.thema,
        teilnehmer=vorhandene
        + [Teilnehmer(f"neu-{i}", r, s) for i, (s, r) in enumerate(rollen_neu)],
        format=args.format,
        runden=args.runden,
        dauer_minuten=args.dauer,
        recherche=args.recherche,
    )
    grund = diskussion.pruefen()
    if grund:
        print(grund, file=sys.stderr)
        return 2

    quelle = LokaleQuelle()
    rechner = _rechner()
    laufend = _laufende(quelle)
    bekannt = {n.lower() for n in laufend.values()}
    fehlen = [t.name for t in vorhandene if t.name.lower() not in bekannt]
    if fehlen:
        frei = ", ".join(sorted(laufend.values()))
        print(f"Laeuft nicht: {', '.join(fehlen)}. Laufende Agenten: {frei}", file=sys.stderr)
        return 2

    ablage = Path.home() / ".claude" / "bus" / rechner / "diskussionen"
    ablage.mkdir(parents=True, exist_ok=True)
    gestartet: list[str] = []

    try:
        if rollen_neu:
            for _ in rollen_neu:
                argumente, umgebung = ohne_kontext(ablage) if args.ohne_kontext else ([], {})
                if not args.recherche:
                    # Bei frischen Sitzungen hart gesperrt, bei laufenden Agenten
                    # bleibt es bei der Bitte in der Anweisung.
                    argumente = [*argumente, "--disallowedTools", "WebSearch", "WebFetch"]
                fehler = starte_lokal(
                    verzeichnis=str(ablage), claude_argumente=argumente, umgebung=umgebung
                )
                if fehler:
                    print(f"Start fehlgeschlagen: {fehler}", file=sys.stderr)
                    return 1
            print(f"{len(rollen_neu)} Sitzung(en) gestartet, warte auf die Namen ...", flush=True)
            gestartet = _warte_auf_neue(quelle, set(laufend), len(rollen_neu))
            if len(gestartet) < len(rollen_neu):
                print(
                    f"Nach {STARTFRIST:.0f} s erst {len(gestartet)} von {len(rollen_neu)} "
                    "Sitzungen im Bestand.",
                    file=sys.stderr,
                )
                return 1
            time.sleep(ANLAUF)
            neue = [
                Teilnehmer(n, r, s) for n, (s, r) in zip(gestartet, rollen_neu, strict=True)
            ]
            diskussion.teilnehmer = vorhandene + neue

        namen = ", ".join(t.name for t in diskussion.teilnehmer)
        print(f'\nDiskussion: "{diskussion.thema}" mit {namen}', flush=True)
        stopp = threading.Event()
        try:
            moderieren(diskussion, BusKanal(quelle, rechner), beim_beitrag=_ausgeben, stopp=stopp)
        except KeyboardInterrupt:
            diskussion.ende = "von Hand gestoppt (Strg+C)"
    finally:
        _aufraeumen(quelle, gestartet)

    if diskussion.beitraege:
        print("\nZusammenfassung wird erstellt ...", flush=True)
        grund = zusammenfassen(diskussion, lambda auftrag: claude_einmal(auftrag, ablage))
        if grund:
            print(f"Keine Zusammenfassung: {grund}", file=sys.stderr)
        else:
            print(f"\n{diskussion.zusammenfassung}", flush=True)

    datei = ablage / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    datei.write_text(als_markdown(diskussion), encoding="utf-8", newline="\n")
    print(f"\nEnde: {diskussion.ende}\nProtokoll: {datei}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
