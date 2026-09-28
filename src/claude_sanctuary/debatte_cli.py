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

Der Ablauf selbst steht in ``debatte_ablauf``, die Oberflaeche benutzt ihn ebenso.
"""

from __future__ import annotations

import argparse
import sys
import threading

from claude_sanctuary.debatte_ablauf import ausfuehren, laufende
from claude_sanctuary.kern.debatte import FORMATE, SEITEN, Beitrag, Diskussion, Teilnehmer
from claude_sanctuary.kern.lokale_quelle import LokaleQuelle


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
    parser.add_argument("--positionen", nargs=2, default=["", ""], metavar=("PRO", "CONTRA"),
                        help='benannte Positionen, etwa: --positionen Unity Godot')
    parser.add_argument("--schlussworte", action="store_true",
                        help="eine Schlussrunde (Vorgabe aus)")
    parser.add_argument("--recherche", action="store_true",
                        help="vor Runde 1 eine Vorbereitung mit Websuche")
    parser.add_argument("--ohne-kontext", action="store_true",
                        help="frische Sitzungen ohne eigene CLAUDE.md und ohne Memory")
    args = parser.parse_args(argv)

    neu = [Teilnehmer(f"neu-{i}", r, s)
           for i, (s, r) in enumerate(_haltung(h) for h in args.neu)]
    vorhandene = _teilnehmer(args.mit)
    diskussion = Diskussion(
        thema=args.thema,
        teilnehmer=vorhandene,
        format=args.format,
        runden=args.runden,
        dauer_minuten=args.dauer,
        recherche=args.recherche,
        positionen=(args.positionen[0], args.positionen[1]),
        schlussworte=args.schlussworte,
    )
    # Vorab pruefen, bevor irgendein Fenster aufgeht - mit Platzhaltern fuer
    # die frischen Teilnehmer, deren Namen noch niemand kennt.
    grund = Diskussion(thema=args.thema, teilnehmer=vorhandene + neu, format=args.format,
                       runden=args.runden).pruefen()
    if grund:
        print(grund, file=sys.stderr)
        return 2

    quelle = LokaleQuelle()
    bekannt = {n.lower() for n in laufende(quelle).values()}
    fehlen = [t.name for t in vorhandene if t.name.lower() not in bekannt]
    if fehlen:
        frei = ", ".join(sorted(laufende(quelle).values()))
        print(f"Laeuft nicht: {', '.join(fehlen)}. Laufende Agenten: {frei}", file=sys.stderr)
        return 2

    stopp = threading.Event()
    try:
        ergebnis = ausfuehren(
            diskussion, neu, ohne_eigenen_kontext=args.ohne_kontext,
            melden=lambda text: print(f"\n{text}", flush=True),
            beim_beitrag=_ausgeben, stopp=stopp, quelle=quelle,
        )
    except KeyboardInterrupt:
        stopp.set()
        print("\nAbgebrochen (Strg+C).", file=sys.stderr)
        return 1
    if ergebnis.fehler:
        print(ergebnis.fehler, file=sys.stderr)
        return 1
    if diskussion.zusammenfassung:
        print(f"\n{diskussion.zusammenfassung}", flush=True)
    print(f"\nEnde: {diskussion.ende}\nProtokoll: {ergebnis.protokoll}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
