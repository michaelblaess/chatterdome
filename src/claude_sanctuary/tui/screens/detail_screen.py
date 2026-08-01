"""Alles zu einem Agenten, was in der Tabelle keinen Platz hat."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from claude_sanctuary.i18n import format_datetime, t
from claude_sanctuary.kern.modelle import Agent, Ampel

# Dieselben festen Farben wie in der Tabelle - siehe dort.
AMPEL_TEXT = {
    Ampel.FREI: ("●", "bold #2ecc71", "state.free"),
    Ampel.BESCHAEFTIGT: ("●", "bold #f1c40f", "state.busy"),
    Ampel.WEG: ("●", "bold #e74c3c", "state.gone"),
}


def _dauer(ms: int) -> str:
    minuten = ms // 60_000
    if minuten < 60:
        return f"{minuten} min"
    return f"{minuten // 60} h {minuten % 60:02d} min"


def _zahl(wert: int) -> str:
    """Tausendertrennung mit Punkt, deutsche Schreibweise."""
    return f"{wert:,}".replace(",", ".")


class DetailScreen(ModalScreen[str | None]):
    """Detailansicht. Gibt eine Folgeaktion zurueck, oder None.

    Die Rueckgabe erlaubt es, aus dem Dialog heraus zu handeln - etwa
    ``senden`` oder ``stop``, ohne dass der Dialog die App kennen muss.
    """

    DEFAULT_CSS = """
    DetailScreen {
        align: center middle;
    }
    DetailScreen > Vertical {
        width: 90%;
        max-width: 100;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    DetailScreen #detail-titel {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    DetailScreen #detail-scroll {
        height: auto;
        max-height: 90%;
    }
    DetailScreen .detail-block {
        height: auto;
        margin-bottom: 1;
    }
    DetailScreen #detail-knoepfe {
        dock: bottom;
        height: 3;
        align: center middle;
    }
    DetailScreen #detail-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Schliessen"),
    ]

    def __init__(self, agent: Agent, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agent = agent

    def compose(self) -> ComposeResult:
        a = self._agent
        zeichen, stil, schluessel = AMPEL_TEXT[a.ampel]
        titel = Text()
        titel.append(f"{zeichen} ", style=stil)
        titel.append(a.name, style="bold")
        titel.append(f"  {a.rechner}", style="dim")
        titel.append(f"   {t(schluessel)}", style=stil)

        with Vertical():
            yield Static(titel, id="detail-titel")
            with VerticalScroll(id="detail-scroll"):
                yield Static(self._block_sitzung(), classes="detail-block")
                yield Static(self._block_rechner(), classes="detail-block")
                yield Static(self._block_arbeit(), classes="detail-block")
            with Horizontal(id="detail-knoepfe"):
                yield Button(t("detail.btn_send"), variant="primary", id="detail-senden")
                yield Button(t("detail.btn_copy"), variant="default", id="detail-kopieren")
                yield Button(t("common.btn_close"), variant="default", id="detail-zu")

    # -- Bloecke --------------------------------------------------------

    def _tabelle(self, titel: str, zeilen: list[tuple[str, Any]]) -> Table:
        tabelle = Table(
            show_header=False, box=None, padding=(0, 2, 0, 0), title=titel, title_justify="left"
        )
        tabelle.add_column(style="dim", no_wrap=True, min_width=18)
        tabelle.add_column(overflow="fold")
        for beschriftung, wert in zeilen:
            tabelle.add_row(beschriftung, wert if isinstance(wert, Text) else str(wert))
        return tabelle

    def _block_sitzung(self) -> Table:
        a = self._agent
        laufzeit = _dauer(a.laufzeit_ms)
        if a.fortgesetzt:
            laufzeit += f"   ({t('detail.conversation')}: {_dauer(a.gespraech_ms)})"
        return self._tabelle(
            t("detail.session"),
            [
                (t("detail.name"), a.name + (f"   {t('detail.self')}" if a.selbst else "")),
                (t("detail.pid"), a.pid if a.pid else "-"),
                (t("detail.session_id"), a.session_id or "-"),
                (t("detail.uptime"), laufzeit),
                (t("detail.model"), a.modell or "-"),
                (t("detail.claude"), a.version or "-"),
            ],
        )

    def _block_rechner(self) -> Table:
        a = self._agent
        return self._tabelle(
            t("detail.machine"),
            [
                (t("detail.host"), a.rechner),
                (t("detail.system"), a.system or "-"),
                (t("detail.dir"), a.cwd or "-"),
                (t("detail.reachable"), t("detail.yes") if a.erreichbar else t("detail.no")),
            ],
        )

    def _block_arbeit(self) -> Table:
        a = self._agent
        kontext = Text(_zahl(a.kontext))
        if a.kontext_kritisch:
            kontext.stylize("bold red")
            kontext.append(f"   {t('detail.context_critical')}", style="bold red")
        elif a.kontext_eng:
            kontext.stylize("yellow")
            kontext.append(f"   {t('detail.context_tight')}", style="yellow")
        if a.nach_compact:
            kontext.append(f"   {t('detail.after_compact')}", style="dim")

        return self._tabelle(
            t("detail.work"),
            [
                (t("detail.context"), kontext),
                (t("detail.tokens"), _zahl(a.tokens)),
                (t("detail.cache"), _zahl(a.cache_gelesen)),
                (t("detail.post"), str(a.post)),
                (t("detail.tool"), a.letztes_tool or "-"),
                (t("detail.last_seen"), format_datetime(a.letzte_zeit) if a.letzte_zeit else "-"),
                (t("detail.task"), a.aufgabe or "-"),
            ],
        )

    # -- Aktionen -------------------------------------------------------

    @on(Button.Pressed, "#detail-senden")
    def _senden(self) -> None:
        self.dismiss("senden")

    @on(Button.Pressed, "#detail-kopieren")
    def _kopieren(self) -> None:
        self.dismiss("kopieren")

    @on(Button.Pressed, "#detail-zu")
    def _zu(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
