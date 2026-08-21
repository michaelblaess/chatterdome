"""Die Warteanzeige fuer offene Auftraege.

Michaels Wunsch vom 21.08.2026, nachdem eine Antwort von Patsy 20 bis 30
Sekunden brauchte: man soll sehen, dass etwas passiert. Die Punkte haengen
bewusst am Zustand und nicht an einer Uhr - siehe Modulkopf von
``kern/warten.py``.
"""

from __future__ import annotations

import pytest

from claude_sanctuary.kern.warten import (
    OFFENE_ZUSTAENDE,
    PUNKTE_TAKTE,
    dauer_kurz,
    warteanzeige,
)


class TestNurBeiOffenenAuftraegen:
    @pytest.mark.parametrize("zustand", OFFENE_ZUSTAENDE)
    def test_offene_zustaende_bekommen_eine_anzeige(self, zustand: str) -> None:
        assert warteanzeige(zustand, 5, 0) is not None

    @pytest.mark.parametrize(
        "zustand", ["completed", "failed", "cancelled", "expired"]
    )
    def test_abgeschlossene_bekommen_keine(self, zustand: str) -> None:
        """Sonst liefen die Punkte neben einem Ergebnis, das laengst da ist."""
        assert warteanzeige(zustand, 5, 0) is None

    def test_ein_unbekannter_zustand_zeigt_nichts(self) -> None:
        # Fail-closed: lieber keine Anzeige als eine Animation fuer etwas,
        # das der Bus gar nicht als offen fuehrt.
        assert warteanzeige("quatsch", 5, 0) is None


class TestPunkte:
    def test_laufen_im_takt_durch(self) -> None:
        punkte = [warteanzeige("submitted", 5, i).punkte for i in range(PUNKTE_TAKTE)]  # type: ignore[union-attr]
        assert punkte == ["", ".", "..", "..."]

    def test_beginnen_danach_von_vorn(self) -> None:
        assert warteanzeige("submitted", 5, PUNKTE_TAKTE).punkte == ""  # type: ignore[union-attr]

    def test_hoeren_nach_der_frist_auf(self) -> None:
        """Punkte, die ewig laufen, sind schlimmer als gar keine."""
        anzeige = warteanzeige("submitted", 200, 1, frist=120)
        assert anzeige is not None
        assert anzeige.verstummt is True
        assert anzeige.punkte == ""

    def test_genau_auf_der_frist_ist_schluss(self) -> None:
        assert warteanzeige("submitted", 120, 1, frist=120).verstummt is True  # type: ignore[union-attr]

    def test_kurz_davor_laeuft_es_noch(self) -> None:
        assert warteanzeige("submitted", 119.9, 1, frist=120).verstummt is False  # type: ignore[union-attr]


class TestDauer:
    def test_zaehlt_die_sekunden_mit(self) -> None:
        assert warteanzeige("working", 7.8, 0).sekunden == 7  # type: ignore[union-attr]

    def test_eine_zeit_aus_der_zukunft_wird_nicht_negativ(self) -> None:
        """Im Mesh gehen die Uhren nicht gleich - "-3 s" waere Unsinn."""
        assert warteanzeige("working", -3, 0).sekunden == 0  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        ("sekunden", "erwartet"),
        [(0, "0:00"), (7, "0:07"), (59, "0:59"), (60, "1:00"), (134, "2:14")],
    )
    def test_formatierung(self, sekunden: int, erwartet: str) -> None:
        assert dauer_kurz(sekunden) == erwartet

    def test_negative_dauer_faellt_auf_null(self) -> None:
        assert dauer_kurz(-5) == "0:00"
