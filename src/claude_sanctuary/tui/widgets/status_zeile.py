"""Kennzahlen unter den Panels.

Der Aufbau kommt aus ``textual_widgets.StatusBar`` - Rahmen und Trenner sind
damit in allen Anwendungen gleich. Hier steht nur, WELCHE Zahlen erscheinen.
"""

from __future__ import annotations

from typing import Any

from textual_widgets import StatusBar, StatusItem

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.modelle import Bestand


def _tokens(wert: int) -> str:
    if wert <= 0:
        return "0"
    return str(wert) if wert < 10_000 else f"{round(wert / 1000)}k"


class StatusZeile(StatusBar):  # type: ignore[misc]
    """Agenten, Auslastung, offene Auftraege, Verbrauch."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(hint=t("status.empty"), **kwargs)

    def uebernehmen(self, bestand: Bestand) -> None:
        rechner = len({a.rechner for a in bestand.agenten})
        self.set_items(
            [
                StatusItem(t("status.agents"), str(len(bestand.agenten))),
                StatusItem(
                    t("status.busy"),
                    str(bestand.beschaeftigt),
                    value_style="bold yellow" if bestand.beschaeftigt else "bold",
                ),
                StatusItem(
                    t("status.open"),
                    str(bestand.offene_auftraege),
                    value_style="bold" if bestand.offene_auftraege else "dim",
                ),
                StatusItem(t("status.machines"), str(rechner)),
                # Kontext, NICHT Verbrauch: die Token-Summe liefert der Operator
                # nur mit --tokens (voller Transkript-Read), sonst ist sie 0 -
                # eine Null anzuzeigen, die nichts bedeutet, ist schlechter
                # als die Zahl wegzulassen.
                StatusItem(t("status.context"), _tokens(bestand.kontext)),
            ]
        )
