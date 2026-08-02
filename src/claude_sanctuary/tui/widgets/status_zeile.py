"""Kennzahlen unter den Panels.

Der Aufbau kommt aus ``textual_widgets.StatusBar`` - Rahmen und Trenner sind
damit in allen Anwendungen gleich. Hier steht nur, WELCHE Zahlen erscheinen.
"""

from __future__ import annotations

from typing import Any

from textual_widgets import StatusBar, StatusItem

from claude_sanctuary.i18n import current_language, t
from claude_sanctuary.kern.modelle import Bestand


def _tokens(wert: int) -> str:
    """Kuerzt grosse Zahlen lesbar ab.

    Ab einer Million auf "M" wechseln, sonst steht dort "5275k" - eine Zahl,
    die niemand auf einen Blick liest. Der Dezimaltrenner folgt der Sprache:
    im Deutschen das Komma, im Englischen der Punkt.
    """
    if wert <= 0:
        return "0"
    if wert < 10_000:
        return str(wert)
    if wert < 1_000_000:
        return f"{round(wert / 1000)}k"
    text = f"{wert / 1_000_000:.1f}M"
    return text.replace(".", ",") if current_language() == "de" else text


class StatusZeile(StatusBar):  # type: ignore[misc]
    """Agenten, Auslastung, offene Auftraege, Verbrauch."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(hint=t("status.empty"), **kwargs)

    def uebernehmen(self, bestand: Bestand, *, verbrauch: int | None = None) -> None:
        """Traegt die Kennzahlen einer Abfrage ein.

        :param verbrauch:
            Zuletzt ermittelter Verbrauch, oder None. Er steht nur in einer
            Abfrage mit --tokens und wird deshalb weitergereicht statt aus
            dem Bestand gelesen - dort waere er in jeder Taktabfrage 0.
        """
        rechner = len({a.rechner for a in bestand.agenten})
        posten = [
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
            # Kontext, NICHT Verbrauch: der belegte Kontext steht in jeder
            # Abfrage, die Token-Summe nur mit --tokens.
            StatusItem(t("status.context"), _tokens(bestand.kontext)),
        ]
        # Ohne --tokens ist die Summe 0. Eine Null anzuzeigen, die nur
        # "nicht ermittelt" heisst, behauptet etwas Falsches - dann lieber
        # gar keine Spalte.
        if verbrauch is not None:
            posten.append(StatusItem(t("status.tokens"), _tokens(verbrauch)))
        self.set_items(posten)
