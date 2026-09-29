"""Sechs Sektionen aus den Transkripten und dem Bus.

Gezeichnet wird mit plotext ueber textual-plotext, wie in jira-timesheet -
beide MIT-lizenziert und damit vertraeglich mit Apache 2.0.

Zur Anordnung: drei Reihen zu zwei Sektionen. Ein einspaltiges Dashboard
zwingt zum Scrollen, bevor die zweite Zahl sichtbar ist, und die Aussagen
stehen hier paarweise - Parallelbetrieb neben Verbrauch, Dauer neben Ordner,
Bus neben Warnung.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static
from textual_plotext import PlotextPlot

from chatterdome.i18n import format_number, t
from chatterdome.kern.statistik import LANGE_SITZUNG_STUNDEN, Statistik
from chatterdome.tui.widgets.balken import balken

# Farben der Verbrauchsarten. plotext nimmt Namen aus seiner eigenen Palette,
# nicht die Hexwerte der Oberflaeche.
FARBE_FRISCH = "green"
FARBE_CACHE_NEU = "orange"
FARBE_GRAU = "gray"
FARBE_AUS = "cyan"

FARBE_ERLEDIGT = "green"
FARBE_GESCHEITERT = "red"
FARBE_OFFEN = "orange"


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
                yield Static(t("stats.parallel"), classes="stats-titel")
                yield PlotextPlot(id="stats-parallel")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.spend"), classes="stats-titel")
                yield PlotextPlot(id="stats-verbrauch")
        with Horizontal(classes="stats-reihe"):
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.duration"), classes="stats-titel")
                yield PlotextPlot(id="stats-dauer")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.folders"), classes="stats-titel")
                # Der Rahmen sitzt am Scrollbereich, nicht am Text: so
                # erscheint die Leiste INNERHALB des Kastens, sobald mehr
                # Ordner da sind, als hineinpassen. Ohne das schnitte der
                # Kasten still ab, und stilles Abschneiden ist der schlimmere
                # Fehler - man sieht ihm nicht an, dass etwas fehlt.
                with VerticalScroll(classes="stats-kasten"):
                    yield Static("", id="stats-ordner", markup=True)
        with Horizontal(classes="stats-reihe"):
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.bus"), classes="stats-titel")
                yield PlotextPlot(id="stats-bus")
            with Vertical(classes="stats-feld"):
                yield Static(t("stats.warning"), classes="stats-titel")
                with VerticalScroll(classes="stats-kasten"):
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
        self._parallel(s)
        self._verbrauch(s)
        self._dauer(s)
        self.query_one("#stats-ordner", Static).update(self._ordner(s))
        self._bus(s)
        self.query_one("#stats-warnung", Static).update(self._warnung(s))
        self.query_one("#stats-fuss", Static).update(self._fusszeile(s))

    def _kopfzeile(self, s: Statistik) -> str:
        zeitraum = f"{s.von:%d.%m.} - {s.bis:%d.%m.%Y}" if s.von and s.bis else ""
        # Die Subagenten stehen nur da, wenn es welche gibt. Ein "davon 0" in
        # jeder Kopfzeile waere Rauschen - die meisten Zeitraeume haben keine.
        subagenten = (
            f"  ·  [dim]{t('stats.head.subagents', n=format_number(s.subagent_anfragen, 0))}[/]"
            if s.subagent_anfragen
            else ""
        )
        return (
            f"[b]{escape(zeitraum)}[/]"
            f"  ·  {t('stats.head.requests', n=format_number(s.anfragen_gesamt, 0))}{subagenten}"
            f"  ·  {t('stats.head.tokens', n=format_number(s.tokens_gesamt / 1e6, 1))}"
            f"  ·  [#f1c40f]{t('stats.head.cache', p=format_number(s.cache_anteil * 100, 1))}[/]"
            f"  ·  {t('stats.head.sessions', n=len(s.sitzungen))}"
            f"  ·  {t('stats.head.peak', n=s.hoechste_gleichzeitig)}"
        )

    def _kurz(self, s: Statistik) -> list[str]:
        """Tagesbeschriftung ohne Jahr - sonst ueberlappen vierzehn Balken."""
        return [f"{w.tag:%d.%m}" for w in s.tage]

    def _parallel(self, s: Statistik) -> None:
        plot = self.query_one("#stats-parallel", PlotextPlot)
        plot.plt.clear_figure()
        if s.tage:
            plot.plt.multiple_bar(  # type: ignore[call-arg]
                self._kurz(s),
                [
                    [w.hoechste_gleichzeitig for w in s.tage],
                    [w.sitzungen for w in s.tage],
                ],
                labels=[t("stats.parallel.peak"), t("stats.parallel.sessions")],
                color=[FARBE_AUS, FARBE_GRAU],  # type: ignore[arg-type]
            )
        plot.refresh()

    def _verbrauch(self, s: Statistik) -> None:
        """Der Verbrauch OHNE die Cache-Lesung.

        Der erste Entwurf stapelte alle vier Arten. Am echten Bestand war das
        Diagramm danach zu 97 Prozent grau: die Cache-Lesung erdrueckt die
        drei anderen so vollstaendig, dass von der Trennung nichts mehr zu
        sehen war - ein Balken in einer Farbe, also dieselbe Aussage wie eine
        blosse Summe.

        Hier stehen deshalb die drei Arten, die tatsaechlich verarbeitet
        wurden. Sie sind der Teil, den man beeinflussen kann. Die Cache-Quote
        selbst steht als eine Zahl in der Kopfzeile - dort ist sie besser
        aufgehoben als in einem Balken, der jeden Tag gleich aussieht.
        """
        plot = self.query_one("#stats-verbrauch", PlotextPlot)
        plot.plt.clear_figure()
        if s.tage:
            # In Millionen, nicht roh: eine Achsenbeschriftung wie
            # "1365219938.0" ist nicht lesbar und schiebt das Diagramm nach
            # rechts aus dem Feld. NICHT runden - die Achsenbeschriftung baut
            # plotext ohnehin aus dem Wertebereich, und ein gerundeter Wert
            # laesst einen kleinen Tag ganz verschwinden.
            plot.plt.stacked_bar(  # type: ignore[call-arg]
                self._kurz(s),
                [
                    [w.cache_neu / 1e6 for w in s.tage],
                    [w.frisch / 1e6 for w in s.tage],
                    [w.aus / 1e6 for w in s.tage],
                ],
                labels=[
                    t("stats.spend.cache_new"),
                    t("stats.spend.fresh"),
                    t("stats.spend.out"),
                ],
                color=[FARBE_CACHE_NEU, FARBE_FRISCH, FARBE_AUS],  # type: ignore[arg-type]
            )
        plot.refresh()

    def _dauer(self, s: Statistik) -> None:
        """Median-Verbrauch je Korb der Sitzungsdauer."""
        plot = self.query_one("#stats-dauer", PlotextPlot)
        plot.plt.clear_figure()
        koerbe = [k for k in s.alterskoerbe if k.anzahl]
        if koerbe:
            plot.plt.bar(
                [f"{k.label} ({k.anzahl})" for k in koerbe],
                [k.tokens_median / 1e6 for k in koerbe],
                color=FARBE_CACHE_NEU,
            )
        plot.refresh()

    def _ordner(self, s: Statistik) -> str:
        """Eine Zeile je Ordner, mit Textbalken statt Diagramm.

        Zwei Gruende gegen plotext an dieser Stelle. Erstens verteilt es sechs
        waagerechte Balken auf zwoelf Zeilen und beschriftet nur jede zweite -
        das sieht aus wie sechs leere Balken zwischen den vollen, und genau so
        hat Michael es gemeldet. Zweitens ist hier Platz fuer die Zahl neben
        dem Balken, und die sagt mehr als eine Achse.

        Gezaehlt wird das VERARBEITETE, nicht die Gesamtsumme - dasselbe Mass
        wie im Verbrauchsdiagramm daneben. Vorher standen hier 1.965,7
        Millionen fuer einen Ordner, also fast zwei Milliarden Token, wovon 97
        Prozent wiederholt gelesener Kontext waren. Zwei Diagramme mit zwei
        verschiedenen Bedeutungen von "Verbrauch" nebeneinander waren schlicht
        ein Fehler.
        """
        if not s.ordner:
            return f"[dim]{t('stats.no_data')}[/]"
        eintraege = s.ordner[:6]
        groesster = max(o.echt for o in eintraege) or 1
        breite = max(len(o.ordner) for o in eintraege)
        zeilen = []
        for o in eintraege:
            zahl = format_number(o.echt / 1e6, 1)
            zeilen.append(
                f"  {escape(o.ordner):<{breite}}  "
                f"[#2ecc71]{balken(o.echt / groesster, 26)}[/]"
                f"  {zahl:>8} M"
            )
        return "\n".join(zeilen)

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
        # Eine Zeile statt einer je Korb: der Kasten hat seit dem Rahmen zehn
        # Zeilen Platz, und vier belegte Koerbe haetten ihn stumm abgeschnitten.
        # Ein Kasten, der still abschneidet, ist schlimmer als eine dichte Zeile.
        belegt = [k for k in s.liegekoerbe if k.anzahl]
        if belegt:
            werte = "  ".join(f"{k.label}: {k.anzahl}" for k in belegt)
            zeilen.append("")
            zeilen.append(f"  [b]{t('stats.warn.waiting')}[/]  {werte}")
        return "\n".join(zeilen)

    def _fusszeile(self, s: Statistik) -> str:
        teile = [t("stats.foot.measured", s=format_number(s.dauer_s, 1))]
        if s.durchlauf_median_h is not None:
            teile.append(t("stats.foot.leadtime", h=format_number(s.durchlauf_median_h, 1)))
        if s.annahme_median_h is not None:
            teile.append(t("stats.foot.accept", h=format_number(s.annahme_median_h, 1)))
        return f"[dim]{escape('  ·  '.join(teile))}[/]\n[dim]{t('stats.foot.caveat')}[/]"
