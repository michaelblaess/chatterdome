"""Eine Nachricht an alle Agenten auf einmal.

WARUM NICHT ueber den Rundruf des Bus: ``chatterdome send all`` legt EINEN
Auftrag ab, der bewusst nur auf dem eigenen Rechner gilt (siehe bus.mjs,
"Der Rundruf bleibt bewusst lokal"). Im Mesh-Betrieb bekaemen die Agenten der
anderen Rechner also nichts - genau der Fehler, der den Bus vor einem Tag
schon rechnerlokal gemacht hat.

Deshalb schickt dieser Dialog N einzelne Auftraege, je einen an einen Agenten,
jeweils mit dessen Rechner als ``--host``. Das ist nicht nur richtig, sondern
auch besser: jeder Auftrag hat eine eigene Kennung, taucht im Verlauf des
jeweiligen Agenten auf und wird einzeln quittiert.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static, TextArea

from chatterdome.i18n import t
from chatterdome.kern.modelle import Agent


class RundrufErgebnis:
    """Was der Dialog zurueckgibt: der Text und wer ihn bekommen soll."""

    def __init__(self, text: str, empfaenger: list[Agent]) -> None:
        self.text = text
        self.empfaenger = empfaenger


class RundrufScreen(ModalScreen[RundrufErgebnis | None]):
    """Mehrzeiliges Feld, ein Schalter, ein Knopf."""

    DEFAULT_CSS = """
    RundrufScreen {
        align: center middle;
    }
    RundrufScreen > Vertical {
        width: 80%;
        max-width: 100;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    RundrufScreen #rundruf-titel {
        text-style: bold;
        color: $accent;
    }
    RundrufScreen #rundruf-ziele {
        color: $text-muted;
        margin-bottom: 1;
    }
    RundrufScreen #rundruf-text {
        height: 10;
        border: round $surface-lighten-2;
    }
    RundrufScreen #rundruf-operator {
        margin-top: 1;
    }
    RundrufScreen #rundruf-knoepfe {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    RundrufScreen #rundruf-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "abbrechen", "ESC"),
        # Strg+Eingabe sendet. Die blosse Eingabetaste kann es nicht sein -
        # das Feld ist mehrzeilig, dort erzeugt sie einen Zeilenumbruch.
        Binding("ctrl+s", "senden", "senden", show=False),
    ]

    def __init__(self, agenten: list[Agent], reserviert: list[str], **kwargs: Any) -> None:
        """
        :param agenten: alle sichtbaren Agenten.
        :param reserviert: Namen aus dem Namenspool, die vorab vergeben sind -
            derzeit "Operator". Sie sind ueber den Schalter zuschaltbar.
        """
        super().__init__(**kwargs)
        self._alle = [a for a in agenten if not a.selbst]
        self._reserviert = {n.casefold() for n in reserviert}

    # -- Aufbau ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(t("broadcast.title"), id="rundruf-titel")
            yield Static(self._zielzeile(False), id="rundruf-ziele")
            yield TextArea(id="rundruf-text")
            yield Checkbox(t("broadcast.include_operator"), value=False, id="rundruf-operator")
            with Horizontal(id="rundruf-knoepfe"):
                yield Button(t("broadcast.send"), variant="primary", id="rundruf-senden")
                yield Button(t("common.btn_cancel"), id="rundruf-abbrechen")

    def on_mount(self) -> None:
        self.set_focus(self.query_one("#rundruf-text", TextArea))

    # -- Auswahl --------------------------------------------------------

    def _empfaenger(self, mit_operator: bool) -> list[Agent]:
        """Die Agenten, die den Text bekommen sollen."""
        if mit_operator:
            return list(self._alle)
        return [a for a in self._alle if a.name.casefold() not in self._reserviert]

    def _zielzeile(self, mit_operator: bool) -> str:
        """Beschreibt, wer angeschrieben wird - vor dem Absenden sichtbar."""
        ziele = self._empfaenger(mit_operator)
        if not ziele:
            return t("broadcast.nobody")
        namen = ", ".join(f"{a.name}@{a.rechner.upper()}" for a in ziele)
        return t("broadcast.targets", anzahl=len(ziele), namen=namen)

    @on(Checkbox.Changed, "#rundruf-operator")
    def _schalter(self, ereignis: Checkbox.Changed) -> None:
        self.query_one("#rundruf-ziele", Static).update(self._zielzeile(bool(ereignis.value)))

    # -- Abschluss ------------------------------------------------------

    @on(Button.Pressed, "#rundruf-senden")
    def _knopf_senden(self) -> None:
        self.action_senden()

    @on(Button.Pressed, "#rundruf-abbrechen")
    def _knopf_abbrechen(self) -> None:
        self.dismiss(None)

    def action_senden(self) -> None:
        text = self.query_one("#rundruf-text", TextArea).text.strip()
        if not text:
            self.notify(t("notify.no_text"), severity="warning")
            return
        ziele = self._empfaenger(self.query_one("#rundruf-operator", Checkbox).value)
        if not ziele:
            self.notify(t("broadcast.nobody"), severity="warning")
            return
        self.dismiss(RundrufErgebnis(text, ziele))

    def action_abbrechen(self) -> None:
        self.dismiss(None)
