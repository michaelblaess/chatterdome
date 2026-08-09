"""Darstellung des Auftragsverlaufs.

Michael hat am 09.08.2026 an einem Bildschirmfoto gezeigt, dass die Blasen
ohne Abstand aneinanderkleben. Die Basisregel setzte zwar ``margin: 0 0 1 0``,
aber die spezifischeren Regeln fuer ``eigen`` und ``fremd`` nur
``margin-left`` bzw. ``margin-right`` - und Textual fuehrt ``margin`` als EINE
Eigenschaft. Die spezifischere Regel ersetzte damit den ganzen Wert samt dem
unteren Abstand. Gemessen kam ``bottom=0`` heraus.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_sanctuary.kern.modelle import Auftrag, Ereignis
from claude_sanctuary.tui.app import SanctuaryApp
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel


def _auftrag() -> Auftrag:
    return Auftrag(
        auftrag_id="x",
        zustand="submitted",
        an="Petra",
        text="wie ist der freie RAM auf Senza?",
        verlauf=[
            Ereignis(
                art="auftrag",
                ts="2026-08-09T04:50:00",
                von="Sanctuary",
                host="RAINBOW",
                text="wie ist der freie RAM auf Senza?",
            ),
            Ereignis(
                art="quittung",
                ts="2026-08-09T04:51:00",
                von="Petra",
                host="SENZA",
                status=200,
                notiz="Senza: 21 GiB frei von 30 GiB",
            ),
        ],
    )


async def _blasen(panel: VerlaufPanel, pilot: Any) -> list[Any]:
    """Wartet, bis die Blasen wirklich haengen, und gibt sie zurueck.

    EIN ``pilot.pause()`` genuegt nicht. Lokal war der Test damit gruen, auf
    den langsameren Linux-Laeufern der CI kamen null Blasen heraus - mounten
    ist asynchron, und wie viele Durchlaeufe es braucht, haengt an der
    Maschine. Dasselbe Muster wie ``_gefuellt`` in test_app.py.
    """
    for _ in range(120):
        await pilot.pause()
        blasen = [k for k in panel.children if "blase" in k.classes]
        if len(blasen) >= 2:
            return blasen
    return [k for k in panel.children if "blase" in k.classes]


@pytest.mark.asyncio
class TestAbstandZwischenBlasen:
    async def test_jede_blase_hat_unten_abstand(self) -> None:
        """Sonst klebt die naechste Nachricht direkt an der vorigen."""
        app = SanctuaryApp()
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            assert len(blasen) == 2, "Auftrag und Quittung sollen zwei Blasen ergeben"
            for blase in blasen:
                klassen = " ".join(sorted(blase.classes))
                assert blase.styles.margin.bottom >= 1, f"{klassen} klebt an der naechsten"

    async def test_die_seitliche_einrueckung_bleibt_erhalten(self) -> None:
        """Sie unterscheidet eigene von fremden Nachrichten - beim Reparieren
        des unteren Abstands darf sie nicht verlorengehen."""
        app = SanctuaryApp()
        app._frage_disclaimer = lambda: None  # type: ignore[method-assign]
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one("#verlauf", VerlaufPanel)
            panel.zeigen("Petra@SENZA", [_auftrag()])
            blasen = await _blasen(panel, pilot)

            # Mit Vorgabewert statt blossem next(): ohne ihn wirft next() eine
            # StopIteration, und die wird in einer Koroutine zu einem
            # RuntimeError - der verdeckt, woran es wirklich lag.
            eigen = next((k for k in blasen if "eigen" in k.classes), None)
            fremd = next((k for k in blasen if "fremd" in k.classes), None)
            assert eigen is not None, "die eigene Blase fehlt"
            assert fremd is not None, "die fremde Blase fehlt"
            assert eigen.styles.margin.left > 0
            assert fremd.styles.margin.right > 0
