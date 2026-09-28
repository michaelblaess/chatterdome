"""Dialog, der eine Diskussion zwischen Agenten einrichtet.

Thema, Format, Grenze nach Runden und Minuten, dazu die Teilnehmer: laufende
Agenten zum Ankreuzen und eine Anzahl frischer Sitzungen, deren Namen erst der
SessionStart-Hook vergibt. Welche Seite wer vertritt, zeigt die Vorschau -
verteilt wird wie im Moderator, sonst stuende im Dialog etwas anderes, als
spaeter passiert.

Der Knopf "Starten" ist gesperrt, solange etwas fehlt, und die Zeile darueber
nennt den Grund. Ein gesperrter Knopf ohne Grund schickt den Anwender im Kreis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.debatte import Diskussion, Teilnehmer
from claude_sanctuary.kern.modelle import Agent

MAX_NEU = 6
"""Mehr frische Fenster auf einmal braucht keine Diskussion, und jedes kostet."""


@dataclass
class DiskussionsAuftrag:
    """Was der Dialog zurueckgibt."""

    diskussion: Diskussion
    """Mit den laufenden Agenten als Teilnehmern."""
    neu: list[Teilnehmer] = field(default_factory=list)
    """Je frische Sitzung ein Platzhalter mit Seite, siehe ``debatte_ablauf.ausfuehren``."""
    ohne_kontext: bool = False


class DiskussionScreen(ModalScreen[DiskussionsAuftrag | None]):
    """Thema, Format, Grenzen, Teilnehmer und Schalter.

    Der Knopf "Starten" geht nur, wenn alles da ist.
    """

    DEFAULT_CSS = """
    DiskussionScreen {
        align: center middle;
    }
    DiskussionScreen > Vertical {
        width: 90%;
        max-width: 110;
        height: auto;
        max-height: 95%;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    DiskussionScreen #disk-titel {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    /* Einzeilige Felder (compact=True) im scrollenden Inhalt, die Knoepfe
       unten angedockt: auf kleinen Terminals scrollt der Inhalt, der Knopf
       "Starten" bleibt sichtbar. Gemessen: vorher lag er bei 120x40 unter
       der Kante. */
    DiskussionScreen #disk-inhalt {
        height: auto;
        max-height: 100%;
    }
    DiskussionScreen .disk-zeile {
        height: 1;
        margin-bottom: 1;
    }
    DiskussionScreen .disk-zeile Label {
        width: 16;
    }
    DiskussionScreen #disk-thema {
        width: 1fr;
    }
    DiskussionScreen #disk-format {
        width: 32;
    }
    DiskussionScreen .disk-zahl {
        width: 8;
    }
    DiskussionScreen .disk-einheit {
        width: auto;
        padding: 0 2 0 1;
        color: $text-muted;
    }
    DiskussionScreen #disk-agenten {
        height: auto;
        max-height: 6;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }
    DiskussionScreen #disk-keine {
        color: $text-muted;
    }
    DiskussionScreen #disk-vorschau {
        color: $text-muted;
        margin-top: 1;
    }
    DiskussionScreen #disk-grund {
        color: $warning;
    }
    DiskussionScreen #disk-knoepfe {
        dock: bottom;
        height: 3;
        align: center middle;
    }
    DiskussionScreen #disk-knoepfe Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "abbrechen", "ESC"),
        Binding("ctrl+s", "starten", "starten", show=False),
    ]

    def __init__(self, agenten: list[Agent], **kwargs: Any) -> None:
        """
        :param agenten: die sichtbaren Agenten. Die eigene Sitzung (``selbst``)
            steht nicht zur Wahl - sie wuerde mitten in ihrer Arbeit Auftraege bekommen.
        """
        super().__init__(**kwargs)
        self._agenten = [a for a in agenten if not a.selbst]

    # -- Aufbau ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(t("discussion.title"), id="disk-titel")
            # Die Knoepfe zuerst: angedockt stehen sie unten, egal wo sie im
            # Aufbau auftauchen, und der Inhalt darueber scrollt.
            with Horizontal(id="disk-knoepfe"):
                yield Button(t("discussion.start"), variant="primary", id="disk-starten")
                yield Button(t("common.btn_cancel"), id="disk-abbrechen")
            with VerticalScroll(id="disk-inhalt"):
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.topic"))
                    yield Input(placeholder=t("discussion.topic_placeholder"),
                                id="disk-thema", compact=True)
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.format"))
                    yield Select(
                        [(t("discussion.format_debate"), "diskussion"),
                         (t("discussion.format_team"), "team")],
                        value="diskussion", allow_blank=False, id="disk-format", compact=True,
                    )
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.limit"))
                    yield Input("3", type="integer", id="disk-runden", classes="disk-zahl",
                                compact=True)
                    yield Static(t("discussion.rounds"), classes="disk-einheit")
                    yield Input("0", type="number", id="disk-dauer", classes="disk-zahl",
                                compact=True)
                    yield Static(t("discussion.minutes"), classes="disk-einheit")
                yield Static(t("discussion.running_agents"))
                with VerticalScroll(id="disk-agenten"):
                    if not self._agenten:
                        yield Static(t("discussion.no_agents"), id="disk-keine")
                    for i, agent in enumerate(self._agenten):
                        yield Checkbox(
                            t("discussion.agent_entry", name=agent.name,
                              rechner=agent.rechner.upper(), status=agent.status),
                            value=False, id=f"disk-agent-{i}", compact=True,
                        )
                with Horizontal(classes="disk-zeile"):
                    yield Label(t("discussion.new_agents"))
                    yield Input("2" if not self._agenten else "0", type="integer",
                                id="disk-neu", classes="disk-zahl", compact=True)
                    yield Static(t("discussion.new_hint"), classes="disk-einheit")
                yield Checkbox(t("discussion.research"), value=False, id="disk-recherche",
                               compact=True)
                yield Checkbox(t("discussion.without_context"), value=True,
                               id="disk-ohne-kontext", compact=True)
                yield Static("", id="disk-vorschau")
                yield Static("", id="disk-grund")

    def on_mount(self) -> None:
        self.set_focus(self.query_one("#disk-thema", Input))
        self._pruefen()

    # -- Auswertung -----------------------------------------------------

    def _zahl(self, feld_id: str) -> float | None:
        """Der Wert eines Zahlenfelds, None wenn er fehlt oder unlesbar ist."""
        roh = self.query_one(f"#{feld_id}", Input).value.strip().replace(",", ".")
        try:
            return float(roh)
        except ValueError:
            return None

    def _gewaehlte(self) -> list[Agent]:
        return [a for i, a in enumerate(self._agenten)
                if self.query_one(f"#disk-agent-{i}", Checkbox).value]

    def _auftrag(self) -> tuple[DiskussionsAuftrag | None, str]:
        """Baut den Auftrag aus den Feldern, oder nennt den ersten Grund, warum nicht."""
        thema = self.query_one("#disk-thema", Input).value.strip()
        runden = self._zahl("disk-runden")
        dauer = self._zahl("disk-dauer")
        neu = self._zahl("disk-neu")
        if not thema:
            return None, t("discussion.missing_topic")
        if runden is None or runden < 1 or runden != int(runden):
            return None, t("discussion.bad_rounds")
        if dauer is None or dauer < 0:
            return None, t("discussion.bad_minutes")
        if neu is None or neu < 0 or neu != int(neu) or neu > MAX_NEU:
            return None, t("discussion.bad_new", maximum=MAX_NEU)
        gewaehlt = self._gewaehlte()
        if len(gewaehlt) + int(neu) < 2:
            return None, t("discussion.too_few")

        format_wert = self.query_one("#disk-format", Select).value
        diskussion = Diskussion(
            thema=thema,
            teilnehmer=[Teilnehmer(a.name) for a in gewaehlt],
            format=str(format_wert),
            runden=int(runden),
            dauer_minuten=float(dauer),
            recherche=self.query_one("#disk-recherche", Checkbox).value,
        )
        platzhalter = [Teilnehmer(t("discussion.new_placeholder", nummer=i + 1))
                       for i in range(int(neu))]
        # Seiten jetzt verteilen, in genau der Reihenfolge des Moderators: erst
        # die laufenden, dann die frischen. Die frischen behalten ihre Seite,
        # wenn sie spaeter ihren echten Namen bekommen.
        probe = Diskussion(thema=thema, teilnehmer=diskussion.teilnehmer + platzhalter,
                           format=diskussion.format, runden=diskussion.runden)
        probe.seiten_verteilen()
        grund = probe.pruefen()
        if grund:
            return None, grund
        anzahl = len(diskussion.teilnehmer)
        for teilnehmer, verteilt in zip(diskussion.teilnehmer, probe.teilnehmer, strict=False):
            teilnehmer.seite = verteilt.seite
        auftrag = DiskussionsAuftrag(
            diskussion=diskussion,
            neu=probe.teilnehmer[anzahl:],
            ohne_kontext=self.query_one("#disk-ohne-kontext", Checkbox).value,
        )
        return auftrag, ""

    def _vorschau(self, auftrag: DiskussionsAuftrag) -> str:
        alle = auftrag.diskussion.teilnehmer + auftrag.neu
        if auftrag.diskussion.format != "diskussion":
            return t("discussion.preview_team", namen=", ".join(t_.name for t_ in alle))
        pro = ", ".join(t_.name for t_ in alle if t_.seite == "pro")
        contra = ", ".join(t_.name for t_ in alle if t_.seite == "contra")
        return t("discussion.preview_sides", pro=pro, contra=contra)

    def _pruefen(self) -> None:
        """Vorschau, Grund und Knopf auf den aktuellen Stand bringen."""
        auftrag, grund = self._auftrag()
        self.query_one("#disk-vorschau", Static).update(
            self._vorschau(auftrag) if auftrag else ""
        )
        self.query_one("#disk-grund", Static).update(grund)
        self.query_one("#disk-starten", Button).disabled = auftrag is None
        # Ohne frische Sitzungen gibt es nichts, dem man den Kontext nehmen
        # koennte - laufende Agenten haben ihn laengst geladen.
        neu = self._zahl("disk-neu")
        self.query_one("#disk-ohne-kontext", Checkbox).disabled = not neu

    @on(Input.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed)
    def _geaendert(self) -> None:
        self._pruefen()

    # -- Abschluss ------------------------------------------------------

    @on(Button.Pressed, "#disk-starten")
    def _knopf_starten(self) -> None:
        self.action_starten()

    @on(Button.Pressed, "#disk-abbrechen")
    def _knopf_abbrechen(self) -> None:
        self.dismiss(None)

    def action_starten(self) -> None:
        auftrag, grund = self._auftrag()
        if auftrag is None:
            self.notify(grund, severity="warning", markup=False)
            return
        self.dismiss(auftrag)

    def action_abbrechen(self) -> None:
        self.dismiss(None)
