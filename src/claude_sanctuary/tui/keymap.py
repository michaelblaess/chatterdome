"""Tastenbelegung dieser Anwendung.

Die Mechanik (Stile, Vim-Ebene, eigene Belegungen, Pruefer) liegt in
``textual_widgets.keymap``. Hier steht nur, was diese Anwendung ausmacht: ihre
Aktionen im Bestandsstil, die F-Tasten ab F7, die Beschriftungen und die Bruecke
zu den Einstellungen. Vorbild ist jira-timesheet.

Die Schluessel sind die Aktionsnamen, nicht die Beschriftungen - ``t()`` laeuft
erst beim Binden.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textual_widgets.keymap import (
    COMMON_FUNCTION_KEYS,
    KeyBinding,
    KeymapStyle,
    ResolvedKeymap,
    default_style_for_platform,
    parse_overrides,
    resolve_keymap,
    sort_for_footer,
)

CLASSIC: dict[str, KeyBinding] = {
    "quit": KeyBinding(("q", "Q")),
    "refresh": KeyBinding(("f5",)),
    "show_settings": KeyBinding(("s", "S")),
    "toggle_log": KeyBinding(("l", "L")),
    "cycle_theme": KeyBinding(("t", "T")),
    "show_about": KeyBinding(("i", "I")),
    # "?" ist in Terminals die gelaeufige Taste fuer Hilfe und gilt in beiden
    # Stilen. "h" bleibt nur im Bestandsstil, in der Vim-Ebene ist es "links".
    "show_help": KeyBinding(("h", "H", "question_mark")),
    "start_agent": KeyBinding(("n", "N")),
    # Beenden bewusst auf DEL statt auf einen Buchstaben - destruktiv.
    "stop_agent": KeyBinding(("delete",)),
    "toggle_local": KeyBinding(("o", "O")),
    "show_usage": KeyBinding(("v", "V")),
    "broadcast": KeyBinding(("b", "B")),
    # "d" liegt bei den Details, und h/j/k/l/g verdeckt die Vim-Ebene - bleibt
    # "a" wie "argue". Waehrend einer Diskussion haelt dieselbe Taste sie an.
    "discussion": KeyBinding(("a", "A")),
    "restart_agent": KeyBinding(("r", "R")),
    "show_memory": KeyBinding(("m", "M")),
    # "s" liegt bei den Einstellungen - fuer die Volltextsuche bleibt "f".
    "show_search": KeyBinding(("f", "F")),
    # "b" liegt beim Rundruf und "n" beim Starten - fuer den Bus bleibt "u".
    "show_bus": KeyBinding(("u", "U")),
    # "s" liegt bei den Einstellungen, "t" beim Thema - bleibt "k" fuer Kennzahlen.
    "show_stats": KeyBinding(("k", "K")),
    # NICHT "screenshot": diesen Aktionsnamen belegt Textual selbst, dort
    # speichert er ein SVG der Oberflaeche. Hier geht es um ein Foto des
    # ganzen Bildschirms - zwei verschiedene Dinge.
    "bildschirmfoto": KeyBinding(("p", "P")),
    "focus_filter": KeyBinding(("slash",), show=False),
    # Neu mit der Umstellung: dasselbe wie Doppelklick und Kontextmenue.
    "show_details": KeyBinding(("d", "D")),
}
"""Der Bestandsstil. Bis auf ``show_details`` und ``?`` die Belegung von v0.2.0."""

APP_FUNCTION_KEYS: dict[str, KeyBinding] = {
    "show_help": KeyBinding(("question_mark",)),
    "show_bus": KeyBinding(("f7", "u", "U")),
    "show_stats": KeyBinding(("f8",)),
    "show_memory": KeyBinding(("f9", "m", "M")),
    "show_search": KeyBinding(("f10", "f", "F")),
}
"""Was diese Anwendung im F-Tasten-Stil selbst vergibt.

``f1`` bis ``f6`` kommen aus der gemeinsamen Konvention. Ab ``f7`` liegen die
vier Ansichten neben den Agenten - reine Ansichten, nichts Destruktives, damit
ein Vertipper auf der F-Reihe nichts anrichtet. Starten, Neustart und Beenden
bleiben bewusst auf Buchstaben bzw. DEL.

Drei Buchstaben fallen im F-Tasten-Stil weg, alle wegen der Vim-Ebene: ``l``
(Log, jetzt ``f4``/``alt+l``), ``h`` (Hilfe, jetzt ``?``) und ``k`` (Statistik,
jetzt ``f8``). Damit ist dieser Stil mit eingeschalteter Vim-Navigation frei
von verdeckten Tasten. ``f11`` und ``f12`` bleiben frei, viele Terminals nehmen
sie fuer Vollbild.
"""

FUNCTION_KEYS: dict[str, KeyBinding] = {**COMMON_FUNCTION_KEYS, **APP_FUNCTION_KEYS}
"""Die gemeinsame Konvention plus die Ergaenzungen dieser Anwendung."""

LABEL_KEYS: dict[str, str] = {
    "quit": "binding.quit",
    "refresh": "binding.refresh",
    "show_settings": "binding.settings",
    "toggle_log": "binding.log",
    "cycle_theme": "binding.theme",
    "show_about": "binding.about",
    "show_help": "binding.help",
    "start_agent": "binding.start",
    "stop_agent": "binding.stop",
    "toggle_local": "binding.local",
    "show_usage": "binding.usage",
    "broadcast": "binding.broadcast",
    "discussion": "binding.discussion",
    "restart_agent": "binding.restart",
    "show_memory": "binding.memory",
    "show_search": "binding.search",
    "show_bus": "binding.bus",
    "show_stats": "binding.stats",
    "bildschirmfoto": "binding.screenshot",
    "focus_filter": "binding.filter",
    "show_details": "binding.details",
}
"""Aktion auf den i18n-Schluessel ihrer Footer-Beschriftung."""

TOOLTIP_KEYS: dict[str, str] = {
    "quit": "tooltip.quit",
    "refresh": "tooltip.refresh",
    "show_settings": "tooltip.settings",
    "toggle_log": "tooltip.log",
    "cycle_theme": "tooltip.theme",
    "show_about": "tooltip.about",
    "show_help": "tooltip.help",
    "start_agent": "tooltip.start",
    "stop_agent": "tooltip.stop",
    "toggle_local": "tooltip.local",
    "show_usage": "tooltip.usage",
    "broadcast": "tooltip.broadcast",
    "discussion": "tooltip.discussion",
    "restart_agent": "tooltip.restart",
    "show_memory": "tooltip.memory",
    "show_search": "tooltip.search",
    "show_bus": "tooltip.bus",
    "show_stats": "tooltip.stats",
    "bildschirmfoto": "tooltip.screenshot",
    "focus_filter": "tooltip.filter",
    "show_details": "tooltip.details",
}
"""Aktion auf den i18n-Schluessel ihres Footer-Tooltips."""

STYLE_LABEL_KEYS: dict[KeymapStyle, str] = {
    KeymapStyle.CLASSIC: "keymap.style_classic",
    KeymapStyle.FUNCTION_KEYS: "keymap.style_function_keys",
}
"""Stil auf den i18n-Schluessel seines Namens - ausgeschrieben statt
zusammengesetzt, damit der Test auf unbenutzte Sprachschluessel sie findet."""

# Die Anzeige der Taste im Footer. Ohne das stuende dort "question_mark" statt "?".
KEY_DISPLAY: dict[str, str] = {
    "slash": "/",
    "delete": "DEL",
    "question_mark": "?",
    **{f"f{nummer}": f"F{nummer}" for nummer in range(1, 11)},
}


def key_display(key: str) -> str:
    """Uebersetzt einen Tastennamen in seine Anzeige.

    :param key: Der Tastenname, so wie Textual ihn kennt.
    :returns: Der Text fuer Footer und Hilfe.
    """
    return KEY_DISPLAY.get(key, key)


def style_from_settings(settings: Mapping[str, Any]) -> KeymapStyle:
    """Ermittelt den Stil aus den Einstellungen.

    Ein leerer oder unbekannter Wert heisst "nicht entschieden" - dann
    entscheidet die Plattform, damit eine frische Installation auf dem Mac nicht
    mit F-Tasten startet, die das Betriebssystem abfaengt.

    :param settings: Das geladene Einstellungsdokument.
    """
    gewaehlt = str(settings.get("keymap_style", "") or "").strip().lower()
    for stil in KeymapStyle:
        if gewaehlt == stil.value:
            return stil
    return default_style_for_platform()


def vim_from_settings(settings: Mapping[str, Any]) -> bool:
    """Ob die Vim-Ebene an den Tabellen haengen soll."""
    return bool(settings.get("keymap_vim", False))


def resolve(settings: Mapping[str, Any]) -> ResolvedKeymap:
    """Baut die fertige Belegung aus den Einstellungen.

    Im F-Tasten-Stil steht das Ergebnis in Footer-Reihenfolge, F1 zuerst. Im
    Bestandsstil wird nicht sortiert - dort haette nur ``refresh`` eine F-Taste,
    und die allein nach vorn zu ziehen aenderte die gewohnte Reihenfolge ohne
    Gewinn.

    :param settings: Das geladene Einstellungsdokument.
    :returns: Belegung samt Beanstandungen. Die gehoeren ins Log, nicht in einen
        Dialog - sie betreffen die Einstellungsdatei, nicht den laufenden Vorgang.
    """
    stil = style_from_settings(settings)
    overrides, probleme = parse_overrides(settings.get("keymap_custom"))
    ergebnis = resolve_keymap(
        stil,
        CLASSIC,
        function_keys=FUNCTION_KEYS,
        overrides=overrides,
        vim_navigation=vim_from_settings(settings),
    )
    bindings = (
        sort_for_footer(ergebnis.bindings)
        if stil is KeymapStyle.FUNCTION_KEYS
        else dict(ergebnis.bindings)
    )
    return ResolvedKeymap(bindings=bindings, problems=probleme + ergebnis.problems)


def key_hint(bindings: Mapping[str, KeyBinding], action: str) -> str:
    """Die Taste einer Aktion, so wie sie in einer Meldung stehen soll.

    Meldungen duerfen keine Taste fest eingebaut haben - sie haengt am Stil und
    an den eigenen Belegungen. In jira-timesheet nannten drei Texte eine Taste,
    die es laengst nicht mehr gab.

    :param bindings: Die aufgeloeste Belegung.
    :param action: Der Name der Aktion.
    :returns: Die erste Taste, einzelne Buchstaben gross. Leer, wenn die Aktion
        keine Taste hat - dann steht nichts da statt einer falschen Taste.
    """
    binding = bindings.get(action)
    if binding is None:
        return ""
    taste = key_display(binding.keys[0])
    return taste.upper() if len(taste) == 1 else taste
