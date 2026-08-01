"""Uebersicht der Kommandozeilenbefehle."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.table import Table
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from claude_sanctuary.i18n import t

BEFEHLE: list[tuple[str, str]] = [
    ("sanctuary status", "Tabelle aller Instanzen"),
    ("sanctuary status <Name>", "Detailansicht einer Instanz"),
    ("sanctuary status --mesh", "zusätzlich die anderen Rechner"),
    ("sanctuary status --json", "maschinenlesbar"),
    ("sanctuary watch [Sek]", "laufend neu zeichnen, mit --json als Strom"),
    ("sanctuary start [Name]", "neue Instanz mit Namen im Tab-Titel"),
    ("sanctuary stop <Name>", "Instanz beenden"),
    ("sanctuary werde-operator", "diese Sitzung übernimmt den Operator-Namen"),
    ("sanctuary names", "vergebene Namen"),
    ("sanctuary motiv [Pool]", "Namensmotive anzeigen oder umschalten"),
    ("sanctuary send <Name> \"Text\"", "Auftrag ablegen, --erwartet-quittung für Rückmeldung"),
    ("sanctuary auftraege [--json]", "Warteschlange, unabhängig vom Lesezeiger"),
    ("sanctuary verlauf <Name>", "Aufträge und Quittungen mit einem Agenten"),
    ("sanctuary read [--alle]", "neue Nachrichten holen"),
    ("sanctuary ack <id> <Code>", "quittieren: 200 erledigt, 202 angenommen, 409 steckt fest"),
    ("sanctuary offen", "Stand der eigenen Aufträge"),
    ("sanctuary doctor", "Bus prüfen"),
    ("sanctuary kosten", "was die Zustellung gekostet hat"),
]


class HilfeScreen(ModalScreen[None]):
    """Listet auf, was auch ohne Oberfläche geht."""

    DEFAULT_CSS = """
    HilfeScreen {
        align: center middle;
    }
    HilfeScreen > Vertical {
        width: 90%;
        max-width: 110;
        height: auto;
        max-height: 90%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    HilfeScreen #hilfe-titel {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    HilfeScreen #hilfe-scroll {
        height: auto;
        max-height: 90%;
    }
    HilfeScreen #hilfe-knoepfe {
        dock: bottom;
        height: 3;
        align: center middle;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Schliessen"),
        Binding("h,H", "close", "Schliessen", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(t("help.title"), id="hilfe-titel")
            with VerticalScroll(id="hilfe-scroll"):
                yield Static(t("help.intro"))
                yield Static(self._tabelle())
            with Horizontal(id="hilfe-knoepfe"):
                yield Button("Schließen (Esc)", variant="primary", id="hilfe-zu")

    @staticmethod
    def _tabelle() -> Table:
        tabelle = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        tabelle.add_column(style="bold cyan", no_wrap=True)
        tabelle.add_column(overflow="fold")
        for befehl, zweck in BEFEHLE:
            tabelle.add_row(befehl, zweck)
        return tabelle

    @on(Button.Pressed, "#hilfe-zu")
    def _zu(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
