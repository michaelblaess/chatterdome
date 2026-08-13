"""Auftragsverlauf mit einem Agenten, im Muster eines Nachrichtenverlaufs.

Es ist bewusst kein Chat: eine laufende interaktive Sitzung hat keinen
Eingang, ein neuer Zug entsteht nur durch eine Eingabe des Benutzers. Was hier
steht, sind abgelegte Auftraege und die Quittungen des Empfaengers - deshalb
tragen die Blasen einen Zustand und keine Haken.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from claude_sanctuary.i18n import format_time, t
from claude_sanctuary.kern.modelle import Auftrag

ZUSTAND_FARBE = {
    "submitted": "grey62",
    "working": "yellow",
    "input_required": "cyan",
    "completed": "green",
    "failed": "red",
    "cancelled": "red",
}

QUITTUNG_SCHLUESSEL = {
    200: "receipt.200",
    202: "receipt.202",
    403: "receipt.403",
    409: "receipt.409",
    503: "receipt.503",
}
"""Quittungscodes auf Uebersetzungsschluessel.

Vorher standen die deutschen Woerter direkt hier - in der englischen Fassung
las man dann "200 erledigt". Codes bleiben Codes, ihre Bedeutung ist Text.
"""


class Blase(Static):
    """Eine einzelne Verlaufsblase.

    Traegt ihren Auftrag und ihren Klartext mit sich, damit das Kontextmenue
    weiss, worauf es zeigt, und damit Kopieren ohne Rich-Auszeichnung geht.
    """

    def __init__(self, inhalt: Text, auftrag_id: str, **kwargs: Any) -> None:
        super().__init__(inhalt, **kwargs)
        self.auftrag_id = auftrag_id
        self.klartext = inhalt.plain


class VerlaufPanel(VerticalScroll):
    """Zeigt die Auftraege mit einem Agenten von alt nach neu."""

    class MenueGewuenscht(Message):
        """Rechtsklick im Verlauf.

        Das Panel baut das Menue NICHT selbst: welche Eintraege sinnvoll sind,
        haengt an Dingen, die die App kennt (Zwischenablage, Dateidialog).
        """

        def __init__(self, position: tuple[int, int], blase: Blase | None) -> None:
            super().__init__()
            self.position = position
            self.blase = blase
            """Die getroffene Blase, oder None bei einem Klick ins Leere."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._partner = ""
        self._auftraege: list[Auftrag] = []
        self._ausgeblendet: set[str] = set()
        """Auftraege, die "Ansicht leeren" verborgen hat.

        Bewusst nur im Speicher und bewusst nur die Anzeige: der Bus ist
        append-only, und ein Verlauf, den man versehentlich loescht, ist der
        Nachweis fuer eine Quittung. Nach einem Neustart ist alles wieder da.
        """

    def compose(self) -> ComposeResult:
        yield Static(t("chat.none_selected"), classes="verlauf-hinweis", id="verlauf-hinweis")

    def leeren(self, hinweis: str) -> None:
        """Entfernt alle Blasen und zeigt stattdessen einen Hinweis."""
        self._partner = ""
        self._auftraege = []
        for kind in list(self.children):
            kind.remove()
        self.mount(Static(hinweis, classes="verlauf-hinweis"))

    def zeigen(self, partner: str, auftraege: list[Auftrag]) -> None:
        """Baut den Verlauf mit einem Agenten neu auf."""
        # Ein Wechsel des Partners hebt das Ausblenden auf - die Marke gilt fuer
        # den Verlauf, den der Anwender vor sich hatte, nicht fuer jeden anderen.
        if partner != self._partner:
            self._ausgeblendet.clear()
        self._partner = partner
        self._auftraege = list(auftraege)
        self._neu_zeichnen()

    def ansicht_leeren(self) -> None:
        """Blendet aus, was gerade zu sehen ist. Neue Auftraege kommen wieder."""
        self._ausgeblendet.update(a.auftrag_id for a in self._auftraege)
        self._neu_zeichnen()

    def alles_zeigen(self) -> None:
        """Nimmt das Ausblenden zurueck."""
        self._ausgeblendet.clear()
        self._neu_zeichnen()

    @property
    def etwas_ausgeblendet(self) -> bool:
        """Ob gerade etwas verborgen ist - steuert den Menueeintrag."""
        return bool(self._ausgeblendet)

    def vorschlagsname(self) -> str:
        """Dateiname fuer den Speichern-Dialog, aus dem Namen des Partners."""
        rein = "".join(z for z in self._partner if z.isalnum() or z in "-_@")
        return f"verlauf-{rein or 'agent'}.txt"

    def sichtbarer_text(self) -> str:
        """Der sichtbare Verlauf als Klartext, fuer Zwischenablage und Datei."""
        blasen = [k for k in self.children if isinstance(k, Blase)]
        return "\n\n".join(b.klartext for b in blasen)

    def _sichtbare_auftraege(self) -> list[Auftrag]:
        return [a for a in self._auftraege if a.auftrag_id not in self._ausgeblendet]

    def _neu_zeichnen(self) -> None:
        for kind in list(self.children):
            kind.remove()

        sichtbar = self._sichtbare_auftraege()
        if not sichtbar:
            hinweis = t("chat.cleared") if self._ausgeblendet else t("chat.empty")
            self.mount(Static(hinweis, classes="verlauf-hinweis"))
            return

        for auftrag in sichtbar:
            for ereignis in auftrag.verlauf:
                klasse = "blase eigen" if ereignis.eigen else "blase fremd"
                self.mount(
                    Blase(self._blase(ereignis, auftrag), auftrag.auftrag_id, classes=klasse)
                )
        self.scroll_end(animate=False)

    def on_click(self, event: Click) -> None:
        """Rechtsklick meldet sich bei der App, alles andere laeuft weiter."""
        if event.button != 3:
            return
        event.stop()
        ziel = event.widget
        blase = ziel if isinstance(ziel, Blase) else None
        self.post_message(self.MenueGewuenscht((event.screen_x, event.screen_y), blase))

    def _blase(self, ereignis: Any, auftrag: Auftrag) -> Text:
        """Setzt eine einzelne Blase aus Kopf und Inhalt zusammen."""
        text = Text()
        kopf = Text()
        # Name@RECHNER statt nur Name: im Mesh kann derselbe Name auf zwei
        # Rechnern vergeben sein, und ohne den Zusatz ist nicht erkennbar,
        # von wo die Antwort kam.
        kopf.append(f"{ereignis.absender} ", style="bold")
        kopf.append(format_time(ereignis.ts), style="dim")
        if ereignis.eigen:
            zustand = auftrag.zustand
            kopf.append("  ")
            kopf.append(
                t(f"state.{zustand}") if zustand else "",
                style=ZUSTAND_FARBE.get(zustand, "dim"),
            )
            if auftrag.topic:
                kopf.append(f"  [{auftrag.topic}]", style="dim")
        elif ereignis.status is not None:
            kopf.append("  ")
            schluessel = QUITTUNG_SCHLUESSEL.get(int(ereignis.status))
            beschriftung = t(schluessel) if schluessel else str(ereignis.status)
            kopf.append(
                f"{ereignis.status} {beschriftung}",
                style=ZUSTAND_FARBE.get(ereignis.zustand, "dim"),
            )
        text.append_text(kopf)

        inhalt = ereignis.text or ereignis.notiz
        if inhalt:
            text.append("\n")
            text.append(str(inhalt))
        elif not ereignis.eigen:
            text.append("\n")
            text.append(t("chat.receipt"), style="dim italic")
        return text
