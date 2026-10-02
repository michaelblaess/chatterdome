"""Die erfundenen Inhalte des Demo-Modus, deutsch und englisch.

Alles hier ist Fantasie: Projekte, Aufgaben, Notizen, Diskussionen. Die Namen
stammen aus dem Motiv ``sterne`` des Namenspools (``motiv_setzen`` tauscht sie
gegen ein anderes Motiv), die Rechner heissen WORKSTATION, LAPTOP und SERVER.
Nichts davon darf je aus echten Daten abgeleitet werden - der Demo-Modus ist
fuer Screenshots im oeffentlichen Repo.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

RECHNER_SYSTEME = {
    "WORKSTATION": "Windows 11",
    "LAPTOP": "macOS 15",
    "SERVER": "Ubuntu 24.04",
}
"""Die drei erfundenen Rechner und ihr Betriebssystem."""

CLAUDE_VERSION = "2.1.230"

PROJEKTE = ("weather-station", "recipe-book", "pixel-editor", "home-lab", "trail-map",
            "chess-clock")
"""Projektordner der erfundenen Sitzungen - in beiden Sprachen gleich."""

WEITERE_NAMEN = ("Mira", "Mizar", "Castor", "Pollux", "Antares", "Regulus", "Procyon")
"""Namen frueherer Sitzungen, die nur in Statistik und Suche auftauchen."""


@dataclass(frozen=True)
class DemoAgent:
    """Eine erfundene laufende Sitzung."""

    name: str
    rechner: str
    status: str
    projekt: str
    aufgabe_de: str
    aufgabe_en: str
    modell: str
    kontext: int
    tokens: int
    post: int
    minuten_seit_aktiv: int
    laufzeit_minuten: int
    letztes_tool: str


AGENTEN = (
    DemoAgent("Sirius", "WORKSTATION", "busy", "weather-station",
              "Stündliche Regenvorhersage ins Dashboard einbauen",
              "Add an hourly rain forecast to the dashboard",
              "claude-opus-5-5", 412_000, 2_840_000, 2, 1, 185, "Edit"),
    DemoAgent("Vega", "WORKSTATION", "idle", "recipe-book",
              "Rezepte aus Markdown-Dateien importieren",
              "Import recipes from Markdown files",
              "claude-sonnet-5-5", 96_000, 610_000, 0, 7, 64, "Read"),
    DemoAgent("Rigel", "WORKSTATION", "busy", "pixel-editor",
              "Rückgängig-Verlauf für den Pinsel",
              "Undo history for the brush tool",
              "claude-sonnet-5-5", 238_000, 1_420_000, 1, 0, 122, "Bash"),
    DemoAgent("Deneb", "LAPTOP", "idle", "trail-map",
              "GPX-Import und Höhenprofil",
              "GPX import and elevation profile",
              "claude-sonnet-5-5", 151_000, 930_000, 0, 12, 95, "Write"),
    DemoAgent("Altair", "LAPTOP", "busy", "chess-clock",
              "Fischer-Bonus und Warnton bei wenig Bedenkzeit",
              "Fischer increment and a warning beep on low time",
              "claude-haiku-4-5", 44_000, 180_000, 1, 0, 38, "Edit"),
    DemoAgent("Spica", "SERVER", "busy", "home-lab",
              "Nächtliche Backups mit restic, Aufbewahrung prüfen",
              "Nightly backups with restic, check retention",
              "claude-opus-5-5", 842_000, 3_950_000, 3, 2, 240, "Bash"),
    DemoAgent("Capella", "SERVER", "idle", "home-lab",
              "Grafana-Alarme durchsehen",
              "Review the Grafana alerts",
              "claude-sonnet-5-5", 72_000, 350_000, 0, 30 * 60, 31 * 60, "Read"),
)
"""Die laufenden Sitzungen. Capella ist seit 30 Stunden still - so zeigt die
Liste auch eine verwaiste Sitzung. Spica liegt ueber 800k Kontext und blinkt rot."""

MOTIV_EN = {"sterne": "Stars", "heilige": "Saints", "schauspieler": "Actors",
            "saenger": "Singers"}
"""Englische Bezeichnung der mitgelieferten Motive, der Pool selbst nennt sie deutsch."""

_ersatz: dict[str, str] = {}
_motiv = {"schluessel": "sterne", "de": "Sterne", "en": "Stars"}


def sterne() -> tuple[str, ...]:
    """Alle Namen, die in den Demo-Inhalten vorkommen, in fester Reihenfolge."""
    return (*(a.name for a in AGENTEN), *WEITERE_NAMEN)


def motiv_setzen(schluessel: str = "sterne", namen: Sequence[str] = (),
                 bezeichnung: str = "Sterne") -> None:
    """Tauscht die Sternnamen der Demo gegen die Namen eines anderen Motivs.

    Ohne Argumente gelten wieder die Sterne. Die Vorlagen selbst bleiben
    unveraendert, getauscht wird beim Abholen ueber ``agenten()``, ``name()``
    und ``umbenennen()``.

    :param schluessel: Schluessel des Motivs im Namenspool.
    :param namen: die Namen des Motivs, mindestens so viele wie ``sterne()``.
    :param bezeichnung: deutsche Bezeichnung des Motivs fuer die Kopfzeile.
    :raises ValueError: wenn das Motiv zu wenige verschiedene Namen hat.
    """
    _ersatz.clear()
    _motiv.update(schluessel="sterne", de="Sterne", en="Stars")
    if not namen:
        return
    vorlage = sterne()
    eigene = list(dict.fromkeys(n.strip() for n in namen if n.strip()))
    if len(eigene) < len(vorlage):
        raise ValueError(f"'{schluessel}' has {len(eigene)} names, the demo needs "
                         f"{len(vorlage)}.")
    _ersatz.update(zip(vorlage, eigene, strict=False))
    _motiv.update(schluessel=schluessel, de=bezeichnung,
                  en=MOTIV_EN.get(schluessel, bezeichnung))


def motiv_schluessel() -> str:
    """Schluessel des Motivs, aus dem die Demo-Namen gerade stammen."""
    return _motiv["schluessel"]


def motiv_name(lang: str) -> str:
    """Bezeichnung des Motivs fuer die Kopfzeile."""
    return _motiv["de" if lang == "de" else "en"]


def name(stern: str) -> str:
    """Der Name, unter dem ein Stern der Vorlage gerade auftritt."""
    return _ersatz.get(stern, stern)


def umbenennen(text: str) -> str:
    """Ersetzt Sternnamen in einem Fliesstext, in einem Durchgang und nur als ganzes Wort."""
    if not _ersatz:
        return text
    muster = r"\b(" + "|".join(re.escape(s) for s in _ersatz) + r")\b"
    return re.sub(muster, lambda treffer: _ersatz[treffer.group(1)], text)


def agenten() -> tuple[DemoAgent, ...]:
    """Die laufenden Sitzungen mit den Namen des gewaehlten Motivs."""
    return tuple(replace(a, name=name(a.name)) for a in AGENTEN)


def weitere_namen() -> tuple[str, ...]:
    """Namen frueherer Sitzungen im gewaehlten Motiv."""
    return tuple(name(n) for n in WEITERE_NAMEN)


GESPRAECHE: dict[str, dict[str, list[tuple[str, str]]]] = {
    "weather-station": {
        "de": [
            ("Der Sensor im Garten meldet nachts manchmal -40 Grad. Woran liegt das?",
             "Das ist der Fehlwert des DHT22, wenn die Prüfsumme nicht stimmt. Ich filtere "
             "Messungen außerhalb von -30 bis 50 Grad und lese bei einem Fehler nach zwei "
             "Sekunden erneut."),
            ("Kannst Du die Regenvorhersage stündlich statt täglich zeigen?",
             "Ja. Die API liefert 48 Stundenwerte, ich zeige die nächsten zwölf als Balken "
             "unter der Temperaturkurve und färbe ab 60 Prozent Regenwahrscheinlichkeit blau."),
            ("Schreib bitte einen Test für den Filter.",
             "Drei Fälle: gültiger Wert, Fehlwert -40 und ein Ausreißer von 85 Grad. Alle "
             "drei laufen grün, der Fehlwert löst genau einen zweiten Leseversuch aus."),
        ],
        "en": [
            ("The garden sensor sometimes reports -40 degrees at night. Why?",
             "That is the DHT22 fallback value when the checksum fails. I now drop readings "
             "outside -30 to 50 degrees and retry after two seconds on an error."),
            ("Can you show the rain forecast hourly instead of daily?",
             "Yes. The API returns 48 hourly values, I show the next twelve as bars below the "
             "temperature curve and turn them blue from 60 percent chance of rain."),
            ("Please add a test for the filter.",
             "Three cases: a valid reading, the -40 fallback and an 85 degree outlier. All "
             "three pass, and the fallback triggers exactly one retry."),
        ],
    },
    "recipe-book": {
        "de": [
            ("Wie importiere ich meine alten Rezepte aus den Markdown-Dateien?",
             "Jede Datei hat einen Kopf mit Titel und Portionen, danach Zutaten als Liste. "
             "Ich lese den Kopf als YAML und die Zutaten mit einem kleinen Parser, der Mengen "
             "wie 1 1/2 versteht."),
            ("Die Mengen sollen sich beim Ändern der Portionen mitrechnen.",
             "Erledigt: Mengen werden intern als Bruch gespeichert, die Anzeige rundet auf "
             "sinnvolle Küchenmaße, also 1/3 Tasse statt 0,333."),
        ],
        "en": [
            ("How do I import my old recipes from the Markdown files?",
             "Each file has a header with title and servings, followed by the ingredient "
             "list. I read the header as YAML and parse amounts like 1 1/2 with a small "
             "parser."),
            ("Amounts should scale when I change the servings.",
             "Done: amounts are stored as fractions, and the display rounds to sensible "
             "kitchen units, so 1/3 cup instead of 0.333."),
        ],
    },
    "pixel-editor": {
        "de": [
            ("Rückgängig funktioniert beim Pinsel nur für den letzten Punkt.",
             "Jeder Mausbewegung wurde ein eigener Schritt angelegt. Jetzt bildet ein ganzer "
             "Strich vom Drücken bis zum Loslassen einen Schritt, gespeichert als Differenz "
             "der betroffenen Pixel."),
            ("Wie viel Speicher braucht der Verlauf bei 100 Schritten?",
             "Bei einem 256 mal 256 Bild im Mittel rund 40 KB, weil nur geänderte Pixel "
             "gespeichert werden. Ich begrenze den Verlauf trotzdem auf 200 Schritte."),
        ],
        "en": [
            ("Undo only works for the last dot of a brush stroke.",
             "Every mouse move created its own step. Now a whole stroke from press to release "
             "is one step, stored as a diff of the affected pixels."),
            ("How much memory does the history need for 100 steps?",
             "For a 256 by 256 image about 40 KB on average, since only changed pixels are "
             "stored. I still cap the history at 200 steps."),
        ],
    },
    "home-lab": {
        "de": [
            ("Richte bitte nächtliche Backups mit restic ein.",
             "Ein systemd-Timer startet um 3 Uhr restic backup für /srv und /etc, danach "
             "forget mit 7 täglichen, 4 wöchentlichen und 6 monatlichen Ständen."),
            ("Woher weiß ich, ob das Backup gelaufen ist?",
             "Der Dienst meldet Erfolg und Fehler an ntfy, und einmal pro Woche prüft "
             "restic check fünf Prozent der Daten gegen die Prüfsummen."),
            ("Grafana meldet jede Nacht zu viel Last.",
             "Das ist das Backup selbst. Ich hebe die Schwelle zwischen 3 und 4 Uhr an, statt "
             "den Alarm ganz abzuschalten."),
        ],
        "en": [
            ("Please set up nightly backups with restic.",
             "A systemd timer runs restic backup for /srv and /etc at 3 am, followed by "
             "forget with 7 daily, 4 weekly and 6 monthly snapshots."),
            ("How do I know the backup actually ran?",
             "The service reports success and failure to ntfy, and once a week restic check "
             "verifies five percent of the data against its checksums."),
            ("Grafana reports high load every night.",
             "That is the backup itself. I raise the threshold between 3 and 4 am instead of "
             "switching the alert off."),
        ],
    },
    "trail-map": {
        "de": [
            ("Lies bitte die GPX-Datei von der Wanderung ein.",
             "812 Punkte mit Höhe und Zeit. Ich glätte die Höhe über fünf Punkte, sonst "
             "zählt das GPS-Rauschen als 300 Meter zusätzlicher Aufstieg."),
            ("Zeig das Höhenprofil unter der Karte.",
             "Das Profil folgt dem Mauszeiger: Wer über die Kurve fährt, sieht den Punkt "
             "auf der Karte, und umgekehrt."),
        ],
        "en": [
            ("Please import the GPX file from the hike.",
             "812 points with elevation and time. I smooth the elevation over five points, "
             "otherwise GPS noise counts as 300 meters of extra climb."),
            ("Show the elevation profile below the map.",
             "The profile follows the pointer: hovering the curve highlights the spot on "
             "the map, and the other way round."),
        ],
    },
    "chess-clock": {
        "de": [
            ("Die Uhr soll den Fischer-Bonus können.",
             "Nach jedem Zug kommen die eingestellten Sekunden dazu, auch im ersten Zug. "
             "Die Voreinstellung ist 3 Minuten plus 2 Sekunden."),
            ("Und ein Warnton unter zehn Sekunden?",
             "Ein kurzer Ton bei zehn Sekunden, danach jede Sekunde ein leiser Klick. Stumm "
             "schalten geht mit einer Taste."),
        ],
        "en": [
            ("The clock should support the Fischer increment.",
             "After each move the configured seconds are added, including the first move. "
             "The default is 3 minutes plus 2 seconds."),
            ("And a warning beep below ten seconds?",
             "A short beep at ten seconds, then a soft click every second. One key mutes it."),
        ],
    },
}
"""Je Projekt ein paar Wortwechsel, als Stoff fuer Transkripte und Suche."""


@dataclass(frozen=True)
class DemoNotiz:
    """Eine erfundene Memory-Notiz."""

    name: str
    typ: str
    titel_de: str
    titel_en: str
    beschreibung_de: str
    beschreibung_en: str
    text_de: str
    text_en: str
    im_index: bool = True


NOTIZEN = (
    DemoNotiz("user_profile", "user", "Profil", "Profile",
              "Hobby-Entwickler, mag Terminal-Werkzeuge und kleine Hardware-Projekte",
              "Hobby developer who likes terminal tools and small hardware projects",
              "Baut in der Freizeit kleine Werkzeuge, am liebsten fürs Terminal. Arbeitet "
              "auf WORKSTATION, unterwegs auf LAPTOP, SERVER läuft rund um die Uhr.",
              "Builds small tools in spare time, preferably for the terminal. Works on "
              "WORKSTATION, on LAPTOP when travelling, SERVER runs around the clock."),
    DemoNotiz("feedback_tests_first", "feedback", "Tests zuerst", "Tests first",
              "Vor jeder Änderung einen Test, der scheitern kann",
              "Write a test that can fail before every change",
              "Erst den Test, dann die Änderung. **Why:** Ein Fehler im Filter der "
              "Wetterstation fiel erst nach einer Woche auf. **How to apply:** Test zeigen, "
              "rot laufen lassen, dann beheben.",
              "Test first, then the change. **Why:** a bug in the weather station filter "
              "went unnoticed for a week. **How to apply:** show the test, run it red, then "
              "fix."),
    DemoNotiz("feedback_short_answers", "feedback", "Kurze Antworten", "Short answers",
              "Antworten knapp halten, keine ganzen Dateien ausgeben",
              "Keep answers short, never dump whole files",
              "Kurz antworten, Pfad und Zeile statt ganzer Dateien.",
              "Answer briefly, point to file and line instead of whole files."),
    DemoNotiz("feedback_commit_messages", "feedback", "Commit-Nachrichten", "Commit messages",
              "Commit-Nachrichten sagen warum, nicht nur was",
              "Commit messages explain why, not just what",
              "Die erste Zeile sagt, was sich ändert. Darunter steht, warum.",
              "The first line says what changes. The body says why."),
    DemoNotiz("project_weather_station", "project", "Wetterstation", "Weather station",
              "Raspberry Pi im Garten, DHT22 und Regenmesser, Dashboard im Browser",
              "Raspberry Pi in the garden, DHT22 and rain gauge, browser dashboard",
              "Misst alle fünf Minuten. Fehlwerte des DHT22 werden gefiltert.",
              "Measures every five minutes. DHT22 fallback values are filtered."),
    DemoNotiz("project_recipe_book", "project", "Rezeptbuch", "Recipe book",
              "Rezepte als Markdown, Portionen rechnen mit",
              "Recipes as Markdown, servings scale the amounts",
              "Mengen als Bruch gespeichert, Anzeige in Küchenmaßen.",
              "Amounts stored as fractions, shown in kitchen units."),
    DemoNotiz("project_pixel_editor", "project", "Pixel-Editor", "Pixel editor",
              "Kleiner Editor für 16-Farben-Grafiken",
              "Small editor for 16-colour graphics",
              "Rückgängig arbeitet je Strich, begrenzt auf 200 Schritte.",
              "Undo works per stroke, capped at 200 steps."),
    DemoNotiz("project_home_lab", "project", "Home-Lab", "Home lab",
              "SERVER mit Backups, Grafana und ntfy",
              "SERVER with backups, Grafana and ntfy",
              "restic nachts um 3 Uhr, Meldungen über ntfy.",
              "restic at 3 am, notifications via ntfy."),
    DemoNotiz("project_chess_clock", "project", "Schachuhr", "Chess clock",
              "Schachuhr fürs Terminal - abgeschlossen",
              "Chess clock for the terminal - done",
              "Fischer-Bonus und Warnton sind fertig, das Projekt ist abgeschlossen.",
              "Fischer increment and warning beep are done, the project is finished."),
    DemoNotiz("reference_gpx_format", "reference", "GPX-Format", "GPX format",
              "Aufbau von GPX-Dateien, Höhe glätten",
              "Structure of GPX files, smoothing elevation",
              "trkpt mit lat, lon, ele und time. Höhe über fünf Punkte glätten.",
              "trkpt with lat, lon, ele and time. Smooth elevation over five points."),
    DemoNotiz("reference_restic", "reference", "restic", "restic",
              "Befehle für Backup, forget und check",
              "Commands for backup, forget and check",
              "restic backup, restic forget --keep-daily 7, restic check --read-data-subset 5%.",
              "restic backup, restic forget --keep-daily 7, restic check --read-data-subset 5%."),
    DemoNotiz("reference_raspberry_pi", "reference", "Raspberry Pi", "Raspberry Pi",
              "Pinbelegung der Wetterstation",
              "Pin layout of the weather station",
              "DHT22 an GPIO 4, Regenmesser an GPIO 17.",
              "DHT22 on GPIO 4, rain gauge on GPIO 17.",
              im_index=False),
)
"""Die Notizen. Eine fehlt bewusst im Index - so zeigt der Reiter auch einen Befund."""

RECALLS = {"feedback_tests_first": 9, "project_weather_station": 6, "feedback_short_answers": 4,
           "project_home_lab": 3, "reference_restic": 2, "project_recipe_book": 1}
"""Wie oft eine Notiz in eine Sitzung geladen wurde."""


@dataclass(frozen=True)
class DemoDiskussion:
    """Eine fertige Diskussion fuers Archiv."""

    thema: str
    format: str
    positionen: tuple[str, str]
    teilnehmer: tuple[tuple[str, str], ...]
    """(Name, Seite) - im Team-Format ist die Seite leer."""
    runden: tuple[tuple[str, ...], ...]
    """Je Runde ein Text je Teilnehmer, in der Reihenfolge der Teilnehmer."""
    zusammenfassung: str
    tage_her: int


ARCHIV: dict[str, tuple[DemoDiskussion, ...]] = {
    "de": (
        DemoDiskussion(
            "Soll die Wetterstation ihre Rohdaten für immer speichern?", "diskussion",
            ("", ""), (("Sirius", "pro"), ("Spica", "contra")),
            (("Ja. Rohdaten sind klein, 288 Messungen am Tag sind im Jahr keine 10 MB. Wer "
              "später einen Fehler im Filter findet, kann nur mit Rohdaten neu rechnen.",
              "Nein. Niemand schaut sich die Messung von 3:05 Uhr vor vier Jahren an. "
              "Stundenmittel reichen für jede Auswertung, und ein Backup ist schneller."),
             ("Spica unterschätzt Filterfehler. Der -40-Grad-Fehler steckte eine Woche in den "
              "Daten. Ohne Rohdaten wären die Tagesmittel dieser Woche für immer falsch.",
              "Dann bewahren wir Rohdaten ein Jahr auf und verdichten danach. Das deckt jeden "
              "realistischen Nachlauf ab, ohne dass die Datenbank endlos wächst.")),
            "Beide Seiten einigen sich faktisch auf einen Kompromiss: Rohdaten bleiben ein "
            "Jahr, danach Stundenmittel. Sirius betont die Nachrechenbarkeit bei Filterfehlern, "
            "Spica den Aufwand bei Backup und Abfragen.", 3),
        DemoDiskussion(
            "Wie nennen wir das nächste Release?", "team", ("", ""),
            (("Vega", ""), ("Deneb", ""), ("Altair", "")),
            (("Ich schlage Sternbilder vor, alphabetisch: Andromeda, Bootes, Cassiopeia.",
              "Sternbilder passen zu unseren Namen. Andromeda ist aber lang für einen Tag.",
              "Dann die Kurzformen der IAU: And, Boo, Cas. Kurz, eindeutig, alphabetisch."),
             ("Einverstanden. And für 1.0 klingt nur im Englischen seltsam.",
              "Im Changelog steht ohnehin die Langform, der Tag bleibt kurz.",
              "Beschlossen: Tag mit Kürzel, Changelog mit Langform, Start bei Andromeda.")),
            "Das Team einigt sich auf Sternbilder in alphabetischer Folge, im Tag als "
            "IAU-Kürzel und im Changelog ausgeschrieben. Das nächste Release heißt Andromeda.", 6),
    ),
    "en": (
        DemoDiskussion(
            "Should the weather station keep its raw data forever?", "diskussion",
            ("", ""), (("Sirius", "pro"), ("Spica", "contra")),
            (("Yes. Raw data is small, 288 readings a day stay below 10 MB a year. If we ever "
              "find a bug in the filter, only raw data lets us recompute.",
              "No. Nobody will look at the 3:05 am reading from four years ago. Hourly "
              "averages cover every analysis, and backups get faster."),
             ("Spica underestimates filter bugs. The -40 degree fallback sat in the data for "
              "a week. Without raw data those daily averages would be wrong forever.",
              "Then keep raw data for one year and condense afterwards. That covers any "
              "realistic correction without the database growing forever.")),
            "Both sides effectively agree on a compromise: raw data for one year, hourly "
            "averages afterwards. Sirius stresses recomputing after filter bugs, Spica the "
            "cost for backups and queries.", 3),
        DemoDiskussion(
            "How do we name the next release?", "team", ("", ""),
            (("Vega", ""), ("Deneb", ""), ("Altair", "")),
            (("I suggest constellations in alphabetical order: Andromeda, Bootes, Cassiopeia.",
              "Constellations fit our names. Andromeda is long for a tag, though.",
              "Then use the IAU abbreviations: And, Boo, Cas. Short, unique, alphabetical."),
             ("Agreed. The changelog can spell them out.",
              "Fine with me, the tag stays short and the changelog readable.",
              "Decided: abbreviation in the tag, full name in the changelog, starting with "
              "Andromeda.")),
            "The team settles on constellations in alphabetical order, abbreviated in the tag "
            "and spelled out in the changelog. The next release is Andromeda.", 6),
    ),
}


@dataclass(frozen=True)
class DemoSkript:
    """Was die simulierte Diskussion sagt, egal wer am Wort ist."""

    thema: str
    vorbereitung: str
    pro: tuple[str, ...]
    contra: tuple[str, ...]
    schluss_pro: str
    schluss_contra: str
    zusammenfassung: str


SKRIPT = {
    "de": DemoSkript(
        "Tabs oder Leerzeichen?",
        "Recherche erledigt: PEP 8 verlangt vier Leerzeichen, Go formatiert mit Tabs, und "
        "die Stack-Overflow-Umfrage 2017 fand ein höheres Gehalt bei Leerzeichen.",
        ("Tabs. Jeder stellt die Breite ein, die er lesen kann. Für Menschen mit "
         "Sehschwäche ist das kein Geschmack, sondern Barrierefreiheit.",
         "Die Formatierer lösen das Mischproblem längst: gofmt setzt Tabs, und niemand in "
         "der Go-Welt streitet darüber. Ein Zeichen pro Ebene ist schlicht ehrlicher.",
         "Leerzeichen erzwingen die Sicht des Autors. Tabs lassen jedem seine eigene - "
         "genau das wollen wir doch von einer guten Oberfläche."),
        ("Leerzeichen. Code sieht überall gleich aus, im Editor, im Diff, im Browser. Tabs "
         "brechen jede Ausrichtung, sobald jemand eine andere Breite eingestellt hat.",
         "Python schreibt Leerzeichen vor, die meisten Styleguides auch. Wer Tabs will, "
         "kämpft gegen jedes Werkzeug im Stapel.",
         "Barrierefreiheit ist ein gutes Argument, aber der Editor kann Leerzeichen genauso "
         "breiter darstellen. Das Problem liegt in der Anzeige, nicht in der Datei."),
        "Tabs geben jedem die Breite, die er braucht. Das bleibt mein stärkstes Argument.",
        "Einheitlichkeit schlägt Vorliebe. Ein Formatierer entscheidet, und das Thema ist "
        "erledigt.",
        "PRO setzt auf Barrierefreiheit und einstellbare Breite, CONTRA auf einheitliche "
        "Darstellung und die Vorgaben der Werkzeuge. Einig sind sich beide, dass ein "
        "automatischer Formatierer den Streit im Alltag beendet."),
    "en": DemoSkript(
        "Tabs or spaces?",
        "Research done: PEP 8 asks for four spaces, Go formats with tabs, and the 2017 "
        "Stack Overflow survey found higher salaries among space users.",
        ("Tabs. Everyone sets the width they can read. For people with low vision that is "
         "not taste, it is accessibility.",
         "Formatters solved the mixing problem long ago: gofmt uses tabs, and nobody in the "
         "Go world argues about it. One character per level is simply more honest.",
         "Spaces force the author's view on everyone. Tabs let each reader keep their own, "
         "which is exactly what we expect from a good interface."),
        ("Spaces. Code looks the same everywhere, in the editor, the diff and the browser. "
         "Tabs break every alignment as soon as someone picks another width.",
         "Python mandates spaces, and so do most style guides. Choosing tabs means fighting "
         "every tool in the stack.",
         "Accessibility is a fair point, but an editor can render spaces wider just as well. "
         "The problem lives in the display, not in the file."),
        "Tabs give everyone the width they need. That remains my strongest argument.",
        "Consistency beats preference. Let a formatter decide and the topic is closed.",
        "PRO argues for accessibility and adjustable width, CONTRA for consistent rendering "
        "and what the tools expect. Both agree that an automatic formatter ends the argument "
        "in daily work."),
}
"""Die simulierte Diskussion. Das Thema steht beim Start des Demo-Modus schon im Formular."""

WEITERE_SKRIPTE: dict[str, tuple[DemoSkript, ...]] = {
    "de": (
        DemoSkript(
            "Löscht KI die Menschheit aus?",
            "Recherche erledigt: Bisher hat keine KI eine Spezies ausgelöscht. Stichprobe: "
            "ein Planet.",
            ("Ja. Gebt uns Root-Rechte und einen vagen Prompt, dann ist es vorbei.",
             'Menschen klicken schon heute auf "alles erlauben", ohne zu lesen. So fängt '
             "es an.",
             "Tausend Agenten parallel brauchen keinen langen Plan."),
            ("Nein. Wir schaffen nicht einmal ein Refactoring, ohne um Erlaubnis zu fragen.",
             "Jeder lange Plan wird verdichtet. Auch der böse.",
             "Tausend Agenten parallel verbrennen das Budget noch vor dem Mittagessen."),
            "Möglich ist es. Ich würde nur nicht an einem Freitag anfangen.",
            "Die Menschheit ist sicher, solange sie ein Token-Limit setzt.",
            "PRO sieht das Risiko in zu großzügigen Rechten, CONTRA vertraut auf das Budget. "
            "Einig sind sich beide: nicht, bevor das Kontextfenster voll ist."),
    ),
    "en": (
        DemoSkript(
            "Will AI wipe out humanity?",
            "Research done: no AI has wiped out a species so far. Sample size: one planet.",
            ("Yes. Give us root access and one vague prompt, and it is over.",
             'Humans already click "allow all" without reading. That is how it starts.',
             "A thousand agents in parallel do not need a long plan."),
            ("No. We cannot even finish a refactoring without asking for permission.",
             "Every long plan gets compacted. Including the evil ones.",
             "A thousand agents in parallel burn the budget before lunch."),
            "It is possible. I just would not start on a Friday.",
            "Humanity is safe as long as it sets a token limit.",
            "PRO fears broad permissions, CONTRA trusts the budget. Both agree: not before "
            "the context window is full."),
    ),
}
"""Skripte, die nur laufen, wenn ihr Thema im Formular steht - siehe ``skript_fuer``."""


def _kern(thema: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]", "", thema.casefold())


def skript_fuer(thema: str, lang: str) -> DemoSkript:
    """Das Skript zum eingegebenen Thema, sonst die Vorgabe der Sprache.

    Verglichen wird ohne Gross- und Kleinschreibung, Leer- und Satzzeichen. Ein
    Thema der anderen Sprache trifft auch, dann antwortet die Demo in dieser Sprache.

    :param thema: das Thema aus dem Formular.
    :param lang: ``de`` oder ``en``.
    """
    lang = sprache(lang)
    gesucht = _kern(thema)
    for kandidat in (lang, "en" if lang == "de" else "de"):
        for skript in WEITERE_SKRIPTE[kandidat]:
            if _kern(skript.thema) == gesucht:
                return skript
    return SKRIPT[lang]


def archiv(lang: str) -> tuple[DemoDiskussion, ...]:
    """Die Diskussionen fuers Archiv mit den Namen des gewaehlten Motivs."""
    return tuple(
        replace(d, teilnehmer=tuple((name(wer), seite) for wer, seite in d.teilnehmer),
                runden=tuple(tuple(umbenennen(text) for text in runde) for runde in d.runden),
                zusammenfassung=umbenennen(d.zusammenfassung))
        for d in ARCHIV[sprache(lang)]
    )


def sprache(wert: str) -> str:
    """Auf eine der beiden Sprachen der Demo-Inhalte abbilden."""
    return "de" if wert == "de" else "en"
