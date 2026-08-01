"""Bildschirmfoto eines Rechners anzeigen."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual_widgets import TerminalImage

from claude_sanctuary.i18n import t


def _groesse(bytes_: int) -> str:
    return f"{bytes_ / 1_048_576:.1f} MB".replace(".", ",")


class BildScreen(ModalScreen[str | None]):
    """Zeigt ein aufgenommenes Bildschirmfoto.

    Gibt ``"neu"`` zurueck, wenn erneut aufgenommen werden soll, sonst None.
    """

    DEFAULT_CSS = """
    BildScreen {
        align: center middle;
    }
    BildScreen > Vertical {
        width: 95%;
        height: 90%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    BildScreen #bild-titel {
        text-style: bold;
        color: $accent;
        height: 1;
    }
    BildScreen TerminalImage {
        height: 1fr;
    }
    BildScreen #bild-knoepfe {
        height: 3;
        align: center middle;
    }
    BildScreen #bild-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "close", "Schliessen"),
    ]

    def __init__(self, pfad: str, rechner: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pfad = pfad
        self._rechner = rechner

    def compose(self) -> ComposeResult:
        datei = Path(self._pfad)
        groesse = _groesse(datei.stat().st_size) if datei.exists() else "-"
        with Vertical():
            yield Static(
                t("shot.title", rechner=self._rechner, groesse=groesse), id="bild-titel"
            )
            yield TerminalImage(self._pfad, id="bild-anzeige")
            with Horizontal(id="bild-knoepfe"):
                yield Button(t("shot.again"), variant="primary", id="bild-neu")
                yield Button(t("shot.save"), variant="default", id="bild-kopieren")
                yield Button(t("common.btn_close"), variant="default", id="bild-zu")

    @on(Button.Pressed, "#bild-neu")
    def _neu(self) -> None:
        self.dismiss("neu")

    @on(Button.Pressed, "#bild-kopieren")
    def _kopieren(self) -> None:
        self.dismiss("kopieren")

    @on(Button.Pressed, "#bild-zu")
    def _zu(self) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
