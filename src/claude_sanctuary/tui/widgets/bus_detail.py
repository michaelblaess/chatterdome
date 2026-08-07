"""Rechte Seite des Bus-Tabs: Uebersicht oder ein einzelner Auftrag.

Ohne Auswahl steht hier die Uebersicht, und sie beantwortet die Frage, die man
vor der Tabelle hat: liegt noch etwas an, wie alt ist das Aelteste, und wie
viel davon kann ein spaeterer Traeger eines Namens noch erben.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from claude_sanctuary.i18n import format_datetime, format_time, t
from claude_sanctuary.kern.busansicht import Kennzahlen, alter_stunden, kennzahlen
from claude_sanctuary.kern.modelle import Auftrag, Busbestand

ZUSTAND_FARBE = {
    "submitted": "#f1c40f",
    "working": "#3498db",
    "input_required": "#9b59b6",
    "completed": "#2ecc71",
    "failed": "#e74c3c",
    "cancelled": "#e67e22",
    "expired": "#95a5a6",
}

QUITTUNG_SCHLUESSEL = {
    200: "receipt.200",
    202: "receipt.202",
    403: "receipt.403",
    408: "receipt.408",
    409: "receipt.409",
    410: "receipt.410",
    503: "receipt.503",
}


def _dauer(stunden: float | None) -> str:
    """Ein Alter in lesbarer Form. Stunden unter einem Tag, sonst Tage."""
    if stunden is None:
        return "?"
    if stunden < 1:
        return t("bus.age.minutes", n=max(1, int(stunden * 60)))
    if stunden < 48:
        return t("bus.age.hours", n=int(stunden))
    return t("bus.age.days", n=int(stunden / 24))


class BusDetail(VerticalScroll):
    """Zeigt die Uebersicht des Busbestands oder einen einzelnen Auftrag."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bestand: Busbestand | None = None
        self._sichtbar: list[Auftrag] = []
        self._auftrag: Auftrag | None = None
        self._laeuft = False

    def compose(self) -> ComposeResult:
        yield Static(t("bus.loading"), id="bus-inhalt", markup=True)

    # -- Aussenseite ----------------------------------------------------

    def setze_bestand(self, bestand: Busbestand | None) -> None:
        self._bestand = bestand
        self._sichtbar = list(bestand.auftraege) if bestand else []
        self._zeichnen()

    def setze_sichtbar(self, auftraege: list[Auftrag]) -> None:
        """Der aktuell gefilterte Ausschnitt - die Zahlen zeigen ihn, nicht alles."""
        self._sichtbar = auftraege
        self._zeichnen()

    def setze_auftrag(self, auftrag: Auftrag | None) -> None:
        self._auftrag = auftrag
        self._zeichnen()

    def setze_laeuft(self, laeuft: bool) -> None:
        self._laeuft = laeuft
        self._zeichnen()

    # -- Zeichnen -------------------------------------------------------

    def _zeichnen(self) -> None:
        ziel = self.query_one("#bus-inhalt", Static)
        if self._laeuft and self._bestand is None:
            ziel.update(t("bus.loading"))
            return
        if self._bestand is None:
            ziel.update(t("bus.no_data"))
            return
        if self._bestand.fehler:
            ziel.update(f"[#e74c3c]{escape(self._bestand.fehler)}[/]")
            return
        ziel.update(self._einzeln() if self._auftrag else self._uebersicht())
        self.scroll_home(animate=False)

    def _uebersicht(self) -> str:
        bestand = self._bestand
        assert bestand is not None
        k = kennzahlen(self._sichtbar)
        zeilen = [
            f"[b]{t('bus.overview')}[/]  [dim]{escape(bestand.rechner)}[/]",
            "",
            *self._zahlenblock(k),
            "",
            *self._verfallsblock(k),
        ]
        if k.aeltester_offen is not None:
            zeilen += ["", *self._aeltester(k.aeltester_offen)]
        zeilen += ["", *self._bindungsblock(k)]
        return "\n".join(zeilen)

    def _zahlenblock(self, k: Kennzahlen) -> list[str]:
        return [
            f"[b]{t('bus.counts')}[/]",
            f"  {t('bus.count.total'):<22}{k.gesamt}",
            f"  {t('bus.count.open'):<22}[#f1c40f]{k.offen}[/]",
            f"  {t('bus.count.done'):<22}[#2ecc71]{k.erledigt}[/]",
            f"  {t('bus.count.failed'):<22}[#e74c3c]{k.gescheitert}[/]",
        ]

    def _verfallsblock(self, k: Kennzahlen) -> list[str]:
        bestand = self._bestand
        assert bestand is not None
        frist = bestand.verfall_stunden
        if not frist:
            return [
                f"[b]{t('bus.expiry')}[/]",
                f"  [#e74c3c]{t('bus.expiry.off')}[/]",
                f"  [dim]{t('bus.expiry.off_hint')}[/]",
            ]
        verfallen = k.je_zustand.get("expired", 0)
        return [
            f"[b]{t('bus.expiry')}[/]",
            f"  {t('bus.expiry.after', n=frist)}",
            f"  [dim]{t('bus.expiry.count', n=verfallen)}[/]",
        ]

    def _aeltester(self, a: Auftrag) -> list[str]:
        beteiligte = f"{escape(a.von or '?')} → {escape(a.an or '?')}"
        return [
            f"[b]{t('bus.oldest')}[/]",
            f"  [dim]{format_datetime(a.erstellt)}[/]  {beteiligte}",
            f"  {escape(' '.join(a.text.split())[:70])}",
            f"  [dim]{t('bus.age', dauer=_dauer(alter_stunden(a)))}[/]",
        ]

    def _bindungsblock(self, k: Kennzahlen) -> list[str]:
        """Die Zahl, die den Vorfall vom 07.08.2026 vorhergesagt haette."""
        zeilen = [f"[b]{t('bus.binding')}[/]"]
        if k.ohne_bindung_offen:
            zeilen += [
                f"  [#f1c40f]{t('bus.binding.role_open', n=k.ohne_bindung_offen)}[/]",
                f"  [dim]{t('bus.binding.role_hint')}[/]",
            ]
        else:
            zeilen.append(f"  [#2ecc71]{t('bus.binding.all_bound')}[/]")
        return zeilen

    def _einzeln(self) -> str:
        a = self._auftrag
        assert a is not None
        farbe = ZUSTAND_FARBE.get(a.zustand, "dim")
        zeilen = [
            f"[b]{escape(a.von or '?')} → {escape(a.an or '?')}[/]",
            f"[dim]{format_datetime(a.erstellt)}  {escape(a.topic or '-')}"
            f"  {escape(a.auftrag_id)}[/]",
            "",
            f"[{farbe}]{t(f'state.{a.zustand}') if a.zustand else '?'}[/]"
            f"   [dim]{t('bus.age', dauer=_dauer(alter_stunden(a)))}[/]",
            "",
            escape(a.text or "-"),
            "",
            *self._bindungszeile(a),
        ]
        quittungen = [e for e in a.verlauf if e.art == "quittung"]
        if quittungen:
            zeilen += ["", f"[b]{t('bus.receipts')}[/]"]
            for e in quittungen:
                schluessel = QUITTUNG_SCHLUESSEL.get(int(e.status)) if e.status else None
                bedeutung = t(schluessel) if schluessel else ""
                kopf = f"  [dim]{format_time(e.ts)}[/]  {escape(e.von or '?')}"
                if e.status:
                    ton = ZUSTAND_FARBE.get(e.zustand, "dim")
                    kopf += f"  [{ton}]{e.status} {escape(bedeutung)}[/]"
                zeilen.append(kopf)
                if e.notiz:
                    zeilen.append(f"    {escape(e.notiz)}")
        return "\n".join(zeilen)

    def _bindungszeile(self, a: Auftrag) -> list[str]:
        if a.an_session:
            return [
                f"[b]{t('bus.binding')}[/]",
                f"  [#2ecc71]{t('bus.binding.session', sitzung=a.an_session[:8])}[/]",
            ]
        if not a.bindung:
            return [
                f"[b]{t('bus.binding')}[/]",
                f"  [dim]{t('bus.binding.legacy')}[/]",
            ]
        return [
            f"[b]{t('bus.binding')}[/]",
            f"  [#f1c40f]{t('bus.binding.name', name=escape(a.an or '?'))}[/]",
        ]
