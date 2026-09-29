"""Tests fuer die Zahlformatierung der Statusleiste."""

from __future__ import annotations

import pytest

from chatterdome.i18n import current_language, load_locale
from chatterdome.tui.widgets.status_zeile import _tokens


@pytest.fixture(autouse=True)
def _sprache_zuruecksetzen() -> object:
    """Stellt die Sprache nach jedem Test wieder her.

    load_locale() setzt globalen Zustand. Ohne das Zuruecksetzen liefe jeder
    nachfolgende Test in der zuletzt gesetzten Sprache - und zwar je nach
    Reihenfolge mal so, mal so.
    """
    vorher = current_language()
    yield
    load_locale(vorher)


class TestZahlformat:
    @pytest.mark.parametrize(
        ("wert", "erwartet"),
        [
            (0, "0"),
            (-5, "0"),
            (9_999, "9999"),
            (452_000, "452k"),
            (999_999, "1000k"),
        ],
    )
    def test_unter_einer_million(self, wert: int, erwartet: str) -> None:
        assert _tokens(wert) == erwartet

    def test_millionen_deutsch_mit_komma(self) -> None:
        """5275k war unlesbar - ab einer Million gehoert dort ein M hin."""
        load_locale("de")
        assert _tokens(5_275_000) == "5,3M"
        assert _tokens(1_000_000) == "1,0M"

    def test_millionen_englisch_mit_punkt(self) -> None:
        load_locale("en")
        assert _tokens(5_275_000) == "5.3M"
