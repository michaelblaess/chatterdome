# Plan: Gedächtnis-Tab

Vierter Tab in claude-sanctuary. Er zeigt, **wie das Gedächtnis von Claude Code
wirklich arbeitet** und was es kostet. Bus und Statistik bleiben vorerst leer.

Stand: 05.08.2026

---

## Warum

Der Anlass war die Beobachtung, dass `MEMORY.md` zu schnell wächst (über 160
Zeilen). Eine Messung am echten Bestand hat die Fragestellung gedreht.

| Grösse | Messwert |
| --- | --- |
| Notizen | 164 (61 project, 49 reference, 46 feedback, 8 user) |
| Bestand gesamt | 13.547 Zeilen, 919 KB, ca. 262.000 Token |
| `MEMORY.md` | 164 Zeilen, 16.877 Zeichen, ca. 4.800 Token |
| Index-Gesundheit | 0 Waisen, 0 tote Verweise |
| Isolierte Notizen | 51 von 164 ohne eingehenden `[[Wikilink]]` |
| Recall-Blöcke im gesamten Transkriptbestand | 42 |

Der Index liegt bei **jedem** Sitzungsstart im Kontext, die Einzeldateien
praktisch nie. Damit gilt:

- Eine Notiz zu löschen spart am Kontext so gut wie nichts.
- Nur eine Zeile weniger in `MEMORY.md` spart wirklich etwas, und zwar in
  jeder künftigen Sitzung.

Der Tab macht genau diesen Unterschied sichtbar, statt eine Dateiliste zu
zeigen. Er ist in der ersten Fassung **rein lesend**.

---

## Drei Messfallen, die ein naives Werkzeug eingebaut hätte

Die dritte ist erst beim Bauen aufgetaucht, und zwar am eigenen Leib.

**Das Git-Datum taugt nicht als Altersmass.** 110 der 164 Notizen tragen Juli
2026, viele davon exakt den 26.07. Das sind Batch-Commits (Umlaut-Welle,
Umbenennungen), keine echte Nutzung. Eine Spalte "zuletzt geändert" würde
Falschsicherheit erzeugen, deshalb gibt es sie nicht.

**Ein Grep über Transkripte misst nicht den Recall.** Die Suche nach
`feedback_git_repo_boundaries` liefert 63 Treffer - ausnahmslos Ausgaben von
`git diff`, kein einziger echter Abruf. Nur der Recall-Marker zählt:

```
<system-reminder>This memory is 4 days old. ...</system-reminder>
1	---
2	name: feedback_no_scratchpad_for_durable
```

**Eine Auswertung zählt sich selbst mit.** Wer in einer Sitzung die
Transkripte nach Abrufen durchsucht, dessen Ausgabe landet im laufenden
Transkript - und enthält den gesuchten Satz. Beim Bau dieses Moduls waren das
**24 von 67** Fundstellen, alle aus den eigenen Suchläufen. Das öffnende
Element gehört deshalb zwingend in den Marker (`<system-reminder>This memory
is`), sonst misst das Werkzeug sich selbst. Dieselbe Falle wie beim naiven
Suchen nach Dateinamen, nur eine Ebene tiefer.

---

## Was die Messung am echten Bestand ergab

| Grösse | Wert |
| --- | --- |
| Index | 4.804 Token, in jeder Sitzung |
| Bestand | 252.965 Token, fast nie geladen |
| Eine Indexzeile | rund 29 Token je Sitzung |
| Index über die 117 gemessenen Sitzungen | **562.068 Token** |
| Abrufe zugeordnet | 27 auf 20 Notizen |
| Nie abgerufen | 144 von 164 Notizen |
| Nicht zuordenbar | 16 Ausschnitte ohne Kopfdaten |
| Verweise ins Leere | 53 |
| Notizen, auf die niemand verweist | 45 |
| Erledigt-Verdacht | 24 Notizen |

Die vierte Zeile ist der Punkt: über die Sitzungen hinweg kostet der Index
**mehr als das Doppelte** des gesamten Bestands, der fast nie geladen wird.

---

## Aufbau

Clean Architecture wie im Rest des Projekts. Der Kern kennt keine Oberfläche.

### `kern/gedaechtnis.py`

- `Notiz` - eine Datei mit Frontmatter, Kennzahlen und Verweisen
- `Befund` - ein Prüfergebnis (Waise, toter Verweis, toter Wikilink, ...)
- `Gedaechtnis` - der ganze Bestand samt Index und abgeleiteten Kennzahlen
- `Recallbericht` - Treffer je Notiz plus die nicht zuordenbaren Blöcke
- `lade_gedaechtnis(verzeichnis)` - liest Verzeichnis und Index
- `zaehle_recalls(projekte, namen)` - scannt die Transkripte

### `tui/widgets/notizen_tabelle.py`

Filterzeile und sortierbare Tabelle mit Kopfklick und `▲`/`▼`, wie die
Agententabelle. Spalten: Zustand, Typ, Name, Zeilen, eingehende Verweise,
ausgehende Verweise, Recalls, Beschreibung.

### `tui/widgets/gedaechtnis_detail.py`

Ohne Auswahl die **Übersicht** - das ist der eigentliche Lerneffekt:

- Kostenrechnung Index gegen Bestand
- Typverteilung als Balken
- Gesundheitsbefunde
- die grössten Notizen
- ein Diät-Vorschlag mit der Ersparnis je Sitzung

Mit Auswahl die **Notiz**: Beschreibung, Kennzahlen, wohin sie verweist, wer
auf sie verweist, Recalls, Erledigt-Hinweis, Pfad als klickbarer Link.

---

## Entscheidungen

- **Rein lesend.** Löschen und Zusammenführen erst, wenn die Analysen sich als
  verlässlich erwiesen haben. Ein Werkzeug, das in `claude-config` schreibt,
  braucht Vertrauen, das es sich erst verdienen muss.
- **Der Recall-Scan läuft in einem Arbeiter.** 385 MB Transkripte brauchen rund
  1 Sekunde bei warmem und deutlich länger bei kaltem Zwischenspeicher. Die
  Tabelle steht sofort, die Recall-Spalte wird nachgetragen.
- **Erst beim Öffnen des Tabs laden.** Wer den Tab nie öffnet, zahlt nichts.
- **Namen werden normalisiert.** Ältere Recalls tragen Bindestriche
  (`feedback-bash-heredoc-commit`), die Dateien heute Unterstriche. Ohne
  Normalisierung fehlen diese Treffer.
- **Nicht zuordenbare Blöcke werden ausgewiesen**, nicht verschwiegen. Ein
  Teil-Recall ohne Frontmatter lässt sich keiner Notiz zuordnen.
- **Die Token-Angabe ist eine Schätzung** und wird als solche beschriftet
  (Zeichen geteilt durch 3,5). Ohne Tokenizer ist kein exakter Wert zu haben.
- **Kein Datum als Alterssignal**, siehe oben.

---

## Umgesetzt

1. `kern/gedaechtnis.py` samt 34 Tests
2. Sprachschlüssel in `de.json` und `en.json`, Parität geprüft
3. `notizen_tabelle.py` und `gedaechtnis_detail.py`
4. Einbau in `app.py`, Taste `m`, Laden beim Öffnen des Tabs
5. Tore grün: `ruff`, `mypy` (strict), 133 Tests
6. README in beiden Sprachen

Zwei Funde aus dem Bau, die vorher niemand auf dem Zettel hatte:

- **Die Übersicht war nie zu sehen.** Die Tabelle setzt den Cursor beim
  Aufbau auf die erste Zeile, damit sprang sofort die Detailansicht an. Der
  Cursorstand ist eben keine Auswahl - die Tabelle führt sie jetzt getrennt,
  und `Esc` führt zurück zur Übersicht.
- **Der i18n-Test hatte keine Prüfung auf unbenutzte Schlüssel**, die
  wertvollste der vier. Sie ist ergänzt und hat sofort 19 tote Schlüssel im
  Bestand gefunden (`head.*`, `tip.*`, `start.*`, `app.subtitle`,
  `log.refreshed`, `log.unreachable`). Sie stehen als benannte Altlast im
  Test, damit die Prüfung ab sofort für alles Neue greift. Ob sie gelöscht
  werden, entscheidet Michael - das gehörte nicht zu dieser Aufgabe.

## Später

- Zusammenführen mehrerer erledigter Notizen in eine Sammelnotiz, samt Pflege
  des Index. Das ist der Hebel, der wirklich Index-Zeilen spart.
- Löschen mit zwingender Index-Pflege.
- Ein Blick auf den Verweisgraphen.
