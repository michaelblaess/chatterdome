"""Sechs Sektionen aus den Transkripten und dem Bus.

Gezeichnet wird mit plotext ueber textual-plotext, wie in jira-timesheet -
beide MIT-lizenziert und damit vertraeglich mit Apache 2.0.

Zur Anordnung: drei Reihen zu zwei Sektionen. Ein einspaltiges Dashboard
zwingt zum Scrollen, bevor die zweite Zahl sichtbar ist, und die Aussagen
stehen hier paarweise - Flotte neben Verbrauch, Dauer neben Ordner, Bus neben
Warnung.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual_plotext import PlotextPlot

from claude_sanctuary.i18n import t
from claude_sanctuary.kern.statistik import LANGE_SITZUNG_STUNDEN, Statistik

# Farben der Verbrauchsarten. plotext nimmt Namen aus seiner eigenen Palette,
# nicht die Hexwerte der Oberflaeche.
FARBE_FRISCH = "green"
FARBE_CACHE_NEU = "orange"
FARBE_CACHE_GELESEN = "gray"
FARBE_AUS = "cyan"

FARBE_ERLEDIGT = "green"
FARBE_GESCHEITERT = "red"
FARBE_OFFEN = "orange"

DIAGRAMM_HOEHE = 14
"""Zeilen je Diagramm. Weniger macht die Achsenbeschriftung unleserlich."""


def _millionen(wert: int) -> str:
    """Token in Millionen, deutsch formatiert. Rohe Zahlen sind hier unlesbar."""
    return f"{wert / 1e6:,.1f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _zahl(wert: int) -> str:
    return f"{wert:,}".replace(",", ".")


class StatistikDashboard(VerticalScroll):
    """Nimmt eine fertige Statistik entgegen und zeichnet sie."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._statistik: Statistik | None = None
        self._laeuft = False

    def compose(self) -> ComposeResult:
        yield Static(t("stats.loading"), id="stats-kopf", markup=True)
        with Horizontal(classes="stats-reihe"):
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.fleet"), classes="stats-titel")
                yield PlotextPlot(id="stats-flotte")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.spend"), classes="stats-titel")
                yield PlotextPlot(id="stats-verbrauch")
        with Horizontal(classes="stats-reihe"):
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.duration"), classes="stats-titel")
                yield PlotextPlot(id="stats-dauer")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.folders"), classes="stats-titel")
                yield PlotextPlot(id="stats-ordner")
        with Horizontal(classes="stats-reihe"):
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.bus"), classes="stats-titel")
                yield PlotextPlot(id="stats-bus")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.warning"), classes="stats-titel")
                yield Static("", id="stats-warnung", markup=True)
        yield Static("", id="stats-fuss", markup=True)

    # -- Aussenseite ----------------------------------------------------

    def setze_statistik(self, statistik: Statistik | None) -> None:
        self._statistik = statistik
        self._laeuft = False
        self._zeichnen()

    def setze_laeuft(self, laeuft: bool) -> None:
        self._laeuft = laeuft
        if laeuft:
            self.query_one("#stats-kopf", Static).update(t("stats.loading"))

    # -- Zeichnen -------------------------------------------------------

    def _zeichnen(self) -> None:
        s = self._statistik
        kopf = self.query_one("#stats-kopf", Static)
        if s is None:
            kopf.update(t("stats.no_data"))
            return
        kopf.update(self._kopfzeile(s))
        self._flotte(s)
        self._verbrauch(s)
        self._dauer(s)
        self._ordner(s)
        self._bus(s)
        self.query_one("#stats-warnung", Static).update(self._warnung(s))
        self.query_one("#stats-fuss", Static).update(self._fusszeile(s))

    def _kopfzeile(self, s: Statistik) -> str:
        zeitraum = f"{s.von:%d.%m.} - {s.bis:%d.%m.%Y}" if s.von and s.bis else ""
        return (
            f"[b]{escape(zeitraum)}[/]"
            f"  ·  {t('stats.head.requests', n=_zahl(s.anfragen_gesamt))}"
            f"  ·  {t('stats.head.tokens', n=_millionen(s.tokens_gesamt))}"
            f"  ·  [#f1c40f]{t('stats.head.cache', p=f'{s.cache_anteil * 100:.1f}')}[/]"
            f"  ·  {t('stats.head.sessions', n=len(s.sitzungen))}"
            f"  ·  {t('stats.head.peak', n=s.hoechste_gleichzeitig)}"
        )

    def _kurz(self, s: Statistik) -> list[str]:
        """Tagesbeschriftung ohne Jahr - sonst ueberlappen vierzehn Balken."""
        return [f"{w.tag:%d.%m}" for w in s.tage]

    def _flotte(self, s: Statistik) -> None:
        plot = self.query_one("#stats-flotte", PlotextPlot)
        plot.plt.clear_figure()
        if s.tage:
            plot.plt.multiple_bar(  # type: ignore[call-arg]
                self._kurz(s),
                [
                    [w.hoechste_gleichzeitig for w in s.tage],
                    [w.sitzungen for w in s.tage],
                ],
                labels=[t("stats.fleet.peak"), t("stats.fleet.sessions")],
                color=[FARBE_AUS, FARBE_CACHE_GELESEN],  # type: ignore[arg-type]
            )
        plot.refresh()

    def _verbrauch(self, s: Statistik) -> None:
        """Vier Arten gestapelt - die Cache-Lesung ist der graue Riese.

        Ohne die Trennung waere das Diagramm eine einzige Aussage ueber
        Wiederholung: gemessen sind 96 bis 98 Prozent Cache.
        """
        plot = self.query_one("#stats-verbrauch", PlotextPlot)
        plot.plt.clear_figure()
        if s.tage:
            # In Millionen, nicht roh: eine Achsenbeschriftung wie
            # "1365219938.0" ist nicht lesbar und schiebt das Diagramm nach
            # rechts aus dem Feld.
            plot.plt.stacked_bar(  # type: ignore[call-arg]
                self._kurz(s),
                [
                    [round(w.cache_gelesen / 1e6, 1) for w in s.tage],
                    [round(w.cache_neu / 1e6, 1) for w in s.tage],
                    [round(w.frisch / 1e6, 1) for w in s.tage],
                    [round(w.aus / 1e6, 1) for w in s.tage],
                ],
                labels=[
                    t("stats.spend.cache_read"),
                    t("stats.spend.cache_new"),
                    t("stats.spend.fresh"),
                    t("stats.spend.out"),
                ],
                color=[  # type: ignore[arg-type]
                    FARBE_CACHE_GELESEN,
                    FARBE_CACHE_NEU,
                    FARBE_FRISCH,
                    FARBE_AUS,
                ],
            )
        plot.refresh()

    def _dauer(self, s: Statistik) -> None:
        """Was Laenge kostet: Median-Verbrauch je Korb der Sitzungsdauer."""
        plot = self.query_one("#stats-dauer", PlotextPlot)
        plot.plt.clear_figure()
        koerbe = [k for k in s.alterskoerbe if k.anzahl]
        if koerbe:
            plot.plt.bar(
                [f"{k.label} ({k.anzahl})" for k in koerbe],
                [round(k.tokens_median / 1e6, 1) for k in koerbe],
                color=FARBE_CACHE_NEU,
            )
        plot.refresh()

    def _ordner(self, s: Statistik) -> None:
        plot = self.query_one("#stats-ordner", PlotextPlot)
        plot.plt.clear_figure()
        if s.ordner:
            # Umgedreht, weil plotext waagerechte Balken von unten aufbaut -
            # ohne das steht der groesste Ordner ganz unten.
            eintraege = list(reversed(s.ordner))
            plot.plt.bar(
                [o.ordner for o in eintraege],
                [round(o.tokens / 1e6, 1) for o in eintraege],
                orientation="horizontal",
                color=FARBE_FRISCH,
            )
        plot.refresh()

    def _bus(self, s: Statistik) -> None:
        plot = self.query_one("#stats-bus", PlotextPlot)
        plot.plt.clear_figure()
        if any(w.gesamt for w in s.bustage):
            plot.plt.stacked_bar(  # type: ignore[call-arg]
                self._kurz(s),
                [
                    [w.erledigt for w in s.bustage],
                    [w.gescheitert for w in s.bustage],
                    [w.offen for w in s.bustage],
                ],
                labels=[
                    t("stats.bus.done"),
                    t("stats.bus.failed"),
                    t("stats.bus.open"),
                ],
                color=[FARBE_ERLEDIGT, FARBE_GESCHEITERT, FARBE_OFFEN],  # type: ignore[arg-type]
            )
        plot.refresh()

    def _warnung(self, s: Statistik) -> str:
        w = s.warnung
        zeilen: list[str] = []

        def zeile(wert: int, schluessel: str, gut: bool) -> str:
            farbe = "#2ecc71" if gut else "#f1c40f"
            return f"  [{farbe}]{wert:>4}[/]  {t(schluessel)}"

        for wert, schluessel in (
            (w.vererbbar_offen, "stats.warn.inheritable"),
            (w.verwaiste_auftraege, "stats.warn.orphaned"),
            (w.namen_mehrfach, "stats.warn.recycled"),
            (w.lange_sitzungen, "stats.warn.long"),
        ):
            zeilen.append(zeile(wert, schluessel, not wert))
        zeilen.append("")
        zeilen.append(f"  [dim]{t('stats.warn.long_hint', h=int(LANGE_SITZUNG_STUNDEN))}[/]")

        # Die Recyclingquote ist nur so gut wie die Zahl der benannten
        # Sitzungen - das gehoert daneben, nicht in eine Fussnote weit weg.
        zeilen.append(
            f"  [dim]{t('stats.warn.names_known', n=s.namen_bekannt, gesamt=len(s.sitzungen))}[/]"
        )
        if s.liegekoerbe and any(k.anzahl for k in s.liegekoerbe):
            zeilen.append("")
            zeilen.append(f"  [b]{t('stats.warn.waiting')}[/]")
            for k in s.liegekoerbe:
                if k.anzahl:
                    zeilen.append(f"    {k.label:>8}  {k.anzahl}")
        return "\n".join(zeilen)

    def _fusszeile(self, s: Statistik) -> str:
        teile = [t("stats.foot.measured", s=f"{s.dauer_s:.1f}")]
        if s.durchlauf_median_h is not None:
            teile.append(t("stats.foot.leadtime", h=f"{s.durchlauf_median_h:.1f}"))
        if s.annahme_median_h is not None:
            teile.append(t("stats.foot.accept", h=f"{s.annahme_median_h:.1f}"))
        return f"[dim]{escape('  ·  '.join(teile))}[/]\n[dim]{t('stats.foot.caveat')}[/]"
