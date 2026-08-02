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


class VerlaufPanel(VerticalScroll):
    """Zeigt die Auftraege mit einem Agenten von alt nach neu."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._partner = ""

    def compose(self) -> ComposeResult:
        yield Static(t("chat.none_selected"), classes="verlauf-hinweis", id="verlauf-hinweis")

    def leeren(self, hinweis: str) -> None:
        """Entfernt alle Blasen und zeigt stattdessen einen Hinweis."""
        self._partner = ""
        for kind in list(self.children):
            kind.remove()
        self.mount(Static(hinweis, classes="verlauf-hinweis"))

    def zeigen(self, partner: str, auftraege: list[Auftrag]) -> None:
        """Baut den Verlauf mit einem Agenten neu auf."""
        self._partner = partner
        for kind in list(self.children):
            kind.remove()
        if not auftraege:
            self.mount(Static(t("chat.empty"), classes="verlauf-hinweis"))
            return

        for auftrag in auftraege:
            for ereignis in auftrag.verlauf:
                klasse = "blase eigen" if ereignis.eigen else "blase fremd"
                self.mount(Static(self._blase(ereignis, auftrag), classes=klasse))
        self.scroll_end(animate=False)

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
