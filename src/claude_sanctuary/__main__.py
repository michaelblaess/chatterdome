"""Einstiegspunkt der Oberflaeche."""

from __future__ import annotations

import argparse
import sys

from claude_sanctuary import __version__
from claude_sanctuary.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, load_locale
from claude_sanctuary.kern.einstellungen import Einstellungen


def main() -> None:
    """Startet die Zentrale."""
    einstellungen = Einstellungen()
    werte = einstellungen.laden()
    gespeicherte_sprache = str(werte.get("language", DEFAULT_LANGUAGE))

    parser = argparse.ArgumentParser(
        prog="sanctuary-tui",
        description="Zentrale fuer mehrere gleichzeitig laufende Claude-Code-Instanzen",
    )
    parser.add_argument("--lang", default=gespeicherte_sprache, choices=SUPPORTED_LANGUAGES)
    parser.add_argument("--version", action="version", version=f"claude-sanctuary {__version__}")
    args = parser.parse_args()

    # Sprache VOR dem Import der App laden - sonst sind die Beschriftungen
    # der Bindings leer, die zur Klassendefinitionszeit entstehen.
    load_locale(args.lang)
    if args.lang != gespeicherte_sprache:
        einstellungen.speichern({"language": args.lang})

    from textual_widgets import reset_terminal_title, set_terminal_title

    from claude_sanctuary.tui.app import SanctuaryApp

    set_terminal_title(f"claude-sanctuary v{__version__}")
    try:
        SanctuaryApp().run()
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
