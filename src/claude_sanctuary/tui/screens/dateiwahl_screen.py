"""Eine Datei aus dem Dateibaum auswaehlen.

Bewusst im Terminal und nicht ueber den Dialog des Betriebssystems: die
Oberflaeche laeuft auch ueber ssh, und dort gibt es keinen Desktop, auf dem
sich ein Fenster oeffnen liesse. Ein GUI-Dialog wuerde in genau dem Fall
haengen, in dem man ihn am dringendsten braucht.

Die Eingabezeile bleibt gleichberechtigt neben dem Baum: wer den Pfad kennt,
tippt ihn schneller, als er ihn zusammenklickt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Static

from claude_sanctuary.i18n import t


class DateiwahlScreen(ModalScreen[str | None]):
    """Baum plus Eingabezeile. Gibt den gewaehlten Pfad zurueck."""

    DEFAULT_CSS = """
    DateiwahlScreen {
        align: center middle;
    }
    DateiwahlScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    DateiwahlScreen #wahl-titel {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    DateiwahlScreen #wahl-baum {
        height: 1fr;
        border: round $surface-lighten-2;
    }
    DateiwahlScreen #wahl-pfad {
        margin-top: 1;
    }
    DateiwahlScreen #wahl-knoepfe {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    DateiwahlScreen #wahl-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "abbrechen", "ESC"),
    ]

    def __init__(self, vorgabe: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._vorgabe = vorgabe
        self._wurzel = self._startordner(vorgabe)

    @staticmethod
    def _startordner(vorgabe: str) -> Path:
        """Der Ordner, in dem der Baum aufgeht.

        Bei einem vorhandenen Pfad dessen Verzeichnis, sonst das
        Benutzerverzeichnis - nie die Laufwerkswurzel, die waere nutzlos gross.
        """
        if vorgabe:
            kandidat = Path(vorgabe).expanduser()
            if kandidat.is_file():
                return kandidat.parent
            if kandidat.is_dir():
                return kandidat
        return Path.home()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(t("filepick.title"), id="wahl-titel")
            yield DirectoryTree(str(self._wurzel), id="wahl-baum")
            yield Input(value=self._vorgabe, placeholder=t("filepick.path"), id="wahl-pfad")
            with Horizontal(id="wahl-knoepfe"):
                yield Button(t("filepick.take"), variant="primary", id="wahl-ok")
                yield Button(t("common.btn_cancel"), id="wahl-abbrechen")

    @on(DirectoryTree.FileSelected)
    def _datei_gewaehlt(self, ereignis: DirectoryTree.FileSelected) -> None:
        # Nur ins Feld uebernehmen, nicht sofort schliessen: ein Klick im
        # Baum ist eine Auswahl, keine Bestaetigung.
        self.query_one("#wahl-pfad", Input).value = str(ereignis.path)

    @on(Input.Submitted, "#wahl-pfad")
    @on(Button.Pressed, "#wahl-ok")
    def _uebernehmen(self) -> None:
        pfad = self.query_one("#wahl-pfad", Input).value.strip()
        if not pfad:
            self.dismiss(None)
            return
        if not Path(pfad).expanduser().is_file():
            self.notify(t("filepick.missing"), severity="warning")
            return
        self.dismiss(str(Path(pfad).expanduser()))

    @on(Button.Pressed, "#wahl-abbrechen")
    def _abbrechen(self) -> None:
        self.dismiss(None)

    def action_abbrechen(self) -> None:
        self.dismiss(None)
