"""Darstellung des Auftragsverlaufs.

Michael hat am 09.08.2026 an einem Bildschirmfoto gezeigt, dass die Blasen
ohne Abstand aneinanderkleben. Die Basisregel setzte zwar ``margin: 0 0 1 0``,
aber die spezifischeren Regeln fuer ``eigen`` und ``fremd`` nur
``margin-left`` bzw. ``margin-right`` - und Textual fuehrt ``margin`` als EINE
Eigenschaft. Die spezifischere Regel ersetzte damit den ganzen Wert samt dem
unteren Abstand. Gemessen kam ``bottom=0`` heraus.

GEPRUEFT WIRD IN EINER MINIMALEN APP, nicht in der echten. Der erste Anlauf
fuhr ``SanctuaryApp`` hoch und rief ``zeigen()`` von aussen auf - unter Windows
gruen, auf den Linux-Laeufern der CI kamen null Blasen heraus. Ursache ist kein
Timing, sondern ein Rennen: die App verwaltet dasselbe Panel selbst und leert
es beim naechsten Durchlauf wieder. Auch eine Warteschleife half deshalb nicht.
Hier haengt das Panel allein in einer App, die sonst nichts tut - dasselbe
Stylesheet, aber niemand raeumt dazwischen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.app import App, ComposeResult

import claude_sanctuary.tui as tui_paket
from claude_sanctuary.kern.modelle import Auftrag, Ereignis
from claude_sanctuary.tui.widgets.verlauf_panel import VerlaufPanel

TCSS = Path(tui_paket.__file__).parent / "app.tcss"


class NurVerlauf(App[None]):
    """Traegt nur das Verlaufspanel - und das echte Stylesheet."""

    CSS_PATH = TCSS

    def compose(self) -> ComposeResult:
        yield VerlaufPanel(id="verlauf")


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
    """Wartet, bis die Blasen haengen. Mounten ist asynchron."""
    for _ in range(60):
        await pilot.pause()
        blasen = [k for k in panel.children if "blase" in k.classes]
        if len(blasen) >= 2:
            return blasen
    return [k for k in panel.children if "blase" in k.classes]


@pytest.mark.asyncio
class TestAbstandZwischenBlasen:
    async def test_jede_blase_hat_unten_abstand(self) -> None:
        """Sonst klebt die naechste Nachricht direkt an der vorigen."""
        app = NurVerlauf()
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
        app = NurVerlauf()
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
