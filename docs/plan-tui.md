# Plan: Textual-TUI

Stand 01.08.2026. Grundlage ist Michaels Skizze plus die Referenz-Apps
`jira-timesheet` (Header, Statuszeile, Log-Panel), `death-proof` (Settings-Tabs)
und `console-error-scanner` (Info-Header).

## Aufbau

```
Header                          Titelzeile
InfoHeader (4 Spalten x 4)      thematisch gruppiert, siehe unten
TabbedContent                   Agenten | Message-Bus | Statistik
  Agenten:
    Horizontal
      Vertical (60 %)           Filterzeile + Agenten-Tabelle
      VerticalSplitter
      Vertical (40 %)
        Verlauf (Chat)          oben, WhatsApp-artig
        HorizontalSplitter
        Eingabe + Senden        unten
Statuszeile                     Summen
HorizontalSplitter
LogPanel                        einklappbar, standardmäßig sichtbar
Footer
```

Alles aus `textual-widgets`: `InfoHeader`, `LogPanel` + `LogRouter`,
`BaseSettingsScreen`, `AboutScreen`, `DisclaimerScreen`, `CrashGuard`,
`ClickableLinksMixin`, `HorizontalSplitter`, `VerticalSplitter`,
`SearchInputWithHistory`. Themes über `textual-themes`.

App-Klasse analog jira-timesheet:

```python
class SanctuaryApp(CrashGuard, ClickableLinksMixin, LogRouter, App[None]):
```

## Kopf-Panel (4 Spalten, `fill="column"`)

| Betrieb | Technik | Netz | Namen |
|---|---|---|---|
| Laufzeit | node | Rechner | Namenspool |
| Agenten | SQLite | Mesh an/aus | Namen frei |
| davon beschäftigt | Datenbank-Pfad | Hosts erreichbar | Tokens gesamt |
| offene Aufträge | Datenbank-Größe | zuletzt aktualisiert | Cache gelesen |

## Agenten-Tabelle

Alle Werte kommen aus `sanctuary status --json`, nichts wird geraten.

| Spalte | Quelle | Anmerkung |
|---|---|---|
| ● | `status` | Ampel, siehe unten |
| Name | `name` | eigene Sitzung mit `*` |
| Rechner | `rechner` | nur bei Mesh-Ansicht |
| Modell | `modell` | Kurzform, `1M` wenn großes Fenster |
| Ordner | `cwd` | von links gekürzt |
| Laufzeit | `laufzeit` | `+` wenn fortgesetzt |
| Kontext | `kontext` | ab 70 % gelb, ab 90 % rot |
| Post | `post` | offene Aufträge - der eigentliche Handlungsbedarf |
| Tokens | `tokens` | Cache getrennt, nicht addiert |
| Werkzeug | `letztesTool` | woran die Sitzung gerade hängt |

Sortierbar per Kopfklick mit ▲/▼, Filterzeile über `SearchInputWithHistory`.

## Ampel

Eine Ampel hat drei Farben. Der Kern kennt genau zwei Zustände (`idle`, `busy`),
die dritte Farbe ist der Ausfall:

| Farbe | Bedeutung | Ableitung |
|---|---|---|
| grün | verfügbar | `idle` - wartet auf Eingabe, kann Aufträge annehmen |
| gelb | beschäftigt | `busy` - arbeitet gerade |
| rot | nicht erreichbar | Host im Mesh antwortet nicht, oder Fehler |

**Der Kontext gehört nicht in die Ampel.** Eine Spalte trägt eine Aussage. Die
Kontext-Spalte färbt sich selbst - ab 70 Prozent gelb, ab 90 Prozent rot - und
bleibt damit unabhängig davon, ob der Agent gerade arbeitet.

## Verlauf statt Chat

Ein echter Chat ist es nicht - eine laufende interaktive Sitzung hat keinen
Eingang. Was es gibt, ist der Auftragsverlauf aus dem Message-Bus: gesendeter Auftrag
(rechts), Quittungen des Empfängers (links), jeweils mit Zustand und Zeit.
Genau das rendert das Panel im WhatsApp-Muster.

Zustandsfarben aus dem A2A-Vokabular: `submitted` grau, `working` gelb,
`completed` grün, `failed` rot, `input_required` blau.

## Datenanbindung

**Python liest und schreibt nicht selbst in die Datenbank.** Der Message-Bus schreibt
aus genau einem Prozess (Node) - der Kommentar in `speicher.mjs` ist
unmissverständlich: Python-Schreiben in die alten JSONL-Dateien hat in der
Messung 7,5 Prozent der Zeilen verloren, und die Übergangsphase läuft noch.

Deshalb ein `Quelle`-Interface mit drei Implementierungen:

| Implementierung | Weg | Zweck |
|---|---|---|
| `LokaleQuelle` | `sanctuary status --json`, `sanctuary auftraege --json` | Normalbetrieb |
| `StromQuelle` | `sanctuary watch 2 --json` als NDJSON-Strom | Live-Ansicht ohne Prozessstart je Aktualisierung |
| `HttpQuelle` | später gegen die geplante API | Platzhalter |

Der Strom ist der wichtige Teil: ein Prozessstart kostet unter Windows 70 bis
105 ms, bei sekündlicher Aktualisierung wäre das die Hälfte der Zeit. Ein
langlebiger Prozess, aus dem Python zeilenweise liest, hat diese Kosten einmal.

Gesendet wird über `sanctuary send <Name> "<Text>"`. Damit bleibt Node der
einzige Schreiber, und die Schnittstelle ist schon die, die später eine REST-API
bekommt: Kommando rein, JSON raus.

## Agent starten

Der offene Punkt. Drei Wege, je nach Ziel:

| Ziel | Weg |
|---|---|
| lokal Windows | `wt.exe -w 0 nt -d <cwd> cmd /k claude -n <Name>` - neuer Tab im laufenden Windows Terminal, Rückfall auf `start cmd` |
| lokal Linux | `gnome-terminal --tab -- bash -lc "claude -n <Name>"` |
| entfernt | `ssh <host> "tmux new-session -d -s <Name> claude -n <Name>"`, Michael hängt sich mit `ssh <host> -t tmux attach -t <Name>` dran |

Ein entfernter Start ohne tmux geht nicht: `ssh host "befehl"` hat kein TTY,
und Claude Code braucht eines. tmux ist auf senza vorhanden.

## Fußzeile

`i` Info, `h` Hilfe, `Stop`, `Start`, `s` Einstellungen, `l` Log,
`t` Theme, `nur lokal`, `F5` Aktualisieren, `q` Beenden. Namenspool-Wechsel
gehört in die Einstellungen, nicht in die Fußzeile - er wird selten gebraucht
und die Zeile ist schon voll.

Buchstaben-Bindings jeweils in beiden Schreibweisen (`q,Q`), jedes mit Tooltip.

## Einstellungen

| Tab | Inhalt |
|---|---|
| Sprache | de/en, Neustart-Hinweis |
| Netzwerk | Proxy für den Kundenrechner |
| Mesh | Hostliste, Zeitüberschreitung, nur lokal als Vorgabe |
| Namenspool | je Pool eine Gruppe: Name plus kommagetrennte Liste, aktiver Pool wählbar |
| Datenbank | Journal-Modus, ID-Spalte anzeigen |
| Speicherort | Pfade anklickbar |

## Haftungshinweis

Pflicht, aber der Standardtext des Widgets beschreibt Scanner. Eigene
Zusicherungen: Berechtigung an den beteiligten Rechnern, Verantwortung für die
ausgelösten Aktionen, keine fremden Daten über den Message-Bus.

## Reihenfolge

1. Gerüst: Projektstruktur, Kern mit `Quelle`-Interface, Disclaimer, Themes
2. Kopf-Panel und Agenten-Tabelle - lesend, das ist der Nutzen von Tag eins
3. Verlauf und Senden
4. Statuszeile, Log-Panel, Einstellungen
5. Starten und Beenden von Agenten
6. Message-Bus- und Statistik-Tab

Message-Bus und Statistik bleiben zunächst leer, Michaels Vorgabe.
