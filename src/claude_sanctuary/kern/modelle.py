"""Datenmodelle des Kerns - UI-frei, von TUI und Web gleichermassen benutzt."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Kontext-Schwellen. Bewusst ABSOLUT und nicht in Prozent: das Kontextfenster
# ist nicht zuverlaessig bekannt. Der Operator erkennt das 1M-Fenster an "[1m]"
# in der Modell-ID, doch das Transkript liefert dieselbe Sitzung auch als
# schlichtes "claude-opus-5" (geprueft 01.08.2026, eigene Sitzung mit 412k
# Kontext und ID ohne Marker). Ein Prozentwert waere damit geraten.
KONTEXT_ENG = 600_000
KONTEXT_KRITISCH = 800_000


class Ampel(Enum):
    """Verfuegbarkeit eines Agenten. Eine Ampel hat drei Farben, mehr nicht."""

    FREI = "gruen"
    """Wartet auf Eingabe, kann Auftraege annehmen."""

    BESCHAEFTIGT = "gelb"
    """Arbeitet gerade."""

    WEG = "rot"
    """Nicht erreichbar oder Fehler."""


@dataclass(slots=True)
class Agent:
    """Eine laufende Claude-Code-Sitzung.

    Die Felder entsprechen der Ausgabe von ``sanctuary status --json``. Werte,
    die dort fehlen koennen, sind hier optional - nichts wird ersatzweise
    geraten.
    """

    name: str
    status: str
    rechner: str
    pid: int | None = None
    session_id: str = ""
    selbst: bool = False
    laufzeit_ms: int = 0
    gespraech_ms: int = 0
    fortgesetzt: bool = False
    post: int = 0
    kontext: int = 0
    tokens: int = 0
    cache_gelesen: int = 0
    modell: str | None = None
    version: str | None = None
    """Claude-Code-Version dieser Sitzung, aus dem Transkript."""

    system: str | None = None
    """Betriebssystem des Rechners, auf dem die Sitzung laeuft."""

    letztes_tool: str | None = None
    letzte_zeit: str = ""
    """ISO-Zeitstempel des letzten Transkript-Eintrags."""

    aufgabe: str | None = None
    cwd: str = ""
    nach_compact: bool = False
    erreichbar: bool = True

    @property
    def ampel(self) -> Ampel:
        """Verfuegbarkeit als Ampelfarbe."""
        if not self.erreichbar:
            return Ampel.WEG
        return Ampel.BESCHAEFTIGT if self.status == "busy" else Ampel.FREI

    @property
    def kontext_eng(self) -> bool:
        """Wahr, wenn ein /compact langsam faellig wird."""
        return self.kontext >= KONTEXT_ENG

    @property
    def kontext_kritisch(self) -> bool:
        """Wahr, wenn der Kontext kritisch voll ist."""
        return self.kontext >= KONTEXT_KRITISCH


@dataclass(slots=True)
class Ereignis:
    """Ein einzelner Eintrag im Verlauf eines Auftrags."""

    art: str
    """``auftrag`` fuer die Anweisung, ``quittung`` fuer die Antwort."""

    ts: str
    von: str = ""
    an: str = ""
    text: str = ""
    zustand: str = ""
    status: int | None = None
    notiz: str = ""
    host: str = ""
    """Rechner des Absenders dieses Eintrags.

    Beim Auftrag ist das ``von_host`` (wo er abgeschickt wurde), bei der
    Quittung der Rechner des Agenten. Ein blosser Name genuegt im Mesh nicht:
    derselbe Name kann auf zwei Rechnern vergeben sein, und beim Lesen ist
    nicht erkennbar, wer geantwortet hat.
    """

    @property
    def eigen(self) -> bool:
        """Wahr, wenn dieser Eintrag von uns stammt (rechte Blase)."""
        return self.art == "auftrag"

    @property
    def absender(self) -> str:
        """Absender als ``Name@RECHNER``, oder nur der Name ohne Rechner."""
        name = self.von or "?"
        return f"{name}@{self.host.upper()}" if self.host else name


@dataclass(slots=True)
class Auftrag:
    """Ein Auftrag mit Zustand, wie ihn der Bus fuehrt.

    Die Zustaende folgen dem A2A-Vokabular: submitted, working,
    input_required, completed, failed, cancelled.
    """

    auftrag_id: str
    zustand: str
    von: str = ""
    an: str = ""
    topic: str = ""
    text: str = ""
    erstellt: str = ""
    geaendert: str = ""
    quittung_erwartet: bool = False
    verlauf: list[Ereignis] = field(default_factory=list)


@dataclass(slots=True)
class Namenspool:
    """Das aktive Namensmotiv und was davon noch frei ist."""

    motiv: str = ""
    namen: list[str] = field(default_factory=list)
    """Namen des Motivs, ohne die reservierten."""

    frei: list[str] = field(default_factory=list)
    reserviert: list[str] = field(default_factory=list)
    vergeben: dict[str, str] = field(default_factory=dict)
    """Sitzungs-ID auf Name."""


@dataclass(slots=True)
class Bestand:
    """Was eine Abfrage insgesamt geliefert hat."""

    rechner: str
    zeit: str
    agenten: list[Agent] = field(default_factory=list)
    fehler: list[str] = field(default_factory=list)
    """Hosts, die nicht geantwortet haben - je Eintrag eine Meldung."""

    system: str = ""
    """Betriebssystem dieses Rechners."""

    anmeldung: str = ""
    """ISO-Zeitstempel, bis wann die Anmeldung gilt (Refresh-Token)."""

    claude_version: str = ""
    """Installierte Claude-Code-Version dieses Rechners."""

    systeme: dict[str, str] = field(default_factory=dict)
    """Rechnername auf Betriebssystem - bei Mesh mehrere Eintraege."""

    @property
    def beschaeftigt(self) -> int:
        return sum(1 for a in self.agenten if a.ampel is Ampel.BESCHAEFTIGT)

    @property
    def offene_auftraege(self) -> int:
        return sum(a.post for a in self.agenten)

    @property
    def tokens(self) -> int:
        """Verbrauch - nur belegt, wenn mit --tokens abgefragt wurde."""
        return sum(a.tokens for a in self.agenten)

    @property
    def kontext(self) -> int:
        """Summe der belegten Kontexte. Steht in jeder Abfrage."""
        return sum(a.kontext for a in self.agenten)
