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
    ("sanctuary status", "cmd.status"),
    ("sanctuary status <Name>", "cmd.status_name"),
    ("sanctuary status --mesh", "cmd.status_mesh"),
    ("sanctuary status --json", "cmd.status_json"),
    ("sanctuary watch [Sek]", "cmd.watch"),
    ("sanctuary start [Name]", "cmd.start"),
    ("sanctuary stop <Name> [--force]", "cmd.stop"),
    ("sanctuary become-operator", "cmd.become_operator"),
    ("sanctuary names", "cmd.names"),
    ("sanctuary motif [Pool]", "cmd.motif"),
    ('sanctuary send <Name> "Text"', "cmd.send"),
    ("sanctuary tasks [--all]", "cmd.tasks"),
    ("sanctuary history <Name>", "cmd.history"),
    ("sanctuary read [--all]", "cmd.read"),
    ("sanctuary ack <id> <Code>", "cmd.ack"),
    ("sanctuary open", "cmd.open"),
    ("sanctuary doctor", "cmd.doctor"),
    ("sanctuary cost", "cmd.cost"),
    ("sanctuary shot [RECHNER]", "cmd.shot"),
    ("sanctuary update [RECHNER]", "cmd.update"),
]
"""Befehl und der Schluessel seiner Erklaerung.

Die Erklaerungen standen hier frueher woertlich auf Deutsch - in der
englischen Fassung war die halbe Hilfe damit deutsch. Der Befehl selbst
bleibt natuerlich, wie er ist.
"""


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
        Binding("escape", "close", "ESC"),
        Binding("h,H", "close", "ESC", show=False),
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
                yield Button(t("help.close"), variant="primary", id="hilfe-zu")

    @staticmethod
    def _tabelle() -> Table:
        tabelle = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        tabelle.add_column(style="bold cyan", no_wrap=True)
        tabelle.add_column(overflow="fold")
        for befehl, schluessel in BEFEHLE:
            tabelle.add_row(befehl, t(schluessel))
        return tabelle

    @on(Button.Pressed, "#hilfe-zu")
    def _zu(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
