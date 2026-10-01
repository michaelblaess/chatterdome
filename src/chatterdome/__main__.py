"""Einstiegspunkt der Oberflaeche."""

from __future__ import annotations

import argparse
import sys

from chatterdome import __version__
from chatterdome.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, load_locale
from chatterdome.kern import absturz, umgebung
from chatterdome.kern.einstellungen import Einstellungen, alten_ordner_uebernehmen


def soll_grafik_wecken(bild_modus: str, protokoll: str | None) -> bool:
    """Sagt, ob das Grafik-Backend vor dem Start geweckt werden soll.

    Ohne erkanntes Protokoll fragt das Wecken ein Terminal nach seiner
    Zellgroesse, das gar keine Grafik beherrscht. Die Abfrage laeuft in einen
    Timeout, und textual-image meldet das mit logger.warning(exc_info=...) -
    also mit vollem Traceback auf der Standardfehlerausgabe. Sichtbar wird der
    erst beim Beenden, weil Textual bis dahin den zweiten Bildschirmpuffer
    haelt, und sieht dort nach einem Absturz aus. Belegt am 14.08.2026 auf
    senza (gnome-terminal, TERM=xterm-256color, kein Sixel).

    :param bild_modus:
    Einstellung "bild_modus": auto, graphics oder halfblock.
    :param protokoll:
    Ergebnis von erkenne_protokoll(), also tgp, sixel oder None.
    :returns:
    True, wenn vorab_initialisieren() sinnvoll ist.
    """
    if bild_modus == "halfblock":
        return False
    # Auch bei erzwungenem "graphics" bringt das Wecken nichts, solange kein
    # Protokoll erkannt ist - die Widget-Klasse kaeme ohnehin nicht zustande.
    return protokoll is not None


def main() -> None:
    """Startet die Zentrale."""
    # Der Demo-Modus MUSS vor jedem Lesen von Einstellungen stehen - sonst
    # stammen Sprache und Thema schon aus dem echten Zuhause. Deshalb der
    # Blick in sys.argv, bevor argparse ueberhaupt gebaut ist.
    demo = "--demo" in sys.argv[1:]
    zuhause = umgebung.demo_aktivieren() if demo else None
    if not demo:
        alten_ordner_uebernehmen()
    einstellungen = Einstellungen()
    werte = einstellungen.laden()
    gespeicherte_sprache = str(werte.get("language", DEFAULT_LANGUAGE))

    parser = argparse.ArgumentParser(
        prog="chatterdome-tui",
        # Englisch, weil die Hilfe vor dem Laden der Sprache entsteht und der
        # Einzeiler aus dem README als Erstes hierher fuehrt.
        description="A control room for several Claude Code sessions running at the same time",
    )
    parser.add_argument(
        "--lang",
        default=gespeicherte_sprache,
        choices=SUPPORTED_LANGUAGES,
        help="Language of the interface",
    )
    parser.add_argument("--version", action="version", version=f"chatterdome {__version__}")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Made-up agents and data instead of the real ones, e.g. for screenshots",
    )
    args = parser.parse_args()

    # Sprache VOR dem Import der App laden - sonst sind die Beschriftungen
    # der Bindings leer, die zur Klassendefinitionszeit entstehen.
    load_locale(args.lang)
    if args.lang != gespeicherte_sprache:
        einstellungen.speichern({"language": args.lang})

    from textual_widgets import (
        erkenne_protokoll,
        reset_terminal_title,
        set_terminal_title,
        vorab_initialisieren,
    )

    from chatterdome.kern.protokolle import Quelle
    from chatterdome.tui.app import ChatterdomeApp

    quelle: Quelle | None = None
    if zuhause is not None:
        from chatterdome.kern.demo_daten import erzeugen
        from chatterdome.kern.demo_quelle import DemoQuelle

        erzeugen(zuhause, args.lang)
        quelle = DemoQuelle(args.lang)

    # MUSS vor App.run() stehen: textual-image fragt beim ersten Import die
    # Zellgroesse am Terminal ab. Passiert das erst waehrend der App, landet
    # die Antwort des Terminals als Zeichenmuell im Eingabefeld.
    #
    # Aber nur, wenn das Terminal ueberhaupt Grafik kann - sonst wartet die
    # Abfrage vergeblich und hinterlaesst einen Traceback, siehe
    # soll_grafik_wecken().
    if soll_grafik_wecken(str(werte.get("bild_modus", "auto")), erkenne_protokoll()):
        vorab_initialisieren()

    set_terminal_title(f"chatterdome v{__version__}{' (Demo)' if demo else ''}")
    # Die Klammer MUSS hier stehen und nicht in der App: nur so umschliesst
    # sie auch das Aufraeumen unten. Bleibt die Endzeile im Protokoll aus,
    # ist genau dieses finally nicht mehr gelaufen - dann war es kein
    # Python-Fehler, sondern ein harter Abbruch von aussen.
    absturz.beobachte(__version__)
    try:
        ChatterdomeApp(quelle=quelle).run()
    finally:
        reset_terminal_title()
        _maus_tracking_aus()


def _maus_tracking_aus() -> None:
    """Schaltet die Maus-Meldungen ab.

    Unter Windows laesst Textual die Modi gelegentlich aktiv - danach landet
    bei jeder Mausbewegung Steuerzeichen-Muell in der Shell.
    """
    if not sys.stdout.isatty():
        return
    sys.stdout.write("\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1015l")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
