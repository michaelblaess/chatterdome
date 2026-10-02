"""Die Quelle des Demo-Modus: erfundene Agenten und ein erfundener Bus.

Erfuellt das ganze Protokoll ``Quelle``, ohne einen Unterprozess zu starten.
Was die Oberflaeche aendert (senden, stoppen), wirkt auf den eigenen Bestand -
so bleibt die Demo bedienbar und zeigt die Folgen.
"""

from __future__ import annotations

import itertools
import threading
from datetime import UTC, datetime, timedelta

from chatterdome.i18n import t
from chatterdome.kern import demo_texte
from chatterdome.kern.demo_daten import arbeitsordner, sitzung
from chatterdome.kern.demo_texte import CLAUDE_VERSION, RECHNER_SYSTEME, sprache
from chatterdome.kern.modelle import Agent, Auftrag, Bestand, Busbestand, Ereignis, Namenspool
from chatterdome.kern.umgebung import DEMO_RECHNER

_BUS: dict[str, list[tuple[str, str, str, str, str, int]]] = {
    "de": [
        ("Sirius", "Spica", "Wie oft läuft das Backup der Messdaten?", "completed",
         "Jede Nacht um 3 Uhr, die Messdaten liegen in /srv/weather.", 95),
        ("Vega", "Rigel", "Kannst Du die Farbpalette als JSON exportieren?", "completed",
         "Liegt unter palette.json, 16 Einträge.", 70),
        ("Deneb", "Sirius", "Welche API nutzt Du für die Regenvorhersage?", "completed",
         "Open-Meteo, stündlich, ohne Schlüssel.", 52),
        ("Altair", "Vega", "Brauchst Du noch Testdaten für den Import?", "working", "", 12),
        ("Spica", "Capella", "Bitte die Grafana-Alarme der letzten Woche sichten.",
         "submitted", "", 35),
        ("Rigel", "Deneb", "Hast Du ein Beispiel für ein Höhenprofil als SVG?", "completed",
         "Ja, siehe profile-demo.svg im Projektordner.", 140),
        ("Sirius", "Altair", "Läuft die Uhr auch im Browser?", "failed",
         "Keine Antwort nach 10 Minuten.", 220),
        ("Vega", "Spica", "Kannst Du restic check für heute Nacht einplanen?", "completed",
         "Eingeplant, Ergebnis kommt per ntfy.", 300),
    ],
    "en": [
        ("Sirius", "Spica", "How often does the sensor data backup run?", "completed",
         "Every night at 3 am, the readings live in /srv/weather.", 95),
        ("Vega", "Rigel", "Can you export the colour palette as JSON?", "completed",
         "It is in palette.json, 16 entries.", 70),
        ("Deneb", "Sirius", "Which API do you use for the rain forecast?", "completed",
         "Open-Meteo, hourly, no key needed.", 52),
        ("Altair", "Vega", "Do you still need test data for the import?", "working", "", 12),
        ("Spica", "Capella", "Please go through last week's Grafana alerts.", "submitted",
         "", 35),
        ("Rigel", "Deneb", "Do you have an elevation profile example as SVG?", "completed",
         "Yes, see profile-demo.svg in the project folder.", 140),
        ("Sirius", "Altair", "Does the clock also run in the browser?", "failed",
         "No answer after 10 minutes.", 220),
        ("Vega", "Spica", "Can you schedule restic check for tonight?", "completed",
         "Scheduled, the result will arrive via ntfy.", 300),
    ],
}
"""(von, an, text, zustand, antwort, minuten her) - der vorbereitete Bus.

Die Namen sind die Sterne der Vorlage, ``DemoQuelle`` uebersetzt sie ins gewaehlte Motiv."""


def _stempel(wann: datetime) -> str:
    return wann.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _rechner_von(name: str) -> str:
    for agent in demo_texte.agenten():
        if agent.name == name:
            return agent.rechner
    return DEMO_RECHNER


class DemoQuelle:
    """Erfundene Agenten auf drei erfundenen Rechnern."""

    def __init__(self, sprache_wert: str = "en", jetzt: datetime | None = None) -> None:
        self._lang = sprache(sprache_wert)
        self._start = jetzt or datetime.now(UTC)
        self._sperre = threading.Lock()
        self._kennung = itertools.count(1)
        self._agenten = [self._agent(a.name) for a in demo_texte.agenten()]
        self._auftraege = [
            self._bus_eintrag(demo_texte.name(von), demo_texte.name(an), text, zustand,
                              antwort, minuten)
            for von, an, text, zustand, antwort, minuten in _BUS[self._lang]
        ]

    # -- Aufbau ------------------------------------------------------------

    def _agent(self, name: str) -> Agent:
        vorlage = next(a for a in demo_texte.agenten() if a.name == name)
        aktiv = self._start - timedelta(minutes=vorlage.minuten_seit_aktiv)
        return Agent(
            name=vorlage.name,
            status=vorlage.status,
            rechner=vorlage.rechner,
            pid=4000 + len(vorlage.name) * 97,
            session_id=sitzung(vorlage.name),
            laufzeit_ms=vorlage.laufzeit_minuten * 60_000,
            gespraech_ms=vorlage.laufzeit_minuten * 60_000 // 3,
            post=vorlage.post,
            kontext=vorlage.kontext,
            tokens=vorlage.tokens,
            cache_gelesen=vorlage.tokens * 6,
            modell=vorlage.modell,
            version=CLAUDE_VERSION,
            system=RECHNER_SYSTEME[vorlage.rechner],
            letztes_tool=vorlage.letztes_tool,
            letzte_zeit=_stempel(aktiv),
            aufgabe=vorlage.aufgabe_de if self._lang == "de" else vorlage.aufgabe_en,
            cwd=arbeitsordner(vorlage.rechner, vorlage.projekt),
        )

    def _bus_eintrag(self, von: str, an: str, text: str, zustand: str, antwort: str,
                     minuten: int) -> Auftrag:
        erstellt = self._start - timedelta(minutes=minuten)
        von_host, an_host = _rechner_von(von), _rechner_von(an)
        verlauf = [Ereignis("auftrag", _stempel(erstellt), von=von, an=an, text=text,
                            zustand="submitted", host=von_host, an_host=an_host)]
        geaendert = erstellt
        if zustand in ("completed", "failed"):
            geaendert = erstellt + timedelta(minutes=3)
            verlauf.append(Ereignis("quittung", _stempel(geaendert), von=an, an=von,
                                    zustand=zustand, status=200 if zustand == "completed" else 504,
                                    notiz=antwort, host=an_host, an_host=von_host))
        return Auftrag(
            auftrag_id=f"demo-{next(self._kennung):04d}", zustand=zustand, von=von, an=an,
            text=text, erstellt=_stempel(erstellt), geaendert=_stempel(geaendert),
            quittung_erwartet=True, verlauf=verlauf, an_session=sitzung(an), bindung="session",
            host=an_host, von_host=von_host,
        )

    # -- Quelle ------------------------------------------------------------

    def bestand(self, *, mesh: bool = False, tokens: bool = False) -> Bestand:
        with self._sperre:
            agenten = [a for a in self._agenten if mesh or a.rechner == DEMO_RECHNER]
        return Bestand(
            rechner=DEMO_RECHNER,
            zeit=_stempel(datetime.now(UTC)),
            agenten=list(agenten),
            system=RECHNER_SYSTEME[DEMO_RECHNER],
            anmeldung=_stempel(self._start + timedelta(days=27)),
            claude_version=CLAUDE_VERSION,
            systeme=dict(RECHNER_SYSTEME) if mesh else {DEMO_RECHNER: "Windows 11"},
        )

    def namen(self) -> Namenspool:
        with self._sperre:
            vergeben = {a.name: a.session_id for a in self._agenten}
        alle = [a.name for a in demo_texte.agenten()] + list(demo_texte.weitere_namen())
        return Namenspool(
            motiv=demo_texte.motiv_name(self._lang),
            namen=alle,
            frei=[n for n in alle if n not in vergeben],
            reserviert=["Operator"],
            vergeben=vergeben,
        )

    def verlauf(self, name: str, *, session_id: str = "", seit: str = "") -> list[Auftrag]:
        with self._sperre:
            return [a for a in self._auftraege if name in (a.von, a.an)]

    def bestandsverlauf(self, grenze: int = 0) -> Busbestand:
        with self._sperre:
            auftraege = sorted(self._auftraege, key=lambda a: a.erstellt, reverse=True)
        if grenze:
            auftraege = auftraege[:grenze]
        return Busbestand(rechner=DEMO_RECHNER, zeit=_stempel(datetime.now(UTC)),
                          verfall_stunden=24, auftraege=auftraege)

    def senden(
        self,
        an: str,
        text: str,
        *,
        topic: str = "",
        quittung: bool = False,
        host: str = "",
        von: str = "",
    ) -> str:
        jetzt = datetime.now(UTC)
        absender = von or "Operator"
        antwort = "Erledigt." if self._lang == "de" else "Done."
        with self._sperre:
            if not any(a.name == an for a in self._agenten):
                return t("demo.unknown_agent", name=an)
            auftrag = self._bus_eintrag(absender, an, text, "completed", antwort, 0)
            auftrag.topic = topic
            auftrag.erstellt = _stempel(jetzt)
            self._auftraege.append(auftrag)
        return ""

    def neustarten_fern(self, rechner: str, session_id: str, cwd: str = "") -> str:
        return t("demo.not_available")

    def stoppen(self, name: str) -> str:
        with self._sperre:
            vorher = len(self._agenten)
            self._agenten = [a for a in self._agenten if a.name != name]
            return "" if len(self._agenten) < vorher else t("demo.unknown_agent", name=name)

    def bildschirmfoto(self, rechner: str = "") -> tuple[str, str]:
        return "", t("demo.not_available")

    def aktualisiere_claude(self, rechner: str = "", verfahren: str = "claude") -> tuple[str, str]:
        return "", t("demo.not_available")

    # -- Fuer den simulierten Diskussionsablauf ------------------------------

    def freie_namen(self) -> list[str]:
        """Namen, die gerade niemand traegt - fuer frisch gestartete Teilnehmer."""
        return self.namen().frei

    def aufnehmen(self, name: str, rechner: str = DEMO_RECHNER) -> Agent:
        """Nimmt einen frisch gestarteten Teilnehmer in den Bestand auf."""
        agent = Agent(name=name, status="busy", rechner=rechner, session_id=sitzung(name, 999),
                      modell="claude-sonnet-5-5", version=CLAUDE_VERSION,
                      system=RECHNER_SYSTEME[rechner], letzte_zeit=_stempel(datetime.now(UTC)),
                      aufgabe=t("demo.discussion_task"), cwd=arbeitsordner(rechner, "debate"))
        with self._sperre:
            self._agenten.append(agent)
        return agent

    def entlassen(self, namen: list[str]) -> None:
        """Nimmt die frisch gestarteten Teilnehmer nach der Diskussion wieder heraus."""
        with self._sperre:
            self._agenten = [a for a in self._agenten if a.name not in namen]
