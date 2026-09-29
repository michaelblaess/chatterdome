"""Rueckfrage vor einer nicht umkehrbaren Aktion."""

from __future__ import annotations

from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class BestaetigungScreen(ModalScreen[bool]):
    """Fragt nach und gibt True oder False zurueck."""

    DEFAULT_CSS = """
    BestaetigungScreen {
        align: center middle;
    }
    BestaetigungScreen > Vertical {
        width: auto;
        min-width: 46;
        max-width: 80;
        height: auto;
        background: $surface;
        border: thick $error;
        padding: 1 2;
    }
    BestaetigungScreen #frage-titel {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }
    BestaetigungScreen #frage-text {
        height: auto;
        margin-bottom: 1;
    }
    BestaetigungScreen #frage-knoepfe {
        height: 3;
        align: center middle;
    }
    BestaetigungScreen #frage-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "nein", "Abbrechen"),
    ]

    def __init__(self, *, titel: str, text: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._titel = titel
        self._text = text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._titel, id="frage-titel")
            yield Static(self._text, id="frage-text")
            with Horizontal(id="frage-knoepfe"):
                yield Button("Beenden", variant="error", id="frage-ja")
                yield Button("Abbrechen (Esc)", variant="default", id="frage-nein")

    @on(Button.Pressed, "#frage-ja")
    def _ja(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#frage-nein")
    def _nein(self) -> None:
        self.dismiss(False)

    def action_nein(self) -> None:
        self.dismiss(False)
