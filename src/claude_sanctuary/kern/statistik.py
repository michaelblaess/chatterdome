"""Auswertung der Transkripte und des Bus - ohne jede Oberflaeche.

Woher die Zahlen kommen und was sie NICHT sagen, gemessen am 07.08.2026 auf
Michaels Bestand (116 Transkripte, 369 MB, 105.122 Zeilen):

- Ein voller Durchgang dauert **2,3 s**. Deshalb rechnet der Tab bei jedem
  Oeffnen frisch statt einen Zwischenspeicher zu pflegen, der veralten kann.
  Traegt der Durchgang eines Tages laenger, ist der Zwischenspeicher der
  naechste Schritt - nicht vorher.
- Je Anfrage stehen Zeitpunkt, Sitzung, Ordner und die vollen usage-Zahlen im
  Transkript. **96 bis 98 Prozent aller Token sind Cache-Lesungen**, deshalb
  werden die vier Arten ueberall getrennt gefuehrt. Eine Summe ueber alles
  misst hauptsaechlich Wiederholung.
- `isSidechain` steht bei 35.498 von 35.498 Anfragen auf false. Subagenten
  tauchen in diesen Dateien NICHT auf - eine Kennzahl ueber ihren Anteil waere
  frei erfunden.

**Ausgewertet wird je Sitzung, nie je Agentenname.** Ein Name ist eine Pacht:
gemessen trugen fuenf Namen bereits je zwei verschiedene Sitzungen. Eine
Auswertung je Name wuerde sie zusammenwerfen - derselbe Denkfehler, der am
07.08.2026 den Busauftrag an die falsche Marga geliefert hat.
"""

from __future__ import annotations

import json
import statistics as stat
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from claude_sanctuary.kern.modelle import (
    GESCHEITERTE_ZUSTAENDE,
    OFFENE_ZUSTAENDE,
    Auftrag,
)

FENSTER_TAGE = 14
"""Vorgabe fuer den Auswertungszeitraum. Vierzehn Balken passen in ein
Terminaldiagramm, ohne dass die Achsenbeschriftung ueberlappt."""

LANGE_SITZUNG_STUNDEN = 24.0
"""Ab wann eine Sitzung in der Fruehwarnung als langlebig gilt."""

# Die Koerbe der Sitzungsdauer. Grenzen in Stunden, offen nach oben.
ALTERSKOERBE: tuple[tuple[str, float, float], ...] = (
    ("0-2 h", 0.0, 2.0),
    ("2-8 h", 2.0, 8.0),
    ("8-24 h", 8.0, 24.0),
    ("> 24 h", 24.0, float("inf")),
)

# Koerbe fuer die Liegezeit offener Auftraege, ebenfalls in Stunden.
LIEGEKOERBE: tuple[tuple[str, float, float], ...] = (
    ("< 1 h", 0.0, 1.0),
    ("1-6 h", 1.0, 6.0),
    ("6-24 h", 6.0, 24.0),
    ("> 24 h", 24.0, float("inf")),
)


# ---------------------------------------------------------------------------
# Rohdaten
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Anfrage:
    """Eine einzelne Anfrage an das Modell, wie sie im Transkript steht."""

    ts: datetime
    sitzung: str
    ordner: str
    frisch: int = 0
    cache_neu: int = 0
    cache_gelesen: int = 0
    aus: int = 0

    @property
    def gesamt(self) -> int:
        return self.frisch + self.cache_neu + self.cache_gelesen + self.aus

    @property
    def echt(self) -> int:
        """Alles ausser der Cache-Lesung - also das, was neu verarbeitet wurde."""
        return self.frisch + self.cache_neu + self.aus


def _zeitpunkt(roh: object) -> datetime | None:
    if not isinstance(roh, str) or not roh:
        return None
    try:
        wert = datetime.fromisoformat(roh.replace("Z", "+00:00"))
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=UTC)


def lies_anfragen(projekte: Path) -> Iterator[Anfrage]:
    """Liest alle Modellanfragen aus den Transkripten.

    Der Vorfilter auf die Zeichenkette spart das Zerlegen von rund zwei
    Dritteln der Zeilen - ohne ihn dauert der Durchgang ein Vielfaches. Eine
    unlesbare Zeile wird uebersprungen und nicht gemeldet: Transkripte werden
    waehrend des Lesens weitergeschrieben, eine halbe letzte Zeile ist normal.
    """
    if not projekte.is_dir():
        return
    # Ordnername je cwd zwischenspeichern. Ohne diesen Zwischenspeicher baut
    # die Schleife 35.616 Path-Objekte fuer eine Handvoll verschiedener Pfade -
    # gemessen 7,7 s gegenueber 2,3 s mit.
    ordnernamen: dict[str, str] = {}
    for datei in sorted(projekte.glob("*/*.jsonl")):
        try:
            with datei.open(encoding="utf-8", errors="replace") as strom:
                for zeile in strom:
                    if '"assistant"' not in zeile:
                        continue
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict) or satz.get("type") != "assistant":
                        continue
                    wann = _zeitpunkt(satz.get("timestamp"))
                    nachricht = satz.get("message")
                    verbrauch = nachricht.get("usage") if isinstance(nachricht, dict) else None
                    if wann is None or not isinstance(verbrauch, dict):
                        continue
                    roh_ordner = satz.get("cwd")
                    ordner = ""
                    if roh_ordner:
                        schluessel = str(roh_ordner)
                        ordner = ordnernamen.get(schluessel, "")
                        if not ordner:
                            ordner = Path(schluessel).name or schluessel
                            ordnernamen[schluessel] = ordner
                    yield Anfrage(
                        ts=wann,
                        sitzung=str(satz.get("sessionId") or ""),
                        ordner=ordner,
                        frisch=_zahl(verbrauch.get("input_tokens")),
                        cache_neu=_zahl(verbrauch.get("cache_creation_input_tokens")),
                        cache_gelesen=_zahl(verbrauch.get("cache_read_input_tokens")),
                        aus=_zahl(verbrauch.get("output_tokens")),
                    )
        except OSError:
            # Eine Datei, die gerade ersetzt wird, darf die Auswertung nicht
            # abbrechen - die uebrigen 115 sind trotzdem auswertbar.
            continue


def _zahl(roh: object) -> int:
    """Eine Zahl aus dem Transkript, oder 0. Fehlende Felder sind normal."""
    if isinstance(roh, bool) or not isinstance(roh, int | float | str):
        return 0
    try:
        return int(roh)
    except (TypeError, ValueError):
        return 0


def lies_namen(projekte: Path) -> dict[str, str]:
    """Sitzung auf Agentennamen, aus den Transkripten.

    Der Name steht als eigener Datensatz ``agent-name`` in den ersten Zeilen,
    mit dem Ordner als Zusatz (``Marga · BUERO_PC2``). Nur der Teil vor dem
    Trenner ist der Poolname.

    Gemessen tragen 22 von 100 Transkripten einen Namen - der SessionStart-Hook
    ist juenger als der Bestand. Jede Auswertung darauf ist also eine
    Untergrenze und muss so beschriftet werden.
    """
    namen: dict[str, str] = {}
    if not projekte.is_dir():
        return namen
    for datei in sorted(projekte.glob("*/*.jsonl")):
        try:
            with datei.open(encoding="utf-8", errors="replace") as strom:
                for nummer, zeile in enumerate(strom):
                    # Der Datensatz steht immer im Kopf der Datei. Ohne diese
                    # Grenze liest die Funktion 369 MB fuer 100 Zeichenketten.
                    if nummer > 60:
                        break
                    if '"agent-name"' not in zeile:
                        continue
                    try:
                        satz = json.loads(zeile)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(satz, dict) or satz.get("type") != "agent-name":
                        continue
                    roh = str(satz.get("agentName") or "")
                    name = roh.split("·")[0].strip()
                    sitzung = str(satz.get("sessionId") or datei.stem)
                    if name:
                        namen[sitzung] = name
                    break
        except OSError:
            continue
    return namen


# ---------------------------------------------------------------------------
# Verdichtungen
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Tageswert:
    """Verbrauch eines Kalendertages, nach Art getrennt."""

    tag: date
    frisch: int = 0
    cache_neu: int = 0
    cache_gelesen: int = 0
    aus: int = 0
    anfragen: int = 0
    sitzungen: int = 0
    hoechste_gleichzeitig: int = 0

    @property
    def gesamt(self) -> int:
        return self.frisch + self.cache_neu + self.cache_gelesen + self.aus

    @property
    def echt(self) -> int:
        return self.frisch + self.cache_neu + self.aus

    @property
    def cache_anteil(self) -> float:
        """Anteil der Cache-Lesungen am Gesamtverbrauch, 0 bis 1."""
        return self.cache_gelesen / self.gesamt if self.gesamt else 0.0


@dataclass(slots=True)
class Sitzungsspanne:
    """Eine Sitzung mit ihrem aktiven Zeitraum und Verbrauch."""

    kennung: str
    ordner: str = ""
    name: str = ""
    beginn: datetime | None = None
    ende: datetime | None = None
    anfragen: int = 0
    tokens: int = 0
    echt: int = 0

    @property
    def stunden(self) -> float:
        """Aktive Dauer: erste bis letzte Anfrage.

        NICHT die Lebensdauer des Fensters - eine Sitzung, die drei Stunden
        ruht, zaehlt diese Zeit hier trotzdem mit, eine die nach der letzten
        Anfrage noch offen steht dagegen nicht.
        """
        if self.beginn is None or self.ende is None:
            return 0.0
        return (self.ende - self.beginn).total_seconds() / 3600.0


@dataclass(slots=True)
class Korb:
    """Ein Auswertungskorb mit Beschriftung und Inhalt."""

    label: str
    anzahl: int = 0
    tokens_median: int = 0


@dataclass(slots=True)
class Ordnerwert:
    ordner: str
    tokens: int = 0
    echt: int = 0
    anfragen: int = 0


@dataclass(slots=True)
class Bustag:
    """Ein Tag im Bus, nach dem Ausgang der Auftraege getrennt."""

    tag: date
    erledigt: int = 0
    gescheitert: int = 0
    offen: int = 0

    @property
    def gesamt(self) -> int:
        return self.erledigt + self.gescheitert + self.offen


@dataclass(slots=True)
class Fruehwarnung:
    """Vier Zahlen, die ein Problem melden, bevor es auffaellt."""

    vererbbar_offen: int = 0
    """Offene Auftraege an einen NAMEN statt an eine Sitzung."""

    namen_mehrfach: int = 0
    """Namen, die im Zeitraum mehr als eine Sitzung getragen haben."""

    verwaiste_auftraege: int = 0
    """Offene Auftraege, deren Empfaengersitzung nicht mehr laeuft."""

    lange_sitzungen: int = 0
    """Sitzungen, die laenger als LANGE_SITZUNG_STUNDEN aktiv waren."""


@dataclass(slots=True)
class Statistik:
    """Alles, was das Dashboard zeigt."""

    von: date | None = None
    bis: date | None = None
    tage: list[Tageswert] = field(default_factory=list)
    sitzungen: list[Sitzungsspanne] = field(default_factory=list)
    alterskoerbe: list[Korb] = field(default_factory=list)
    ordner: list[Ordnerwert] = field(default_factory=list)
    bustage: list[Bustag] = field(default_factory=list)
    liegekoerbe: list[Korb] = field(default_factory=list)
    durchlauf_median_h: float | None = None
    annahme_median_h: float | None = None
    warnung: Fruehwarnung = field(default_factory=Fruehwarnung)
    anfragen_gesamt: int = 0
    dauer_s: float = 0.0
    namen_bekannt: int = 0
    """Wie viele Sitzungen einen Agentennamen tragen - Nenner der Recyclingquote."""

    @property
    def leer(self) -> bool:
        return not self.tage and not self.sitzungen

    @property
    def tokens_gesamt(self) -> int:
        return sum(t.gesamt for t in self.tage)

    @property
    def cache_anteil(self) -> float:
        gesamt = self.tokens_gesamt
        return sum(t.cache_gelesen for t in self.tage) / gesamt if gesamt else 0.0

    @property
    def hoechste_gleichzeitig(self) -> int:
        return max((t.hoechste_gleichzeitig for t in self.tage), default=0)


def _median(werte: list[float]) -> float:
    return stat.median(werte) if werte else 0.0


def spannen(anfragen: list[Anfrage], namen: dict[str, str]) -> list[Sitzungsspanne]:
    """Fasst die Anfragen je Sitzung zu einer Spanne zusammen."""
    gesammelt: dict[str, Sitzungsspanne] = {}
    for a in anfragen:
        if not a.sitzung:
            continue
        s = gesammelt.get(a.sitzung)
        if s is None:
            s = Sitzungsspanne(kennung=a.sitzung, ordner=a.ordner, name=namen.get(a.sitzung, ""))
            gesammelt[a.sitzung] = s
        if s.beginn is None or a.ts < s.beginn:
            s.beginn = a.ts
        if s.ende is None or a.ts > s.ende:
            s.ende = a.ts
        if a.ordner and not s.ordner:
            s.ordner = a.ordner
        s.anfragen += 1
        s.tokens += a.gesamt
        s.echt += a.echt
    return sorted(gesammelt.values(), key=lambda s: s.beginn or datetime.min.replace(tzinfo=UTC))


def hoechste_gleichzeitigkeit(spannen_liste: list[Sitzungsspanne], tag: date) -> int:
    """Wie viele Sitzungen waren an diesem Tag gleichzeitig aktiv, hoechstens?

    Klassischer Intervall-Sweep ueber die auf den Tag beschnittenen Spannen.
    Die Zahl ist rueckwirkend aus den Transkripten zu haben - es musste dafuer
    nie etwas mitgeschrieben werden.
    """
    beginn = datetime.combine(tag, datetime.min.time(), tzinfo=UTC)
    ende = beginn + timedelta(days=1)
    punkte: list[tuple[datetime, int]] = []
    for s in spannen_liste:
        if s.beginn is None or s.ende is None or s.ende < beginn or s.beginn >= ende:
            continue
        punkte.append((max(s.beginn, beginn), 1))
        punkte.append((min(s.ende, ende), -1))
    if not punkte:
        return 0
    # Bei gleichem Zeitpunkt zuerst schliessen (-1 vor +1), sonst zaehlt eine
    # Sitzung, die genau endet, wenn die naechste beginnt, als Ueberlappung.
    punkte.sort(key=lambda p: (p[0], p[1]))
    laufend = 0
    hoch = 0
    for _, delta in punkte:
        laufend += delta
        hoch = max(hoch, laufend)
    return hoch


def tagesreihe(
    anfragen: list[Anfrage],
    spannen_liste: list[Sitzungsspanne],
    *,
    von: date,
    bis: date,
) -> list[Tageswert]:
    """Eine Zeile je Kalendertag, auch fuer Tage ohne Verbrauch.

    Luecken bleiben als Nullbalken stehen: ein Diagramm, das arbeitsfreie Tage
    einfach weglaesst, staucht die Zeitachse und suggeriert Durchgaengigkeit.
    """
    werte: dict[date, Tageswert] = {}
    tag = von
    while tag <= bis:
        werte[tag] = Tageswert(tag=tag)
        tag += timedelta(days=1)

    sitzungen_je_tag: defaultdict[date, set[str]] = defaultdict(set)
    for a in anfragen:
        d = a.ts.date()
        eintrag = werte.get(d)
        if eintrag is None:
            continue
        eintrag.frisch += a.frisch
        eintrag.cache_neu += a.cache_neu
        eintrag.cache_gelesen += a.cache_gelesen
        eintrag.aus += a.aus
        eintrag.anfragen += 1
        sitzungen_je_tag[d].add(a.sitzung)

    for d, eintrag in werte.items():
        eintrag.sitzungen = len(sitzungen_je_tag.get(d, ()))
        eintrag.hoechste_gleichzeitig = hoechste_gleichzeitigkeit(spannen_liste, d)
    return [werte[d] for d in sorted(werte)]


def alterskoerbe(spannen_liste: list[Sitzungsspanne]) -> list[Korb]:
    """Sitzungen nach aktiver Dauer, mit dem Median ihres Verbrauchs.

    Median und nicht Mittelwert: eine einzelne 330-Stunden-Sitzung wuerde den
    Mittelwert ihres Korbs allein bestimmen.
    """
    koerbe = [Korb(label=name) for name, _, _ in ALTERSKOERBE]
    tokens: list[list[float]] = [[] for _ in ALTERSKOERBE]
    for s in spannen_liste:
        dauer = s.stunden
        for i, (_, unten, oben) in enumerate(ALTERSKOERBE):
            if unten <= dauer < oben:
                koerbe[i].anzahl += 1
                tokens[i].append(float(s.tokens))
                break
    for i, korb in enumerate(koerbe):
        korb.tokens_median = int(_median(tokens[i]))
    return koerbe


def ordnerwerte(anfragen: list[Anfrage], grenze: int = 8) -> list[Ordnerwert]:
    """Verbrauch je Arbeitsordner, die groessten zuerst."""
    gesammelt: dict[str, Ordnerwert] = {}
    for a in anfragen:
        name = a.ordner or "?"
        eintrag = gesammelt.get(name)
        if eintrag is None:
            eintrag = Ordnerwert(ordner=name)
            gesammelt[name] = eintrag
        eintrag.tokens += a.gesamt
        eintrag.echt += a.echt
        eintrag.anfragen += 1
    geordnet = sorted(gesammelt.values(), key=lambda o: -o.tokens)
    return geordnet[:grenze]


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


def _auftragszeit(iso: str) -> datetime | None:
    return _zeitpunkt(iso)


def bustage(auftraege: list[Auftrag], *, von: date, bis: date) -> list[Bustag]:
    """Auftraege je Tag ihres Eingangs, nach Ausgang getrennt."""
    werte: dict[date, Bustag] = {}
    tag = von
    while tag <= bis:
        werte[tag] = Bustag(tag=tag)
        tag += timedelta(days=1)
    for a in auftraege:
        wann = _auftragszeit(a.erstellt)
        if wann is None:
            continue
        eintrag = werte.get(wann.date())
        if eintrag is None:
            continue
        if a.zustand in OFFENE_ZUSTAENDE:
            eintrag.offen += 1
        elif a.zustand in GESCHEITERTE_ZUSTAENDE:
            eintrag.gescheitert += 1
        else:
            eintrag.erledigt += 1
    return [werte[d] for d in sorted(werte)]


def liegekoerbe(auftraege: list[Auftrag], jetzt: datetime | None = None) -> list[Korb]:
    """Wie lange die noch offenen Auftraege schon liegen."""
    bezug = jetzt or datetime.now(UTC)
    koerbe = [Korb(label=name) for name, _, _ in LIEGEKOERBE]
    for a in auftraege:
        if a.zustand not in OFFENE_ZUSTAENDE:
            continue
        wann = _auftragszeit(a.erstellt)
        if wann is None:
            continue
        stunden = (bezug - wann).total_seconds() / 3600.0
        for i, (_, unten, oben) in enumerate(LIEGEKOERBE):
            if unten <= stunden < oben:
                koerbe[i].anzahl += 1
                break
    return koerbe


def durchlaufzeiten(auftraege: list[Auftrag]) -> tuple[float | None, float | None]:
    """Median der Zeit bis zur Erledigung und bis zur Annahme, in Stunden.

    Zwei verschiedene Aussagen: die Zeit bis zur **Annahme** (Quittung 202)
    misst, wie schnell ein Agent ueberhaupt hinsieht. Die Zeit bis zum
    **Endzustand** misst die Arbeit. Wer nur eine davon zeigt, verwechselt
    Erreichbarkeit mit Geschwindigkeit.
    """
    fertig: list[float] = []
    angenommen: list[float] = []
    for a in auftraege:
        beginn = _auftragszeit(a.erstellt)
        if beginn is None:
            continue
        if a.zustand not in OFFENE_ZUSTAENDE:
            ende = _auftragszeit(a.geaendert)
            if ende is not None:
                fertig.append((ende - beginn).total_seconds() / 3600.0)
        for e in a.verlauf:
            if e.art == "quittung" and e.status == 202:
                wann = _auftragszeit(e.ts)
                if wann is not None:
                    angenommen.append((wann - beginn).total_seconds() / 3600.0)
                break
    return (
        _median(fertig) if fertig else None,
        _median(angenommen) if angenommen else None,
    )


def fruehwarnung(
    auftraege: list[Auftrag],
    spannen_liste: list[Sitzungsspanne],
    laufende: set[str],
) -> Fruehwarnung:
    """Die vier Zahlen der Ampelsektion.

    :param laufende:
        Session-IDs der aktuell laufenden Instanzen. Ist die Menge leer, wird
        die Waisenzahl NICHT berechnet - eine leere Instanzliste kann auch aus
        einem Fehler stammen, und daraus jeden Auftrag als verwaist zu melden
        waere ein Fehlalarm auf ganzer Breite.
    """
    warnung = Fruehwarnung()
    for a in auftraege:
        if a.zustand not in OFFENE_ZUSTAENDE:
            continue
        if not a.an_session:
            warnung.vererbbar_offen += 1
        elif laufende and a.an_session not in laufende:
            warnung.verwaiste_auftraege += 1

    je_name: Counter[str] = Counter(s.name for s in spannen_liste if s.name)
    warnung.namen_mehrfach = sum(1 for anzahl in je_name.values() if anzahl > 1)
    warnung.lange_sitzungen = sum(
        1 for s in spannen_liste if s.stunden > LANGE_SITZUNG_STUNDEN
    )
    return warnung


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------


def lade_statistik(
    projekte: Path,
    auftraege: list[Auftrag] | None = None,
    *,
    tage: int = FENSTER_TAGE,
    laufende: set[str] | None = None,
    jetzt: datetime | None = None,
) -> Statistik:
    """Liest alles ein und verdichtet es.

    :param projekte: das Verzeichnis ``~/.claude/projects``.
    :param auftraege: der Busbestand, oder None fuer die reine Flottenansicht.
    :param laufende: Session-IDs der laufenden Instanzen, fuer die Waisenzahl.
    :param jetzt: Bezugszeit. Nur fuer Tests von aussen zu setzen.
    """
    from time import monotonic

    start = monotonic()
    bezug = jetzt or datetime.now(UTC)
    bis = bezug.date()
    von = bis - timedelta(days=tage - 1)
    grenze = datetime.combine(von, datetime.min.time(), tzinfo=UTC)

    alle = list(lies_anfragen(projekte))
    namen = lies_namen(projekte)
    # Spannen ueber ALLE Anfragen bilden, dann filtern: eine Sitzung, die vor
    # dem Fenster begann und hineinreicht, haette sonst einen falschen Beginn
    # und damit eine zu kurze Dauer.
    alle_spannen = spannen(alle, namen)
    im_fenster = [s for s in alle_spannen if s.ende is not None and s.ende >= grenze]
    anfragen = [a for a in alle if a.ts >= grenze]

    liste = auftraege or []
    fertig, annahme = durchlaufzeiten(liste)
    return Statistik(
        von=von,
        bis=bis,
        tage=tagesreihe(anfragen, im_fenster, von=von, bis=bis),
        sitzungen=im_fenster,
        alterskoerbe=alterskoerbe(im_fenster),
        ordner=ordnerwerte(anfragen),
        bustage=bustage(liste, von=von, bis=bis),
        liegekoerbe=liegekoerbe(liste, bezug),
        durchlauf_median_h=fertig,
        annahme_median_h=annahme,
        warnung=fruehwarnung(liste, im_fenster, laufende or set()),
        anfragen_gesamt=len(anfragen),
        dauer_s=monotonic() - start,
        namen_bekannt=sum(1 for s in im_fenster if s.name),
    )
