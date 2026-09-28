"""Kennzahlen unter den Panels.

Der Aufbau kommt aus ``textual_widgets.StatusBar`` - Rahmen und Trenner sind
damit in allen Anwendungen gleich. Hier steht nur, WELCHE Zahlen erscheinen.
"""

from __future__ import annotations

from typing import Any

from rich.style import Style
from rich.text import Text
from textual_widgets import StatusBar, StatusItem
from textual_widgets.status_bar import TRENNER

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
        self._bus_posten: list[StatusItem] = []
        self._diskussion = False
        self._link: tuple[str, str] | None = None
        """Beschriftung und Klick-Aktion eines Links am Ende, nur im Diskussionsmodus."""

    def diskussion_zeigen(self, posten: list[StatusItem],
                          link: tuple[str, str] | None = None) -> None:
        """Zeigt die Kennzahlen einer Diskussion statt der des Bus.

        :param link: (Beschriftung, Aktion) - etwa das Protokoll, das per Klick aufgeht.
        """
        self._diskussion = True
        self._link = link
        self.set_items(posten)

    def diskussion_aus(self) -> None:
        """Zurueck zu den Bus-Kennzahlen."""
        if not self._diskussion:
            return
        self._diskussion = False
        self._link = None
        self.set_items(self._bus_posten)

    def _build(self) -> Text:
        text: Text = super()._build()
        if self._diskussion and self._link is not None:
            beschriftung, aktion = self._link
            text.append(TRENNER, style="dim")
            text.append(f"{t('discussion.stat_log')}: ", style="dim")
            text.append(beschriftung, style=Style(underline=True, bold=True)
                        + Style.from_meta({"@click": aktion}))
        return text

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
        self._bus_posten = posten
        # Im Reiter Diskussion steht deren Zeile - der Bus-Takt darf sie nicht
        # alle paar Sekunden ueberschreiben.
        if not self._diskussion:
            self.set_items(posten)
