"""Tests der umschaltbaren Tastenbelegung.

Die Mechanik selbst ist in textual-widgets geprueft. Hier steht, was diese
Anwendung ausmacht: dass die Bestandstabelle zur Anwendung passt, dass beide
Stile das Erwartete binden und dass die Hilfe zeigt, was wirklich gebunden ist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual_widgets.keymap import KeymapStyle, find_collisions, function_key_number

from chatterdome.tui import keymap
from chatterdome.tui.screens.hilfe_screen import _ist_grossschreibung, tastenzeilen
from chatterdome.tui.widgets.agenten_tabelle import AgentenDaten

SPRACHEN = Path(__file__).resolve().parents[1] / "src" / "chatterdome" / "locale"

ALTE_BELEGUNG: dict[str, tuple[str, ...]] = {
    "quit": ("q", "Q"),
    "refresh": ("f5",),
    "show_settings": ("s", "S"),
    "toggle_log": ("l", "L"),
    "cycle_theme": ("t", "T"),
    "show_about": ("i", "I"),
    "start_agent": ("n", "N"),
    "stop_agent": ("delete",),
    "toggle_local": ("o", "O"),
    "show_usage": ("v", "V"),
    "broadcast": ("b", "B"),
    "restart_agent": ("r", "R"),
    "show_memory": ("m", "M"),
    "show_search": ("f", "F"),
    "show_bus": ("u", "U"),
    "show_stats": ("k", "K"),
    "bildschirmfoto": ("p", "P"),
    "focus_filter": ("slash",),
}
"""Die Klassen-BINDINGS von v0.2.0, woertlich - nur refresh_now heisst jetzt refresh."""


def _mit(stil: str, **weitere: Any) -> dict[str, Any]:
    return {"keymap_style": stil, **weitere}


# --- Die Tabelle der Anwendung --------------------------------------------------


def test_bestandstabelle_ist_kollisionsfrei() -> None:
    assert find_collisions(keymap.CLASSIC) == ()


def test_jede_aktion_hat_beschriftung_und_tooltip() -> None:
    assert [a for a in keymap.CLASSIC if a not in keymap.LABEL_KEYS] == []
    assert [a for a in keymap.CLASSIC if a not in keymap.TOOLTIP_KEYS] == []


def test_keine_verwaiste_beschriftung() -> None:
    assert [a for a in keymap.LABEL_KEYS if a not in keymap.CLASSIC] == []
    assert [a for a in keymap.TOOLTIP_KEYS if a not in keymap.CLASSIC] == []


def test_jede_beschriftung_ist_uebersetzt() -> None:
    for sprache in ("de", "en"):
        texte = json.loads((SPRACHEN / f"{sprache}.json").read_text(encoding="utf-8"))
        schluessel = [*keymap.LABEL_KEYS.values(), *keymap.TOOLTIP_KEYS.values()]
        fehlend = [s for s in schluessel if s not in texte]
        assert fehlend == [], f"{sprache}: {fehlend}"


def test_jede_aktion_gibt_es_in_der_app() -> None:
    from chatterdome.tui.app import ChatterdomeApp

    # Eine Taste ohne action_-Methode tut schlicht nichts - ohne Fehler.
    ohne = [a for a in keymap.CLASSIC if not hasattr(ChatterdomeApp, f"action_{a}")]
    assert ohne == []


@pytest.mark.parametrize("stil", list(KeymapStyle))
def test_beide_stile_sind_kollisionsfrei(stil: KeymapStyle) -> None:
    ergebnis = keymap.resolve(_mit(stil.value))
    assert ergebnis.problems == (), [p.message for p in ergebnis.problems]


# --- Die Stile ------------------------------------------------------------------


def test_klassisch_laesst_alles_wie_bisher() -> None:
    bindings = keymap.resolve(_mit("classic")).bindings
    for action, tasten in ALTE_BELEGUNG.items():
        assert bindings[action].keys == tasten, action
    # Die Hilfe behaelt h vorn, "?" kommt nur dazu.
    assert bindings["show_help"].keys[:2] == ("h", "H")


def test_f_tasten_nehmen_nur_drei_buchstaben_weg() -> None:
    # Log, Hilfe und Statistik verlieren ihren Buchstaben, alle drei wegen vim.
    klassisch = keymap.resolve(_mit("classic")).bindings
    f_tasten = keymap.resolve(_mit("function_keys")).bindings
    verloren = {
        action: sorted(set(klassisch[action].keys) - set(f_tasten[action].keys))
        for action in klassisch
    }
    assert {a: k for a, k in verloren.items() if k} == {
        "toggle_log": ["L", "l"],
        "show_help": ["H", "h"],
        "show_stats": ["K", "k"],
    }


def test_f_tasten_stil_ist_mit_vim_sauber() -> None:
    ergebnis = keymap.resolve(_mit("function_keys", keymap_vim=True))
    assert ergebnis.problems == (), [p.message for p in ergebnis.problems]


def test_klassischer_stil_meldet_was_vim_verdeckt() -> None:
    ergebnis = keymap.resolve(_mit("classic", keymap_vim=True))
    assert {p.action for p in ergebnis.problems} == {"show_help", "toggle_log", "show_stats"}


def test_destruktives_bleibt_auf_buchstaben() -> None:
    # Ein Vertipper auf der F-Reihe soll nichts beenden oder neu starten.
    bindings = keymap.resolve(_mit("function_keys")).bindings
    for action in ("stop_agent", "restart_agent", "start_agent", "broadcast"):
        assert function_key_number(bindings[action]) is None, action


# --- F-Tasten und Footer-Reihenfolge --------------------------------------------


def test_f_reihe_ist_lueckenlos_von_1_bis_10() -> None:
    bindings = keymap.resolve(_mit("function_keys")).bindings
    nummern = sorted(n for b in bindings.values() if (n := function_key_number(b)) is not None)
    assert nummern == list(range(1, 11))


def test_f11_und_f12_bleiben_frei() -> None:
    bindings = keymap.resolve(_mit("function_keys")).bindings
    belegt = {key for b in bindings.values() for key in b.keys}
    assert not belegt & {"f11", "f12"}


def test_footer_beginnt_mit_den_f_tasten_in_der_richtigen_reihenfolge() -> None:
    bindings = keymap.resolve(_mit("function_keys")).bindings
    sichtbar = [keymap.key_display(b.keys[0]) for b in bindings.values() if b.show]
    # F3 fehlt bewusst - der Filter steht nicht im Footer.
    assert sichtbar[:9] == ["F1", "F2", "F4", "F5", "F6", "F7", "F8", "F9", "F10"]
    assert all(not e.startswith("F") for e in sichtbar[9:])


def test_klassischer_stil_behaelt_seine_reihenfolge() -> None:
    assert list(keymap.resolve(_mit("classic")).bindings) == list(keymap.CLASSIC)


# --- Einstellungen --------------------------------------------------------------


@pytest.mark.parametrize(
    ("plattform", "erwartet"),
    [("darwin", KeymapStyle.CLASSIC), ("win32", KeymapStyle.FUNCTION_KEYS)],
)
def test_leerer_stil_folgt_der_plattform(
    plattform: str, erwartet: KeymapStyle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("textual_widgets.keymap.sys.platform", plattform)
    assert keymap.style_from_settings({"keymap_style": ""}) is erwartet
    assert keymap.style_from_settings({}) is erwartet


def test_unbekannter_stil_faellt_nicht_um() -> None:
    assert keymap.style_from_settings({"keymap_style": "quatsch"}) in tuple(KeymapStyle)


def test_eigene_belegung_gewinnt() -> None:
    ergebnis = keymap.resolve(_mit("function_keys", keymap_custom={"toggle_log": ["alt+l"]}))
    assert ergebnis.bindings["toggle_log"].keys == ("alt+l",)
    assert ergebnis.problems == ()


def test_eigene_belegung_auf_unbekannte_aktion_wird_gemeldet() -> None:
    ergebnis = keymap.resolve(_mit("classic", keymap_custom={"gibtsnicht": ["z"]}))
    assert len(ergebnis.problems) == 1
    assert "gibtsnicht" in ergebnis.problems[0].message


def test_vorgaben_kennen_die_neuen_schluessel() -> None:
    from chatterdome.kern.einstellungen import VORGABEN

    assert VORGABEN["keymap_style"] == ""
    assert VORGABEN["keymap_vim"] is False
    assert VORGABEN["keymap_custom"] == {}


# --- Hilfe und Tastenhinweise ---------------------------------------------------


@pytest.mark.parametrize("stil", list(KeymapStyle))
def test_hilfe_zeigt_jede_aktion_mit_taste(stil: KeymapStyle) -> None:
    ergebnis = keymap.resolve(_mit(stil.value))
    zeilen = tastenzeilen(ergebnis)
    assert len(zeilen) == len(ergebnis.bindings)
    assert all(tasten for tasten, _ in zeilen), zeilen


def test_grossschreibung_wird_als_dublette_erkannt() -> None:
    assert _ist_grossschreibung("Q")
    assert not _ist_grossschreibung("q")
    assert not _ist_grossschreibung("f5")
    assert not _ist_grossschreibung("alt+l")


def test_tastenhinweis_folgt_dem_stil() -> None:
    def hinweis(stil: str, aktion: str) -> str:
        return keymap.key_hint(keymap.resolve(_mit(stil)).bindings, aktion)

    assert hinweis("classic", "show_memory") == "M"
    assert hinweis("function_keys", "show_memory") == "F9"
    assert hinweis("classic", "refresh") == "F5"
    assert hinweis("function_keys", "show_help") == "?"
    assert hinweis("classic", "gibtsnicht") == ""


class _TabellenApp(App[None]):
    """Kleinste App mit der Agententabelle, um die Vim-Ebene zu pruefen."""

    def __init__(self, vim: bool) -> None:
        super().__init__()
        self._vim = vim

    @property
    def vim_navigation(self) -> bool:
        return self._vim

    def compose(self) -> ComposeResult:
        yield AgentenDaten(id="probe")

    def on_mount(self) -> None:
        tabelle = self.query_one("#probe", AgentenDaten)
        tabelle.add_column("a")
        for zeile in ("eins", "zwei", "drei"):
            tabelle.add_row(zeile)
        tabelle.focus()


async def test_j_und_k_bewegen_den_zeiger_wenn_vim_an_ist() -> None:
    app = _TabellenApp(vim=True)
    async with app.run_test() as pilot:
        tabelle = app.query_one("#probe", AgentenDaten)
        assert tabelle.cursor_row == 0
        await pilot.press("j")
        await pilot.pause()
        assert tabelle.cursor_row == 1
        await pilot.press("k")
        await pilot.pause()
        assert tabelle.cursor_row == 0


async def test_j_tut_nichts_wenn_vim_aus_ist() -> None:
    # Gegenprobe: ohne den Schalter darf die Taste den Zeiger nicht bewegen.
    app = _TabellenApp(vim=False)
    async with app.run_test() as pilot:
        tabelle = app.query_one("#probe", AgentenDaten)
        await pilot.press("j")
        await pilot.pause()
        assert tabelle.cursor_row == 0


def test_keine_meldung_nennt_eine_taste_woertlich() -> None:
    """Hier stand "Taste m" - im F-Tasten-Stil liest F9 die Transkripte."""
    for sprache in ("de", "en"):
        texte = json.loads((SPRACHEN / f"{sprache}.json").read_text(encoding="utf-8"))
        assert "{shortcut}" in texte["mem.recall.none"], sprache
