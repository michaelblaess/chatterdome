"""Die Agenten als Kacheln - dieselben Daten wie die Tabelle, nur zum Hinsehen.

Die Kacheln fuehren keinen eigenen Bestand und keine eigene Auswahl: was sichtbar
ist, Filter, Sortierung und der markierte Agent bleiben Sache von
``AgentenTabelle``. Zwei Auswahlen liefen sonst frueher oder spaeter auseinander,
und Beenden traefe einen anderen Agenten als den, der hervorgehoben ist.

Die Effekte sagen alle etwas aus, siehe ``bild_zu``. Gezeichnet wird eine Kachel
nur, wenn sich ihr Bild wirklich aendert - nicht bei jedem Takt.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any, ClassVar

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.widgets import Static
from textual_widgets import vim_navigation_bindings

from chatterdome.i18n import t
from chatterdome.kern.modelle import KONTEXT_KRITISCH, Agent, Ampel
from chatterdome.tui.schutz import klartext, klartext_oder_nichts
from chatterdome.tui.widgets import roboter
from chatterdome.tui.widgets.agenten_anzeige import (
    AMPEL_FARBE,
    BLINK_STIL,
    _alter,
    _aufgabe,
    _dauer,
    _tokens,
)
from chatterdome.tui.widgets.balken import balken
from chatterdome.tui.widgets.roboter import Gesicht

KACHEL_HOEHE = 11
"""Fuenf Zeilen Roboter, vier Zeilen Angaben, zwei Zeilen Rahmen."""

KACHEL_MINDESTBREITE = 22
"""Roboter samt Schlafzeichen und Rahmen. Darunter wird eine Spalte weniger gezeigt."""

SPALTEN_MAX = 4
"""Mehr Kacheln je Zeile werden nicht breiter sinnvoll, sondern nur unuebersichtlich."""

ANIMATIONS_TAKT = 0.25
"""Sekunden je Takt. Alles Bewegte ist ein Vielfaches davon."""

BLINZEL_ZYKLUS = 32
"""Takte zwischen zwei Lidschlaegen, bei 0,25 Sekunden also acht Sekunden."""

POST_BLINK_TAKTE = 12
"""So lange blinkt der Umschlag, wenn neue Post kommt. Danach steht er nur noch da."""

EINBLEND_VERSATZ = 0.05
EINBLEND_DAUER = 0.2
EINBLEND_GESTAFFELT = 12
"""Nur so viele erscheinen nacheinander, sonst wartet man bei vielen Agenten darauf."""

_KONTEXT_FREI = "#2ecc71"
_KONTEXT_ENG = "#f1c40f"
_KONTEXT_KRITISCH = "bold #e74c3c"
_DUNKLES_LICHT = "#5a4a12"
"""Das Antennenlicht in der Dunkelphase: dasselbe Gelb, nur aus."""

_SCHLAFZEICHEN = {(0, 0): " z", (1, 1): "Z ", (2, 0): "zZ"}
"""(Takt des Schlafens, Roboterzeile) auf das Zeichen rechts vom Kopf."""


def spalten_fuer(breite: int) -> int:
    """Wie viele Kacheln nebeneinander passen.

    :param breite: Verfuegbare Zeichen. Null, solange das Widget nie gezeichnet wurde.
    :returns: Immer mindestens eine Spalte.
    """
    # Zwischen n Kacheln liegen n-1 Zeichen Abstand.
    passend = (breite + 1) // (KACHEL_MINDESTBREITE + 1)
    return max(1, min(SPALTEN_MAX, passend))


@dataclass(frozen=True, slots=True)
class Bild:
    """Alles, was sich an einer Kachel im Takt aendern kann.

    Bleibt das Bild gleich, wird nichts gezeichnet. Freie Agenten blinzeln alle
    acht Sekunden einmal, und dafuer soll nicht viermal je Sekunde alles neu
    aufgebaut werden.
    """

    gesicht: Gesicht
    blick: int = 0
    licht_an: bool = True
    schlafzeichen: int = 0
    warnung_an: bool = False
    post_an: bool = False


def bild_zu(agent: Agent, verwaist: bool, takt: int, post_bis: int = 0) -> Bild:
    """Was eine Kachel in diesem Takt zeigt.

    :param agent: Der Agent.
    :param verwaist: Ob die Sitzung verwaist ist. Als Wert hinein, damit nicht
        viermal je Sekunde ein Zeitstempel je Agent gelesen wird.
    :param takt: Der laufende Takt.
    :param post_bis: Bis zu welchem Takt der Umschlag blinkt.
    """
    warnung = agent.kontext_kritisch and takt // 2 % 2 == 0
    post = takt < post_bis and takt % 2 == 0
    if not agent.erreichbar:
        return Bild(Gesicht.AUS, warnung_an=warnung, post_an=post)
    if verwaist:
        return Bild(Gesicht.SCHLAEFT, schlafzeichen=takt // 4 % 3, warnung_an=warnung, post_an=post)
    if agent.ampel is Ampel.BESCHAEFTIGT:
        return Bild(
            Gesicht.ARBEITET,
            blick=(-1, 0, 1, 0)[takt // 2 % 4],
            licht_an=takt // 2 % 2 == 0,
            warnung_an=warnung,
            post_an=post,
        )
    # Jeder blinzelt zu seiner Zeit, sonst zwinkert die ganze Reihe im Gleichtakt.
    versatz = roboter.kennzahl(agent.name) % BLINZEL_ZYKLUS
    blinzelt = (takt + versatz) % BLINZEL_ZYKLUS == 0
    return Bild(
        Gesicht.BLINZELT if blinzelt else Gesicht.WACH, warnung_an=warnung, post_an=post
    )


def _mittig(zeile: Text, breite: int) -> Text:
    """Mittet von Hand: Textual uebernimmt ``justify`` aus einem Rich-Text nicht je Zeile."""
    laenge = cell_len(zeile.plain)
    if laenge > breite:
        zeile = zeile.copy()
        zeile.truncate(breite)
        return zeile
    return Text(" " * ((breite - laenge) // 2)) + zeile


def _laufzeit(agent: Agent) -> str:
    """Die Laufzeit knapp - auf einer Kachel genuegen die Stunden."""
    stunden = agent.laufzeit_ms // 3_600_000
    wert = f"{stunden}h" if stunden else _dauer(agent.laufzeit_ms)
    return wert + ("+" if agent.fortgesetzt else "")


def _namenszeile(agent: Agent, beschriftung: str, breite: int, bild: Bild) -> Text:
    post = f"  ✉ {agent.post}" if agent.post else ""
    selbst = " *" if agent.selbst else ""
    platz = max(4, breite - 2 - cell_len(post) - len(selbst))
    # Der Name traegt die Ampelfarbe mit: so liest man den Zustand einer Reihe,
    # ohne jeden Punkt einzeln zu suchen.
    zeile = Text(no_wrap=True)
    zeile.append(f"● {_aufgabe(beschriftung, platz)}{selbst}", style=AMPEL_FARBE[agent.ampel])
    if post:
        zeile.append(post, style=BLINK_STIL if bild.post_an else "bold #f1c40f")
    return zeile


def _kontextzeile(agent: Agent, breite: int, bild: Bild) -> Text:
    wert = _tokens(agent.kontext)
    # Absolut gegen die kritische Schwelle: das Kontextfenster ist nicht
    # zuverlaessig bekannt, siehe kern/modelle.py. Ein Prozentwert waere geraten.
    anteil = agent.kontext / KONTEXT_KRITISCH if agent.kontext > 0 else 0.0
    if agent.kontext_kritisch:
        stil = BLINK_STIL if bild.warnung_an else _KONTEXT_KRITISCH
    else:
        stil = _KONTEXT_ENG if agent.kontext_eng else _KONTEXT_FREI
    zeile = Text(no_wrap=True)
    zeile.append(balken(anteil, max(1, breite - len(wert) - 1)), style=stil)
    zeile.append(f" {wert}", style="" if agent.kontext > 0 else "dim")
    return zeile


def _zeitzeile(agent: Agent, verwaist: bool, breite: int) -> Text:
    warnung = "⚠ " if verwaist else ""
    alter = _alter(agent.letzte_zeit)
    laufzeit = _laufzeit(agent)
    links = f"{warnung}{t('col.last_seen')} {alter}"
    rechts = f"{t('col.uptime')} {laufzeit}"
    # Reicht es nicht fuer beide Beschriftungen, bleiben die Werte. Die sind die
    # Aussage, und die Kachel steht ohnehin neben der Tabelle mit den Koepfen.
    if cell_len(links) + cell_len(rechts) + 1 > breite:
        links = f"{warnung}{alter}"
        rechts = laufzeit
    luecke = max(1, breite - cell_len(links) - cell_len(rechts))
    zeile = Text(no_wrap=True)
    zeile.append(links, style="bold #e74c3c" if verwaist else "dim")
    zeile.append(" " * luecke)
    zeile.append(rechts, style="dim")
    return zeile


def kachel_text(agent: Agent, beschriftung: str, breite: int, bild: Bild, verwaist: bool) -> Text:
    """Der ganze Inhalt einer Kachel, ohne den Rahmen.

    Fremdtext geht hier nur als Text-Objekt hinein, nie als Markup-Zeichenkette.
    Eine eckige Klammer in einem Auftrag ist also nur eine eckige Klammer.

    :param agent: Der Agent.
    :param beschriftung: Wie er angeschrieben wird, qualifiziert, wenn noetig.
    :param breite: Zeichen je Zeile.
    :param bild: Der Stand der Animation.
    :param verwaist: Ob die Sitzung verwaist ist.
    """
    licht = AMPEL_FARBE[agent.ampel].removeprefix("bold ")
    roboterzeilen = roboter.zeichne(
        agent.name,
        bild.gesicht,
        licht if bild.licht_an else _DUNKLES_LICHT,
        blick=bild.blick,
        gedimmt=bild.gesicht in (Gesicht.SCHLAEFT, Gesicht.AUS),
    )
    zeilen: list[Text] = []
    for nummer, zeile in enumerate(roboterzeilen):
        # Links und rechts gleich viel Platz, sonst rueckt der Roboter beim Schlafen.
        rechts = ""
        if bild.gesicht is Gesicht.SCHLAEFT:
            rechts = _SCHLAFZEICHEN.get((bild.schlafzeichen, nummer), "")
        gerahmt = Text("  ") + zeile + Text(rechts.ljust(2), style="dim")
        zeilen.append(_mittig(gerahmt, breite))

    zeilen.append(_mittig(_namenszeile(agent, beschriftung, breite, bild), breite))
    aufgabe = _aufgabe(agent.aufgabe, breite) if agent.aufgabe else "-"
    zeilen.append(_mittig(Text(aufgabe, style="" if agent.aufgabe else "dim"), breite))
    zeilen.append(_kontextzeile(agent, breite, bild))
    zeilen.append(_zeitzeile(agent, verwaist, breite))
    return Text("\n", no_wrap=True).join(zeilen)


class AgentenKachel(Static):
    """Eine Kachel. Haelt nur, was sie zum Zeichnen braucht."""

    class Geklickt(Message):
        """Die Maus war hier. Ausgewertet wird das am Behaelter."""

        def __init__(self, kachel: AgentenKachel, ereignis: events.Click) -> None:
            super().__init__()
            self.kachel = kachel
            self.taste = ereignis.button
            self.klicks = ereignis.chain
            self.bei = (ereignis.screen_x, ereignis.screen_y)

    def __init__(self, agent: Agent, beschriftung: str, mehrere_rechner: bool) -> None:
        super().__init__()
        self.agent = agent
        self.beschriftung = beschriftung
        self._verwaist = False
        self._takt = 0
        self._post_bis = 0
        self._bild = Bild(Gesicht.WACH)
        self.setze(agent, beschriftung, mehrere_rechner)

    def setze(self, agent: Agent, beschriftung: str, mehrere_rechner: bool) -> None:
        """Uebernimmt neue Werte, ohne die Kachel neu aufzubauen.

        :param agent: Der Agent an dieser Stelle.
        :param beschriftung: Wie er angeschrieben wird.
        :param mehrere_rechner: Ob der Rechner dazugeschrieben wird.
        """
        # Gleiche Sitzung, mehr Post: nur dann blinkt der Umschlag. Rueckt durch
        # eine neue Sortierung ein anderer Agent hierher, ist das keine neue Post.
        if agent.session_id == self.agent.session_id and agent.post > self.agent.post:
            self._post_bis = self._takt + POST_BLINK_TAKTE
        self.agent = agent
        self.beschriftung = beschriftung
        self._verwaist = agent.verwaist()
        self._zustand_setzen()
        # Ein Rahmentitel wertet Markup aus, der Rechnername kommt aus dem Mesh.
        self.border_subtitle = klartext(agent.rechner) if mehrere_rechner else ""
        self.tooltip = klartext_oder_nichts(self._hinweis())
        self._bild = bild_zu(agent, self._verwaist, self._takt, self._post_bis)
        self.refresh()

    def _hinweis(self) -> str | None:
        teile = [" ".join((self.agent.aufgabe or "").split()), self.agent.cwd]
        return "\n".join(teil for teil in teile if teil) or None

    def _zustand_setzen(self) -> None:
        a = self.agent
        self.set_class(not a.erreichbar, "weg")
        self.set_class(a.erreichbar and self._verwaist, "verwaist")
        self.set_class(a.erreichbar and not self._verwaist and a.ampel is Ampel.BESCHAEFTIGT,
                       "beschaeftigt")
        self.set_class(a.erreichbar and not self._verwaist and a.ampel is Ampel.FREI, "frei")

    def ticken(self, takt: int) -> None:
        """Ein Schritt der Animation. Zeichnet nur, wenn sich etwas aendert."""
        self._takt = takt
        bild = bild_zu(self.agent, self._verwaist, takt, self._post_bis)
        self.set_class(self.has_class("beschaeftigt") and not bild.licht_an, "puls")
        if bild != self._bild:
            self._bild = bild
            self.refresh()

    def render(self) -> Text:
        breite = self.content_size.width or KACHEL_MINDESTBREITE - 2
        return kachel_text(self.agent, self.beschriftung, breite, self._bild, self._verwaist)

    def on_click(self, ereignis: events.Click) -> None:
        ereignis.stop()
        self.post_message(self.Geklickt(self, ereignis))


class AgentenKacheln(ScrollableContainer):
    """Das Raster der Kacheln. Bedienung wie die Tabelle, aber in zwei Richtungen."""

    DEFAULT_CSS = f"""
    AgentenKacheln {{
        height: 1fr;
        layout: grid;
        grid-size: 3;
        grid-rows: {KACHEL_HOEHE};
        grid-gutter: 0 1;
        padding: 0 1;
    }}
    AgentenKachel {{
        height: {KACHEL_HOEHE};
        border: round $foreground 30%;
        border-subtitle-color: $foreground 60%;
        text-wrap: nowrap;
    }}
    AgentenKachel:hover {{
        background: $boost;
    }}
    AgentenKachel.frei {{
        border: round #2ecc71 70%;
    }}
    AgentenKachel.beschaeftigt {{
        border: round #f1c40f;
    }}
    AgentenKachel.beschaeftigt.puls {{
        border: round #f1c40f 35%;
    }}
    AgentenKachel.weg {{
        border: round #e74c3c;
    }}
    AgentenKachel.verwaist {{
        border: round $foreground 25%;
    }}
    AgentenKachel.markiert {{
        border: heavy $accent 70%;
        background: $boost;
    }}
    AgentenKacheln:focus AgentenKachel.markiert {{
        border: heavy $accent;
    }}
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("left", "cursor_left", show=False),
        Binding("right", "cursor_right", show=False),
        Binding("pageup", "page_up", show=False),
        Binding("pagedown", "page_down", show=False),
        Binding("home", "scroll_top", show=False),
        Binding("end", "scroll_bottom", show=False),
        Binding("enter", "aufrufen", show=False),
    ]

    class Gewaehlt(Message):
        """Die Bedienung will eine andere Kachel markieren."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class Aufgerufen(Message):
        """Doppelklick oder Enter - Detailansicht gewuenscht."""

        def __init__(self, index: int) -> None:
            super().__init__()
            self.index = index

    class MenueGewuenscht(Message):
        """Rechtsklick auf eine Kachel."""

        def __init__(self, index: int, bei: tuple[int, int]) -> None:
            super().__init__()
            self.index = index
            self.bei = bei

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._kacheln: list[AgentenKachel] = []
        self._cursor = 0
        self._takt_nummer = 0
        self._spalten = 3
        self._animiert = False
        self._zeitgeber: Any = None

    def on_mount(self) -> None:
        # Vim-Ebene am Widget, siehe AgentenDaten._on_mount.
        if getattr(self.app, "vim_navigation", False):
            for key, action in vim_navigation_bindings():
                self._bindings.bind(key, action, show=False)
        self._zeitgeber = self.set_interval(ANIMATIONS_TAKT, self._ticken, pause=not self._animiert)

    # -- Daten ----------------------------------------------------------

    def zeigen(self, agenten: Sequence[Agent], beschriftung: Callable[[Agent], str],
               cursor: int) -> None:
        """Bringt die Kacheln auf den neuen Stand.

        Bestehende Kacheln werden wiederverwendet: der Bestand kommt alle paar
        Sekunden neu, und Abbauen und Aufbauen hiesse jedes Mal Flackern und einen
        verlorenen Scrollstand. Deshalb auch keine Kennungen aus Agentendaten -
        zwei Prozesse auf einer Sitzung sind ein echter Zustand, siehe
        ``agenten_tabelle.eindeutig``.

        :param agenten: Die sichtbaren Agenten, in der Reihenfolge der Tabelle.
        :param beschriftung: Wie ein Agent angeschrieben wird.
        :param cursor: Index des markierten Agenten.
        """
        rechner = {a.rechner.casefold() for a in agenten}
        mehrere = len(rechner) > 1
        for kachel, agent in zip(self._kacheln, agenten, strict=False):
            kachel.setze(agent, beschriftung(agent), mehrere)
        ueberzaehlig = self._kacheln[len(agenten) :]
        neu = [AgentenKachel(a, beschriftung(a), mehrere) for a in agenten[len(self._kacheln) :]]
        self._kacheln = [*self._kacheln[: len(agenten)], *neu]
        for kachel in ueberzaehlig:
            kachel.remove()
        if neu:
            self.mount(*neu)
        self.markiere(cursor)

    def markiere(self, index: int) -> None:
        """Zeichnet die Markierung. Wer markiert ist, entscheidet die Tabelle."""
        self._cursor = index
        for i, kachel in enumerate(self._kacheln):
            kachel.set_class(i == index, "markiert")
        if 0 <= index < len(self._kacheln):
            self.call_after_refresh(self._cursor_zeigen, self._kacheln[index])

    def _cursor_zeigen(self, kachel: AgentenKachel) -> None:
        if kachel.is_attached:
            self.scroll_to_widget(kachel, animate=False)

    # -- Effekte --------------------------------------------------------

    def animieren(self, an: bool) -> None:
        """Startet oder stoppt den Takt. Eine verborgene Ansicht rechnet nichts."""
        self._animiert = an
        if self._zeitgeber is None:
            return
        if an:
            self._zeitgeber.resume()
        else:
            self._zeitgeber.pause()

    def _ticken(self) -> None:
        # Hinter einem Dialog oder auf einem anderen Reiter sieht es niemand.
        if not self.screen.is_current or self.region.area == 0:
            return
        self._takt_nummer += 1
        for kachel in self._kacheln:
            kachel.ticken(self._takt_nummer)

    def einblenden(self) -> None:
        """Laesst die Kacheln beim Umschalten kurz nacheinander erscheinen."""
        if self.app.animation_level == "none":
            return
        for i, kachel in enumerate(self._kacheln[:EINBLEND_GESTAFFELT]):
            kachel.styles.opacity = 0.0
            # i + 1: ein Zeitgeber mit Dauer null wirft in Textual eine
            # ZeroDivisionError, und die erste Kachel bliebe unsichtbar.
            self.set_timer((i + 1) * EINBLEND_VERSATZ, partial(self._aufblenden, kachel))

    def _aufblenden(self, kachel: AgentenKachel) -> None:
        if kachel.is_attached:
            kachel.styles.animate("opacity", value=1.0, duration=EINBLEND_DAUER)

    # -- Bedienung ------------------------------------------------------

    def on_resize(self, ereignis: events.Resize) -> None:
        spalten = spalten_fuer(ereignis.size.width)
        if spalten != self._spalten:
            self._spalten = spalten
            self.styles.grid_size_columns = spalten

    def _gehe_zu(self, index: int) -> None:
        if not self._kacheln:
            return
        self.post_message(self.Gewaehlt(max(0, min(len(self._kacheln) - 1, index))))

    def action_cursor_left(self) -> None:
        self._gehe_zu(self._cursor - 1)

    def action_cursor_right(self) -> None:
        self._gehe_zu(self._cursor + 1)

    def action_cursor_up(self) -> None:
        self._gehe_zu(self._cursor - self._spalten)

    def action_cursor_down(self) -> None:
        self._gehe_zu(self._cursor + self._spalten)

    def _zeilen_je_seite(self) -> int:
        return max(1, self.size.height // KACHEL_HOEHE)

    def action_page_up(self) -> None:
        self._gehe_zu(self._cursor - self._spalten * self._zeilen_je_seite())

    def action_page_down(self) -> None:
        self._gehe_zu(self._cursor + self._spalten * self._zeilen_je_seite())

    def action_scroll_top(self) -> None:
        self._gehe_zu(0)

    def action_scroll_bottom(self) -> None:
        self._gehe_zu(len(self._kacheln) - 1)

    def action_aufrufen(self) -> None:
        if 0 <= self._cursor < len(self._kacheln):
            self.post_message(self.Aufgerufen(self._cursor))

    def on_agenten_kachel_geklickt(self, ereignis: AgentenKachel.Geklickt) -> None:
        ereignis.stop()
        try:
            index = self._kacheln.index(ereignis.kachel)
        except ValueError:
            return  # Gerade durch einen neuen Bestand entfernt.
        if ereignis.taste == 3:
            self.post_message(self.Gewaehlt(index))
            self.post_message(self.MenueGewuenscht(index, ereignis.bei))
        elif ereignis.taste == 1:
            self.post_message(self.Gewaehlt(index))
            if ereignis.klicks >= 2:
                self.post_message(self.Aufgerufen(index))
