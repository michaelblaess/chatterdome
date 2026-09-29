"""Hilfe: die geltende Tastenbelegung und die Kommandozeilenbefehle."""

from __future__ import annotations

from typing import Any, ClassVar

from rich.table import Table
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static
from textual_widgets.keymap import KeymapStyle, ResolvedKeymap

from chatterdome.i18n import t
from chatterdome.tui import keymap

BEFEHLE: list[tuple[str, str]] = [
    ("chatterdome status", "cmd.status"),
    ("chatterdome status <Name>", "cmd.status_name"),
    ("chatterdome status --mesh", "cmd.status_mesh"),
    ("chatterdome status --json", "cmd.status_json"),
    ("chatterdome watch [Sek]", "cmd.watch"),
    ("chatterdome start [Name]", "cmd.start"),
    ("chatterdome stop <Name> [--force]", "cmd.stop"),
    ("chatterdome become-operator", "cmd.become_operator"),
    ("chatterdome names", "cmd.names"),
    ("chatterdome motif [Pool]", "cmd.motif"),
    ('chatterdome send <Name> "Text"', "cmd.send"),
    ("chatterdome tasks [--all]", "cmd.tasks"),
    ("chatterdome history <Name>", "cmd.history"),
    ("chatterdome read [--all]", "cmd.read"),
    ("chatterdome ack <id> <Code>", "cmd.ack"),
    ("chatterdome open", "cmd.open"),
    ("chatterdome doctor", "cmd.doctor"),
    ("chatterdome cost", "cmd.cost"),
    ("chatterdome shot [RECHNER]", "cmd.shot"),
    ("chatterdome update [RECHNER]", "cmd.update"),
]
"""Befehl und der Schluessel seiner Erklaerung.

Die Erklaerungen standen hier frueher woertlich auf Deutsch - in der
englischen Fassung war die halbe Hilfe damit deutsch. Der Befehl selbst
bleibt natuerlich, wie er ist.
"""


def _ist_grossschreibung(key: str) -> bool:
    """Ob eine Taste nur die Grossschreibung einer anderen ist.

    Die Belegung fuehrt Buchstaben doppelt (``q`` und ``Q``), damit sie
    unabhaengig von der Umschalttaste wirken. In der Hilfe waere das Rauschen.
    """
    return len(key) == 1 and key.isupper()


def tastenzeilen(belegung: ResolvedKeymap) -> list[tuple[str, str]]:
    """Taste und Beschriftung je Aktion, so wie die Hilfe sie zeigt.

    Gelesen wird die fertige Belegung, keine gepflegte Liste daneben - so zeigt
    die Hilfe zwangslaeufig das, was die Anwendung tatsaechlich gebunden hat.
    """
    zeilen: list[tuple[str, str]] = []
    for action, binding in belegung.bindings.items():
        tasten = " / ".join(
            keymap.key_display(key) for key in binding.keys if not _ist_grossschreibung(key)
        )
        beschriftung = t(keymap.LABEL_KEYS.get(action, action))
        if not binding.show:
            beschriftung = f"{beschriftung}  ({t('keymap.hidden')})"
        zeilen.append((tasten, beschriftung))
    return zeilen


class HilfeScreen(ModalScreen[None]):
    """Zeigt, welche Taste was tut, und was auch ohne Oberfläche geht."""

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
    HilfeScreen .hilfe-abschnitt {
        text-style: bold;
        margin-top: 1;
    }
    HilfeScreen #hilfe-modus {
        color: $text-muted;
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
        Binding("h,H,question_mark", "close", "ESC", show=False),
    ]

    def __init__(
        self,
        belegung: ResolvedKeymap | None = None,
        stil: KeymapStyle | None = None,
        vim: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._belegung = belegung
        self._stil = stil
        self._vim = vim

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(t("help.title"), id="hilfe-titel")
            with VerticalScroll(id="hilfe-scroll"):
                if self._belegung is not None:
                    yield Static(t("help.keys_title"), classes="hilfe-abschnitt")
                    yield Static(self._modus(), id="hilfe-modus")
                    yield Static(self._tastentabelle(self._belegung))
                    yield Static(t("help.commands_title"), classes="hilfe-abschnitt")
                yield Static(t("help.intro"))
                yield Static(self._tabelle())
            with Horizontal(id="hilfe-knoepfe"):
                yield Button(t("help.close"), variant="primary", id="hilfe-zu")

    def _modus(self) -> str:
        vim = t("keymap.vim_on") if self._vim else t("keymap.vim_off")
        if self._stil is None:
            return vim
        return f"{t(keymap.STYLE_LABEL_KEYS[self._stil])} - {vim}"

    @staticmethod
    def _tastentabelle(belegung: ResolvedKeymap) -> Table:
        tabelle = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        tabelle.add_column(style="bold cyan", no_wrap=True)
        tabelle.add_column(overflow="fold")
        for tasten, beschriftung in tastenzeilen(belegung):
            tabelle.add_row(tasten, beschriftung)
        return tabelle

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
