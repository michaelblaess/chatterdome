"""Rechte Seite des Gedaechtnis-Tabs: Uebersicht oder eine einzelne Notiz.

Ohne Auswahl steht hier die Uebersicht, und die ist der eigentliche Zweck des
Tabs. Sie stellt zwei Zahlen nebeneinander, die man sonst nie zusammen sieht:
was der Index in JEDER Sitzung kostet und was der gesamte Bestand kosten
wuerde, wenn er je vollstaendig geladen wuerde. Der Abstand zwischen beiden
ist die ganze Lehre.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.gedaechtnis import (
    INDEX_BYTES_LIMIT,
    INDEX_ZEILEN_LIMIT,
    ZEICHEN_JE_TOKEN,
    Gedaechtnis,
    Notiz,
    schaetze_tokens,
)

BALKEN_BREITE = 34
"""Zellen fuer den laengsten Balken. Passt neben die Beschriftung."""


def _zahl(wert: int) -> str:
    """Tausendertrennung mit Punkt, wie im deutschen Schriftbild ueblich."""
    return f"{wert:,}".replace(",", ".")


def _balken(anteil: float, breite: int = BALKEN_BREITE) -> str:
    """Zeichnet einen Balken. Ein Wert ueber null bekommt immer ein Zeichen.

    Sonst verschwindet der kleinere von zwei Werten ganz, und ein Balken der
    Laenge null sieht aus wie "kostet nichts" statt "kostet wenig".
    """
    voll = round(max(0.0, min(1.0, anteil)) * breite)
    if anteil > 0:
        voll = max(1, voll)
    return "█" * voll + "░" * (breite - voll)


class GedaechtnisDetail(VerticalScroll):
    """Zeigt die Uebersicht des Bestands oder eine einzelne Notiz."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bestand: Gedaechtnis | None = None
        self._notiz: Notiz | None = None
        self._laeuft = False

    def compose(self) -> ComposeResult:
        yield Static(t("mem.loading"), id="gedaechtnis-inhalt", markup=True)

    # -- Aussenseite ----------------------------------------------------

    def setze_bestand(self, bestand: Gedaechtnis | None) -> None:
        self._bestand = bestand
        self._zeichnen()

    def setze_notiz(self, notiz: Notiz | None) -> None:
        self._notiz = notiz
        self._zeichnen()

    def setze_laeuft(self, laeuft: bool) -> None:
        """Schaltet den Hinweis, dass die Transkripte gerade gelesen werden."""
        self._laeuft = laeuft
        self._zeichnen()

    # -- intern ---------------------------------------------------------

    def _zeichnen(self) -> None:
        ziel = self.query_one("#gedaechtnis-inhalt", Static)
        if self._bestand is None:
            ziel.update(t("mem.loading"))
            return
        if not self._bestand.notizen:
            # Ohne diesen Zweig bliebe "wird gelesen" stehen, und ein falsch
            # eingetragener Pfad saehe aus wie ein haengendes Programm.
            ziel.update(t("mem.no_dir", pfad=escape(str(self._bestand.verzeichnis))))
            return
        if self._notiz is not None:
            ziel.update("\n".join(self._notiz_text(self._notiz)))
            return
        ziel.update("\n".join(self._uebersicht(self._bestand)))

    def _verweis(self, text: str, ziel: str) -> str:
        """Klickbarer Verweis, wenn die App das Mischgut mitbringt.

        Der Text MUSS entschaerft werden: eckige Klammern im Fremdtext liest
        Rich sonst als Auszeichnung, und der Verweis wird sichtbar leer.
        """
        macher = getattr(self.app, "link_markup", None)
        sicher = escape(text)
        return str(macher(sicher, ziel)) if callable(macher) else sicher

    # -- Uebersicht -----------------------------------------------------

    def _uebersicht(self, bestand: Gedaechtnis) -> list[str]:
        zeilen: list[str] = [
            f"[bold]{t('mem.headline')}[/]",
            f"[dim]{t('mem.lead')}[/]",
            "",
        ]
        zeilen += self._auslastung(bestand)
        zeilen += self._kosten(bestand)
        zeilen += self._arten(bestand)
        zeilen += self._pruefungen(bestand)
        zeilen += self._abrufe(bestand)
        zeilen += self._groesste(bestand)
        zeilen += self._diaet(bestand)
        return zeilen

    def _auslastung(self, bestand: Gedaechtnis) -> list[str]:
        """Die dringlichste Zahl, deshalb ganz oben.

        Anders als die geschaetzten Token ist das ein HARTES Limit: was
        darueber steht, wird beim Sitzungsstart still abgeschnitten, und zwar
        das zuletzt Angelegte. Wer es nicht kennt, verliert Notizen, ohne dass
        irgendwo etwas passiert.
        """
        farbe = "#e74c3c" if bestand.index_warnt else "#2ecc71"
        return [
            f"[bold]{t('mem.limit.title')}[/]",
            "",
            f"  [{farbe}]{_balken(bestand.index_zeilen_anteil, 24)}[/]  "
            + t(
                "mem.limit.lines",
                zeilen=bestand.index_zeilen,
                grenze=INDEX_ZEILEN_LIMIT,
                prozent=round(bestand.index_zeilen_anteil * 100),
            ),
            f"  [dim]{_balken(bestand.index_bytes_anteil, 24)}[/]  "
            + t(
                "mem.limit.bytes",
                bytes=_zahl(bestand.index_zeichen),
                grenze=_zahl(INDEX_BYTES_LIMIT),
                prozent=round(bestand.index_bytes_anteil * 100),
            ),
            "",
            (
                f"[bold #e74c3c]{t('mem.limit.warn', frei=bestand.index_zeilen_frei)}[/]"
                if bestand.index_warnt
                else f"[dim]{t('mem.limit.ok', frei=bestand.index_zeilen_frei)}[/]"
            ),
            f"[dim]{t('mem.limit.hint')}[/]",
            "",
        ]

    def _kosten(self, bestand: Gedaechtnis) -> list[str]:
        index = bestand.index_tokens
        gesamt = bestand.bestand_tokens
        hoechster = max(index, gesamt, 1)
        index_note = t(
            "mem.cost.index_note",
            zeilen=bestand.index_zeilen,
            eintraege=bestand.index_eintraege,
        )
        bestand_note = t(
            "mem.cost.bestand_note",
            anzahl=bestand.anzahl,
            zeilen=_zahl(bestand.zeilen_gesamt),
        )
        # Die Hochrechnung ist der eigentliche Punkt: einmal wirkt der Index
        # winzig, ueber die Sitzungen hinweg ueberholt er den ganzen Bestand.
        # Gerechnet wird nur mit einer GEMESSENEN Sitzungszahl, nie mit einer
        # ausgedachten.
        bericht = bestand.recall_bericht
        sitzungen = bericht.dateien if bericht is not None else 0
        summiert = index * sitzungen
        hoechster = max(index, gesamt, summiert, 1)

        zeilen = [
            f"[bold]{t('mem.cost.title')}[/]",
            "",
            f"  [bold #e74c3c]{_balken(index / hoechster)}[/]  [bold]{_zahl(index)}[/] Token",
            f"  [dim]{t('mem.cost.index')} - {index_note}[/]",
            "",
            f"  [dim]{_balken(gesamt / hoechster)}[/]  [bold]{_zahl(gesamt)}[/] Token",
            f"  [dim]{t('mem.cost.bestand')} - {bestand_note}[/]",
        ]
        if sitzungen > 1:
            zeilen += [
                "",
                f"  [bold #e74c3c]{_balken(summiert / hoechster)}[/]  "
                f"[bold]{_zahl(summiert)}[/] Token",
                f"  [dim]{t('mem.cost.sum_note', sitzungen=sitzungen)}[/]",
            ]
        zeilen += [
            "",
            t("mem.cost.per_line", tokens=bestand.tokens_je_indexzeile),
            f"[bold]{t('mem.cost.lesson')}[/]",
            f"[dim]{t('mem.estimate', faktor=str(ZEICHEN_JE_TOKEN).replace('.', ','))}[/]",
            "",
        ]
        return zeilen

    def _arten(self, bestand: Gedaechtnis) -> list[str]:
        nach_typ = bestand.nach_typ
        if not nach_typ:
            return []
        hoechster = max(nach_typ.values())
        zeilen = [f"[bold]{t('mem.types.title')}[/]", ""]
        for typ, anzahl in nach_typ.items():
            zeilen.append(
                f"  [dim]{typ:<12}[/] {_balken(anzahl / hoechster, 22)} "
                f"[bold]{anzahl:>3}[/]"
            )
        zeilen.append("")
        return zeilen

    def _pruefungen(self, bestand: Gedaechtnis) -> list[str]:
        zeilen = [f"[bold]{t('mem.health.title')}[/]", ""]
        gezaehlt: dict[str, int] = {}
        for befund in bestand.befunde():
            gezaehlt[befund.art] = gezaehlt.get(befund.art, 0) + 1
        if not gezaehlt:
            zeilen.append(f"  [#2ecc71]✓[/] {t('mem.health.ok')}")
        for art, anzahl in sorted(gezaehlt.items(), key=lambda paar: -paar[1]):
            zeilen.append(f"  [#e74c3c]●[/] {t(f'mem.health.{art}', anzahl=anzahl)}")
        # Isolierte Notizen stehen bewusst UNTER den Befunden und in gelb: das
        # ist ein Hinweis, kein Fehler. Eine Notiz kann voellig in Ordnung sein,
        # ohne dass eine andere auf sie verweist.
        isoliert = len(bestand.isolierte)
        if isoliert:
            zeilen.append(f"  [#f1c40f]●[/] {t('mem.health.isoliert', anzahl=isoliert)}")
        zeilen.append("")
        return zeilen

    def _abrufe(self, bestand: Gedaechtnis) -> list[str]:
        zeilen = [f"[bold]{t('mem.recall.title')}[/]", ""]
        bericht = bestand.recall_bericht
        if self._laeuft:
            zeilen += [f"  [dim]{t('mem.recall.pending')}[/]", ""]
            return zeilen
        if bericht is None:
            zeilen += [f"  [dim]{t('mem.recall.none')}[/]", ""]
            return zeilen

        nie = sum(1 for n in bestand.notizen if n.recalls == 0)
        # Fliesstext ohne Einzug: bricht er um, stuende die Fortsetzung sonst
        # am linken Rand und der Absatz saehe zerrissen aus.
        zeilen.append(
            t(
                "mem.recall.summary",
                zugeordnet=bericht.zugeordnet,
                notizen=len(bericht.treffer),
                dateien=bericht.dateien,
                mb=round(bericht.bytes / 1_000_000),
                nie=nie,
                gesamt=bestand.anzahl,
            )
        )
        if bericht.unzugeordnet:
            zeilen.append(f"[dim]{t('mem.recall.unassigned', anzahl=bericht.unzugeordnet)}[/]")
        zeilen += [f"[dim]{t('mem.recall.floor')}[/]", ""]
        return zeilen

    def _groesste(self, bestand: Gedaechtnis) -> list[str]:
        groesste = bestand.groesste(5)
        if not groesste:
            return []
        hoechster = max(n.zeilen for n in groesste)
        zeilen = [f"[bold]{t('mem.biggest.title')}[/]", ""]
        for notiz in groesste:
            zeilen.append(
                f"  {_balken(notiz.zeilen / hoechster, 18)} [bold]{notiz.zeilen:>4}[/] "
                f"[dim]{escape(notiz.name)}[/]"
            )
        zeilen.append("")
        return zeilen

    def _diaet(self, bestand: Gedaechtnis) -> list[str]:
        erledigte = bestand.erledigte
        zeilen = [f"[bold]{t('mem.diet.title')}[/]", ""]
        if not erledigte:
            zeilen += [f"  [dim]{t('mem.diet.done_none')}[/]", ""]
            return zeilen
        # Aus vielen Index-Zeilen wird eine: gespart wird alles bis auf die
        # eine, die die Sammelnotiz selbst braucht.
        ersparnis = max(0, len(erledigte) - 1) * bestand.tokens_je_indexzeile
        zeilen += [
            t("mem.diet.done", anzahl=len(erledigte), tokens=_zahl(ersparnis)),
            f"[dim]{t('mem.diet.hint')}[/]",
            "",
        ]
        return zeilen

    # -- Einzelne Notiz -------------------------------------------------

    def _notiz_text(self, notiz: Notiz) -> list[str]:
        zeilen = [f"[bold]{escape(notiz.name)}[/]"]
        if notiz.index_text and notiz.index_text != notiz.name:
            zeilen.append(f"[dim]{escape(notiz.index_text)}[/]")
        zeilen.append("")

        if notiz.beschreibung:
            zeilen += [
                f"[bold]{t('mem.detail.desc')}[/]",
                f"  {escape(notiz.beschreibung)}",
                "",
            ]

        zeilen += [
            f"[bold]{t('mem.detail.facts')}[/]",
            f"  {t('mem.detail.type')}: {notiz.typ or '?'}",
            "  "
            + t(
                "mem.detail.lines",
                zeilen=notiz.zeilen,
                zeichen=_zahl(notiz.zeichen),
                tokens=_zahl(schaetze_tokens(notiz.zeichen)),
            ),
        ]
        if notiz.im_index:
            zeilen.append(
                f"  {t('mem.detail.index')}: "
                f"{t('mem.detail.index_yes', text=escape(notiz.index_text))}"
            )
        else:
            zeilen.append(
                f"  {t('mem.detail.index')}: [#e74c3c]{t('mem.detail.index_no')}[/]"
            )
        zeilen.append("")

        zeilen += self._verweise(notiz)

        zeilen += [f"[bold]{t('mem.detail.recalls')}[/]", f"  {self._abruf_text(notiz)}", ""]

        if notiz.erledigt_verdacht:
            zeilen += [f"[#f1c40f]{t('mem.detail.done')}[/]", ""]

        pfad = str(notiz.datei)
        zeilen += [f"[bold]{t('mem.detail.file')}[/]", f"  {self._verweis(pfad, pfad)}"]
        return zeilen

    def _verweise(self, notiz: Notiz) -> list[str]:
        aus = ", ".join(escape(z) for z in notiz.verweist_auf) or t("mem.detail.none")
        ein = ", ".join(escape(z) for z in notiz.eingehend) or t("mem.detail.none")
        zeilen = [
            f"[bold]{t('mem.detail.out')}[/] ({len(notiz.verweist_auf)})",
            f"  [dim]{aus}[/]",
        ]
        if notiz.tote_verweise:
            tot = ", ".join(escape(z) for z in notiz.tote_verweise)
            zeilen.append(f"  [#e74c3c]{t('mem.detail.dead')}: {tot}[/]")
        zeilen += [
            "",
            f"[bold]{t('mem.detail.in')}[/] ({len(notiz.eingehend)})",
            f"  [dim]{ein}[/]",
            "",
        ]
        return zeilen

    def _abruf_text(self, notiz: Notiz) -> str:
        if not notiz.recalls:
            return f"[dim]{t('mem.detail.recalls_never')}[/]"
        if notiz.letzter_recall_tage is None:
            return t("mem.detail.recalls_plain", anzahl=notiz.recalls)
        return t(
            "mem.detail.recalls_value",
            anzahl=notiz.recalls,
            tage=notiz.letzter_recall_tage,
        )
