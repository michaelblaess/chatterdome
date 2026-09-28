"""Der Reiter "Diskussion": Formular zum Einrichten, danach der Chat.

Ohne laufende Diskussion steht hier das Formular, mit ihr der Verlauf wie im
Messenger - PRO links, CONTRA rechts, von oben nach unten zu lesen. Die neutrale
Zusammenfassung steht UNTER dem Chat und nie darin (Michael, 28.09.2026: "keine
Zusammenfassungen im Chat, sondern wirklich eine Diskussion").

Das Panel startet nichts selbst. Es meldet ``Starten`` und ``Anhalten`` an die
App, die den Ablauf in einem Worker fuehrt und die Ereignisse zurueckreicht.
Vorher stand das Formular in einem modalen Dialog hinter der Taste a.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.debatte import CONTRA, PRO, Beitrag, Diskussion, Teilnehmer
from claude_sanctuary.kern.modelle import Agent

MAX_NEU = 6
"""Mehr frische Fenster auf einmal braucht keine Diskussion, und jedes kostet."""

AUTO = "auto"
"""Wert der Seitenauswahl, wenn der Moderator verteilen soll."""


@dataclass
class DiskussionsAuftrag:
    """Was das Formular an die App gibt."""

    diskussion: Diskussion
    """Mit den laufenden Agenten als Teilnehmern."""
    neu: list[Teilnehmer] = field(default_factory=list)
    """Je frische Sitzung ein Platzhalter mit Seite, siehe ``debatte_ablauf.ausfuehren``."""
    ohne_kontext: bool = False


class _AgentZeile(Horizontal):
    """Ein laufender Agent zum Ankreuzen, daneben seine Seite."""

    def __init__(self, agent: Agent, angekreuzt: bool, seite: str, **kwargs: Any) -> None:
        super().__init__(classes="disk-agent-zeile", **kwargs)
        self.agent = agent
        self._angekreuzt = angekreuzt
        self._seite = seite

    def compose(self) -> ComposeResult:
        yield Checkbox(
            t("discussion.agent_entry", name=self.agent.name,
              rechner=self.agent.rechner.upper(), status=self.agent.status),
            value=self._angekreuzt, compact=True, classes="disk-agent-haken",
        )
        yield Select([(t("discussion.side_auto"), AUTO), ("PRO", PRO), ("CONTRA", CONTRA)],
                     value=self._seite, allow_blank=False, compact=True,
                     classes="disk-agent-seite")

    @property
    def angekreuzt(self) -> bool:
        return self.query_one(".disk-agent-haken", Checkbox).value

    @property
    def seite(self) -> str:
        return str(self.query_one(".disk-agent-seite", Select).value)


class DiskussionsPanel(Vertical):
    """Formular und Chat einer Diskussion."""

    DEFAULT_CSS = """
    DiskussionsPanel {
        height: 1fr;
    }
    DiskussionsPanel #disk-formular {
        height: 1fr;
        padding: 1 2;
    }
    DiskussionsPanel .disk-zeile {
        height: 1;
        margin-bottom: 1;
    }
    DiskussionsPanel .disk-zeile Label {
        width: 18;
    }
    DiskussionsPanel #disk-thema {
        width: 1fr;
    }
    DiskussionsPanel .disk-position {
        width: 1fr;
        margin-right: 2;
    }
    DiskussionsPanel #disk-format {
        width: 32;
    }
    DiskussionsPanel .disk-zahl {
        width: 8;
    }
    DiskussionsPanel .disk-einheit {
        width: auto;
        padding: 0 2 0 1;
        color: $text-muted;
    }
    DiskussionsPanel #disk-agenten {
        height: auto;
        max-height: 8;
        border: round $surface-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }
    DiskussionsPanel .disk-agent-zeile {
        height: 1;
    }
    DiskussionsPanel .disk-agent-haken {
        width: 1fr;
    }
    DiskussionsPanel .disk-agent-seite {
        width: 20;
    }
    DiskussionsPanel .disk-leise {
        color: $text-muted;
    }
    DiskussionsPanel #disk-grund {
        color: $warning;
    }
    DiskussionsPanel .disk-knoepfe {
        height: 3;
        align: left middle;
    }
    DiskussionsPanel .disk-knoepfe Button {
        margin: 0 2 0 0;
    }

    /* -- Chat -- */
    DiskussionsPanel #disk-chat-raum {
        display: none;
        height: 1fr;
    }
    DiskussionsPanel.laeuft #disk-formular,
    DiskussionsPanel.fertig #disk-formular {
        display: none;
    }
    DiskussionsPanel.laeuft #disk-chat-raum,
    DiskussionsPanel.fertig #disk-chat-raum {
        display: block;
    }
    DiskussionsPanel #disk-kopf {
        height: auto;
        padding: 0 2;
        border-bottom: solid $surface-lighten-2;
    }
    DiskussionsPanel #disk-steuerung {
        height: 3;
        padding: 0 2;
    }
    DiskussionsPanel #disk-steuerung Button {
        margin: 0 2 0 0;
    }
    DiskussionsPanel #disk-chat {
        height: 1fr;
        padding: 1 2;
    }
    /* Der Abstand steht in JEDER Regel vollstaendig: Textual fuehrt margin
       als eine Eigenschaft, eine Langform in der spezifischeren Regel wuerde
       den unteren Abstand der Basisregel loeschen (belegt am 09.08.2026). */
    DiskussionsPanel .disk-blase {
        height: auto;
        padding: 0 1;
        background: $panel;
        margin: 0 16 1 0;
    }
    DiskussionsPanel .disk-blase.disk-pro {
        border-left: thick $primary;
        margin: 0 16 1 0;
    }
    DiskussionsPanel .disk-blase.disk-contra {
        border-right: thick $accent;
        margin: 0 0 1 16;
    }
    DiskussionsPanel .disk-blase.disk-team {
        border-left: thick $secondary;
        margin: 0 8 1 0;
    }
    DiskussionsPanel .disk-meldung {
        height: auto;
        color: $text-muted;
        text-style: italic;
        content-align: center middle;
        width: 1fr;
        margin: 0 0 1 0;
    }
    DiskussionsPanel #disk-zusammenfassung-raum {
        display: none;
        height: auto;
        max-height: 12;
        border-top: solid $surface-lighten-2;
        padding: 0 2;
    }
    DiskussionsPanel #disk-zusammenfassung-raum.da {
        display: block;
    }
    """

    class Starten(Message):
        """Das Formular ist vollstaendig, die App soll den Ablauf starten."""

        def __init__(self, auftrag: DiskussionsAuftrag) -> None:
            super().__init__()
            self.auftrag = auftrag

    class Anhalten(Message):
        """Der Knopf "Anhalten" wurde gedrueckt."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._agenten: list[Agent] = []
        self._generation = 0
        """Zaehlt die Neuaufbauten der Agentenliste - IDs muessen eindeutig bleiben."""
        self._diskussion: Diskussion | None = None
        self._neu: list[Teilnehmer] = []
        """Platzhalter der frischen Agenten, bis ihre Namen bekannt sind."""
        self._runde = 0
        self._redner = ""
        self._zustand = ""

    # -- Aufbau ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="disk-formular"):
            with Horizontal(classes="disk-zeile"):
                yield Label(t("discussion.topic"))
                yield Input(placeholder=t("discussion.topic_placeholder"),
                            id="disk-thema", compact=True)
            with Horizontal(classes="disk-zeile"):
                yield Label(t("discussion.positions"))
                yield Input(placeholder=t("discussion.position_pro_placeholder"),
                            id="disk-position-pro", classes="disk-position", compact=True)
                yield Input(placeholder=t("discussion.position_contra_placeholder"),
                            id="disk-position-contra", classes="disk-position", compact=True)
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
                yield Static(t("discussion.no_agents"), id="disk-keine", classes="disk-leise")
            with Horizontal(classes="disk-zeile"):
                yield Label(t("discussion.new_agents"))
                yield Input("0", type="integer", id="disk-neu", classes="disk-zahl",
                            compact=True)
                yield Static(t("discussion.new_hint"), classes="disk-einheit")
            yield Checkbox(t("discussion.research"), value=False, id="disk-recherche",
                           compact=True)
            yield Checkbox(t("discussion.without_context"), value=True,
                           id="disk-ohne-kontext", compact=True)
            yield Static("", id="disk-vorschau", classes="disk-leise")
            yield Static("", id="disk-grund")
            with Horizontal(classes="disk-knoepfe"):
                yield Button(t("discussion.start"), variant="primary", id="disk-starten")
        with Vertical(id="disk-chat-raum"):
            yield Static("", id="disk-kopf")
            with Horizontal(id="disk-steuerung"):
                yield Button(t("discussion.stop"), variant="error", id="disk-anhalten")
                yield Button(t("discussion.new"), variant="primary", id="disk-neue")
            yield VerticalScroll(id="disk-chat")
            with VerticalScroll(id="disk-zusammenfassung-raum"):
                yield Static("", id="disk-zusammenfassung")

    def on_mount(self) -> None:
        self._pruefen()

    # -- Agentenliste ---------------------------------------------------

    def agenten_setzen(self, agenten: list[Agent]) -> None:
        """Nimmt den aktuellen Bestand. Baut die Liste nur neu, wenn sich Namen aendern.

        Haken und Seiten ueberleben den Neuaufbau ueber den Namen - sonst loeschte
        jede Aktualisierung des Bestands, was der Anwender gerade eingestellt hat.
        """
        neu = [a for a in agenten if not a.selbst]
        if [(a.name, a.rechner) for a in neu] == [(a.name, a.rechner) for a in self._agenten]:
            return
        vorher = {(z.agent.name, z.agent.rechner): (z.angekreuzt, z.seite)
                  for z in self.query(_AgentZeile)}
        self._agenten = neu
        self._generation += 1
        liste = self.query_one("#disk-agenten", VerticalScroll)
        liste.remove_children()
        if not neu:
            liste.mount(Static(t("discussion.no_agents"), classes="disk-leise"))
        for i, agent in enumerate(neu):
            angekreuzt, seite = vorher.get((agent.name, agent.rechner), (False, AUTO))
            liste.mount(_AgentZeile(agent, angekreuzt, seite,
                                    id=f"disk-agent-{self._generation}-{i}"))
        self.call_after_refresh(self._pruefen)

    # -- Formular auswerten ---------------------------------------------

    def _zahl(self, feld_id: str) -> float | None:
        roh = self.query_one(f"#{feld_id}", Input).value.strip().replace(",", ".")
        try:
            return float(roh)
        except ValueError:
            return None

    def auftrag(self) -> tuple[DiskussionsAuftrag | None, str]:
        """Baut den Auftrag aus dem Formular, oder nennt den ersten Grund, warum nicht."""
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
        zeilen = [z for z in self.query(_AgentZeile) if z.angekreuzt]
        if len(zeilen) + int(neu) < 2:
            return None, t("discussion.too_few")

        format_wert = str(self.query_one("#disk-format", Select).value)
        mit_seiten = format_wert == "diskussion"
        diskussion = Diskussion(
            thema=thema,
            teilnehmer=[Teilnehmer(z.agent.name,
                                   seite=z.seite if mit_seiten and z.seite != AUTO else "")
                        for z in zeilen],
            format=format_wert,
            runden=int(runden),
            dauer_minuten=float(dauer),
            recherche=self.query_one("#disk-recherche", Checkbox).value,
            positionen=(self.query_one("#disk-position-pro", Input).value.strip(),
                        self.query_one("#disk-position-contra", Input).value.strip()),
        )
        platzhalter = [Teilnehmer(t("discussion.new_placeholder", nummer=i + 1))
                       for i in range(int(neu))]
        # Seiten jetzt verteilen, in der Reihenfolge des Moderators: erst die
        # laufenden, dann die frischen. Die frischen behalten ihre Seite, wenn
        # sie spaeter ihren echten Namen bekommen.
        diskussion.teilnehmer = diskussion.teilnehmer + platzhalter
        diskussion.seiten_verteilen()
        grund = diskussion.pruefen()
        if grund:
            return None, grund
        anzahl = len(zeilen)
        neu_teilnehmer = diskussion.teilnehmer[anzahl:]
        diskussion.teilnehmer = diskussion.teilnehmer[:anzahl]
        return DiskussionsAuftrag(
            diskussion=diskussion,
            neu=neu_teilnehmer,
            ohne_kontext=self.query_one("#disk-ohne-kontext", Checkbox).value,
        ), ""

    def _seitenzeile(self, diskussion: Diskussion, teilnehmer: list[Teilnehmer]) -> str:
        if diskussion.format != "diskussion":
            return t("discussion.head_team", namen=", ".join(x.name for x in teilnehmer))
        return t(
            "discussion.head_sides",
            pro_pos=diskussion.position(PRO), contra_pos=diskussion.position(CONTRA),
            pro=", ".join(x.name for x in teilnehmer if x.seite == PRO),
            contra=", ".join(x.name for x in teilnehmer if x.seite == CONTRA),
        )

    def _pruefen(self) -> None:
        """Vorschau, Grund und Knopf auf den aktuellen Stand bringen."""
        auftrag, grund = self.auftrag()
        vorschau = ""
        if auftrag is not None:
            vorschau = self._seitenzeile(auftrag.diskussion,
                                         auftrag.diskussion.teilnehmer + auftrag.neu)
        self.query_one("#disk-vorschau", Static).update(Text(vorschau))
        self.query_one("#disk-grund", Static).update(Text(grund))
        self.query_one("#disk-starten", Button).disabled = auftrag is None
        # Ohne frische Sitzungen gibt es nichts, dem man den Kontext nehmen
        # koennte - laufende Agenten haben ihn laengst geladen.
        self.query_one("#disk-ohne-kontext", Checkbox).disabled = not self._zahl("disk-neu")

    @on(Input.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed)
    def _geaendert(self) -> None:
        if not self.has_class("laeuft"):
            self._pruefen()

    # -- Knoepfe --------------------------------------------------------

    @on(Button.Pressed, "#disk-starten")
    def _knopf_starten(self) -> None:
        auftrag, grund = self.auftrag()
        if auftrag is None:
            self.notify(grund, severity="warning", markup=False)
            return
        self.post_message(self.Starten(auftrag))

    @on(Button.Pressed, "#disk-anhalten")
    def _knopf_anhalten(self) -> None:
        self.query_one("#disk-anhalten", Button).disabled = True
        self._zustand = t("discussion.state_stopping")
        self._kopf_zeichnen()
        self.post_message(self.Anhalten())

    @on(Button.Pressed, "#disk-neue")
    def _knopf_neue(self) -> None:
        self.remove_class("fertig")
        self._pruefen()

    # -- Chat -----------------------------------------------------------

    def beginnen(self, diskussion: Diskussion, neu: list[Teilnehmer]) -> None:
        """Schaltet auf den Chat um. Die frischen Teilnehmer tragen noch Platzhalter."""
        self._diskussion = diskussion
        self._neu = neu
        self._runde = 0
        self._redner = ""
        self._zustand = t("discussion.state_starting") if neu else ""
        self.query_one("#disk-chat", VerticalScroll).remove_children()
        self.query_one("#disk-zusammenfassung", Static).update("")
        self.query_one("#disk-zusammenfassung-raum").remove_class("da")
        self.query_one("#disk-anhalten", Button).disabled = False
        self.query_one("#disk-anhalten", Button).display = True
        self.query_one("#disk-neue", Button).display = False
        self.remove_class("fertig")
        self.add_class("laeuft")
        self._kopf_zeichnen()

    def _kopf_zeichnen(self) -> None:
        d = self._diskussion
        if d is None:
            return
        teilnehmer = list(d.teilnehmer) + self._neu
        kopf = Text()
        kopf.append(d.thema, style="bold")
        kopf.append("\n")
        kopf.append(self._seitenzeile(d, teilnehmer))
        regeln = t("discussion.rules_research_on") if d.recherche else t(
            "discussion.rules_research_off")
        kopf.append(f"\n{regeln}", style="dim")
        if self._zustand:
            kopf.append(f"\n{self._zustand}", style="italic")
        self.query_one("#disk-kopf", Static).update(kopf)

    def redner(self, name: str, runde: int) -> None:
        """Der Moderator gibt gerade jemandem das Wort."""
        if self._diskussion is None:
            return
        self._runde, self._redner = runde, name
        if not self.query_one("#disk-anhalten", Button).disabled:
            self._zustand = t("discussion.state_turn", runde=runde,
                              runden=self._diskussion.runden, name=name)
        self._kopf_zeichnen()

    def beitrag(self, beitrag: Beitrag) -> None:
        """Haengt einen Eintrag an den Chat."""
        chat = self.query_one("#disk-chat", VerticalScroll)
        widget = self._blase(beitrag)
        chat.mount(widget)
        chat.scroll_end(animate=False)

    def _blase(self, beitrag: Beitrag) -> Static:
        d = self._diskussion
        if beitrag.art == "vorbereitung":
            # Die Notizen sind privat - im Chat steht nur, dass recherchiert wurde.
            text = (t("discussion.research_failed", name=beitrag.name)
                    if beitrag.ungeprueft else t("discussion.researched", name=beitrag.name))
            return Static(Text(text), classes="disk-meldung")
        if beitrag.art in ("fehler", "ausgelassen"):
            return Static(Text(f"{beitrag.name}: {beitrag.text}"), classes="disk-meldung")
        mit_seiten = d is not None and d.format == "diskussion" and beitrag.seite
        position = d.position(beitrag.seite) if (d is not None and mit_seiten) else ""
        kopf = t("discussion.bubble_head", name=beitrag.name, runde=beitrag.runde)
        if position:
            kopf = f"{kopf} · {position}"
        if beitrag.art == "schlusswort":
            kopf = f"{beitrag.name} · {t('discussion.head_closing')}"
        inhalt = Text()
        inhalt.append(kopf, style="bold")
        if beitrag.ungeprueft:
            inhalt.append(f"  {t('discussion.unverified')}", style="italic dim")
        inhalt.append("\n")
        inhalt.append(beitrag.text)
        if beitrag.hinweis:
            inhalt.append(f"\n{beitrag.hinweis}", style="dim italic")
        seite = beitrag.seite if mit_seiten else "team"
        klasse = {PRO: "disk-pro", CONTRA: "disk-contra"}.get(seite, "disk-team")
        return Static(inhalt, classes=f"disk-blase {klasse}")

    def meldung(self, text: str) -> None:
        """Eine Zeile des Ablaufs (Start, Namen, Zusammenfassung wird erstellt)."""
        self._zustand = text
        self._kopf_zeichnen()

    def teilnehmer_bekannt(self, diskussion: Diskussion) -> None:
        """Die frischen Agenten haben ihre Namen - Kopf neu zeichnen."""
        self._diskussion = diskussion
        self._neu = []
        self._kopf_zeichnen()

    def fertig(self, diskussion: Diskussion, ende: str, protokoll: str) -> None:
        """Beendet: Zusammenfassung unter den Chat, Knopf fuer eine neue Diskussion."""
        self._diskussion = diskussion
        self._zustand = t("discussion.state_done", ende=ende, pfad=protokoll)
        self._kopf_zeichnen()
        if diskussion.zusammenfassung:
            inhalt = Text()
            inhalt.append(t("discussion.summary_title"), style="bold")
            inhalt.append("\n")
            inhalt.append(diskussion.zusammenfassung)
            self.query_one("#disk-zusammenfassung", Static).update(inhalt)
            self.query_one("#disk-zusammenfassung-raum").add_class("da")
        self.query_one("#disk-anhalten", Button).display = False
        self.query_one("#disk-neue", Button).display = True
        self.remove_class("laeuft")
        self.add_class("fertig")
