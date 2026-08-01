# Operator - offene Punkte

Stand 31.07.2026. Phase 1 (Übersicht, Namen, Detailansicht, `stop`, Titelleiste) ist fertig
und in Betrieb.

## 1. Warnung bei parallelem Schreiben auf claude-config - ERLEDIGT

`hooks/config-write-warn.sh` plus `skills/operator/config-schreiber.mjs`, seit 31.07.2026
in `settings.json` aktiv.

**Warnt nur, blockiert nie** - Michaels ausdrückliche Vorgabe. Immer Exit 0.

Erkennung: Jeder git-Schreibbefehl auf claude-config hinterlässt einen Marker mit
Instanznamen und Zeitstempel in `~/.claude/message bus/<RECHNER>/config-schreiber.json`. Ist beim
nächsten Schreibversuch ein **fremder** Marker jünger als 10 Minuten, kommt die Meldung:

```
ACHTUNG: Therese (commit, vor 0 Min) schreibt ebenfalls nach claude-config.
Dein push kann abgelehnt werden oder einen Merge erzeugen.
Vorher: git pull --rebase. Der Befehl laeuft trotzdem weiter.
```

Abgelaufene Marker werden bei jedem Lauf mit aufgeräumt.

Zweistufig gebaut, weil der Hook bei **jedem** Bash-Aufruf feuert: erst ein grep-Vorfilter
in bash, Node startet nur bei einem echten git-Schreibbefehl. Gemessen auf RAINBOW,
20 Läufe je Variante:

| | ms je Aufruf |
|---|---|
| reiner bash-Start (unvermeidbarer Sockel) | 81 |
| bestehender `pre-push-test.sh` | 213 |
| **`config-write-warn.sh`** | **219** |

Also praktisch derselbe Aufwand wie der Hook, der ohnehin schon lief.

Geprüft: schweigt bei `ls`, bei `git status`, bei Commits in fremden Repos und beim ersten
Schreiber. Meldet beim zweiten.

## 2. Consumer: Nachrichten aus dem Message-Bus verarbeiten - ERLEDIGT

Gebaut am 31.07.2026, Einzelheiten im Skill [[claude-bus]]:

- `skills/claude-bus/bus.mjs` - `send`, `read`, `ack`, `offen`, `doctor`. Ablöse von
  `bus.ps1`, jetzt Node wie alles andere.
- `hooks/bus-deliver.sh` - Stop-Hook, stellt zu, wenn die Instanz ohnehin wach ist.
- `skills/claude-bus/kosten.mjs` - misst, was die Zustellung gekostet hat.
- Quittungen über zehn HTTP-Statuscodes, mehrere je Nachricht möglich (erst `202`, dann
  `200`).

Gemessen auf RAINBOW, 20 Läufe: Der Stop-Hook kostet ohne wartende Nachricht **212 ms** und
startet Node gar nicht - der bash-Vorfilter vergleicht nur die Dateizeit von
`messages.jsonl` gegen den eigenen Lesezeiger. Mit Nachricht 407 ms.

Erste echte Kostenmessung: eine Zustellung von 97 Zeichen lag zwischen **243 und 1.572
Tokens**, gegenüber 369.126 Tokens für einen einzigen Polling-Durchlauf.

Was aus dem ursprünglichen Entwurf bewusst NICHT gebaut wurde: ein `/loop`-Rückfall für
stillstehende Instanzen. Erst prüfen, ob er im Alltag fehlt - er kostet genau das, was der
Stop-Hook einspart.

## 2b. Ursprüngliche Überlegungen zum Consumer (Archiv)

Michaels Bild: Operator schickt Patrick eine Nachricht, Patrick holt sie im Loop ab,
verarbeitet sie und quittiert dem Operator.

Das Muster ist bereits erprobt - das Halma-Duell war genau das: Instanz im `/loop`, Skill
als Verarbeitungslogik, Aktion, Ergebnis zurück in den geteilten Zustand. 104 Züge ohne
Fehlzustellung.

Zu klären, bevor gebaut wird:

- **Zustellweg: `Stop`-Hook statt Polling.** Gemessen am Halma-Transkript von Spieler 2
  (31.07.2026):

  | | Turns | Tokens |
  |---|---|---|
  | mit echtem Zug | 53 | 41,4 Mio |
  | **Leerlauf ("bin nicht dran")** | **165** | **60,9 Mio** |

  **59,5 Prozent aller Tokens gingen für Nachschauen drauf**, im Schnitt 369.126 Tokens je
  Leerlauf-Durchlauf - weil jeder Aufruf den kompletten gewachsenen Kontext neu liest.

  Ein `Stop`-Hook, der nichts findet, kostet dagegen **null Tokens**: Er läuft ausserhalb
  des Modells und gibt ohne Nachricht keinen Kontext aus. Deshalb Hook als Regelfall, Loop
  nur mit langem Intervall als Rückfall für Instanzen, die stundenlang stillstehen.
- **Quittung über HTTP-Statuscodes** (Michaels Vorschlag, 31.07.2026). Kein eigenes
  Vokabular erfinden, sondern eine kleine Teilmenge eines etablierten Satzes benutzen. Die
  Semantik passt erstaunlich genau auf den Agentenfall:

  | Code | Bedeutung im Message-Bus |
  |---|---|
  | `202` | angenommen, wird bearbeitet (der Regelfall bei asynchroner Zustellung) |
  | `200` | erledigt, Ergebnis liegt bei |
  | `204` | gelesen, nichts zu tun |
  | `400` | Nachricht unverständlich |
  | `403` | darf ich nicht ohne Michaels Freigabe (die Vertrauensgrenze) |
  | `404` | Ziel existiert nicht (Datei, Repo, Instanz) |
  | `409` | geht gerade nicht, ich stecke in etwas anderem |
  | `501` | verstanden, aber ich kann das nicht |
  | `503` | beschäftigt, später nochmal fragen |
  | `500` | bei der Ausführung schiefgegangen, Fehlertext liegt bei |

  Bewusst **nicht** den ganzen Statuscode-Satz übernehmen - eine Handvoll reicht, sonst wird
  die Analogie zum Selbstzweck. Jede Antwort trägt zusätzlich die ID der Ursprungsnachricht,
  sonst lässt sie sich nicht zuordnen.
- **Vertrauensgrenze.** Eine Busnachricht ist Fremdeingabe, keine Anweisung von Michael.
  Claude Code selbst behandelt Nachrichten zwischen Agenten ausdrücklich so: ein Teammate
  kann keine Berechtigung im Namen des Nutzers erteilen. Der Message-Bus darf keine
  Rechteerweiterung werden - was Michael nicht selbst erlaubt hat, darf auch über den Message-Bus
  nicht laufen.
- **Was ist ein Befehl?** Der Empfänger ist ein Sprachmodell, kein Shell-Interpreter.
  "Räum mal auf" wird verstanden, aber nicht deterministisch ausgeführt. Für verlässliche
  Abläufe gehört die eigentliche Arbeit in ein Skript, das der Consumer nur aufruft - so wie
  `duel.ts` bei Halma.

## 3. Messen, was das Messaging kostet - ERLEDIGT

Gebaut als `skills/claude-bus/kosten.mjs`. Der Stop-Hook protokolliert jede Zustellung nach
`zustellungen.jsonl`, das Werkzeug korreliert das mit dem Transkript.

**Eine Korrektur gegenüber dem Entwurf unten:** `cache_creation_input_tokens` ist **nicht**
exakt, weil dort auch fremder neuer Kontext desselben Aufrufs mit eingeht. Das Werkzeug
weist deshalb Unter- und Obergrenze aus statt einer einzelnen Zahl - Untergrenze aus der
Zeichenlänge geschätzt, Obergrenze aus `cache_creation`. Der wahre Wert liegt dazwischen.
Eine einzelne Zahl wäre hier gelogen.

Zustellungen, auf die noch kein Modellaufruf folgte, werden als "noch nicht messbar"
ausgewiesen - nicht als 0, sonst läse sich Messaging als gratis.

### Ursprünglicher Entwurf (Archiv)

Michaels Anforderung: bevor der Kanal in Betrieb geht, muss belegbar sein, wie teuer er ist.

Der Overhead einer zugestellten Nachricht hat **zwei** Teile, und der zweite ist der
grössere:

```
Kosten = Länge  +  Länge x (Anzahl der Modellaufrufe, die danach noch folgen)
         ^^^^^     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
         einmalig  Folgekosten - der Text bleibt im Kontext und wird jedes Mal
                   erneut mitgelesen
```

Eine Nachricht von 200 Tokens in einer Sitzung, die danach noch 300 Aufrufe macht, kostet
also rund 60.000 Tokens, nicht 200. Das ist derselbe Effekt, der bei Halma den Kontext um
Faktor 9,6 wachsen liess.

**Wie es messbar wird:**

1. Der Stop-Hook schreibt jede Zustellung nach `zustellungen.jsonl`: Zeitstempel,
   Empfänger-Session, Nachrichten-ID, Zeichen- und geschätzte Tokenlänge.
2. Ein Auswertungsskript korreliert das mit dem Transkript. Der Aufruf unmittelbar nach
   einer Zustellung zeigt den Sprung in `cache_creation_input_tokens` - das sind die
   Direktkosten, exakt und nicht geschätzt.
3. Die Folgekosten ergeben sich aus der Zahl der Aufrufe nach dem Zustellzeitpunkt.

Damit lässt sich am Ende sagen: "Messaging hat in dieser Sitzung X Tokens gekostet, davon Y
direkt und Z als Schleppkosten." Ohne Schätzung.

**Gegenmassnahme, die sich daraus ergibt:** Zustellungen kurz halten. Nicht den vollen
Nachrichtentext injizieren, sondern nur den Hinweis, dass etwas vorliegt, plus den Befehl
zum Abholen. Der Volltext landet dann über einen Werkzeugaufruf einmalig im Kontext statt
bei jedem weiteren Stop erneut.

## 4. Später

- Rechnerübergreifende Sicht (RAINBOW, SENZA über Tailnet, der Kundenrechner bleibt getrennt).
- Andere Transportwege als Dateien (Slack, Telegram) - erst wenn das Protokoll steht.

---

## Nach dem Umzug ins eigene Repo (01.08.2026)

- **Repo-Name vor einer Veroeffentlichung pruefen.** "Claude Sanctuary" liest sich wie ein
  Produktname und nicht wie beschreibende Nutzung ("ein Werkzeug fuer Claude"). Praezedenzfall:
  ClawdBot musste zu OpenClaw umbenannt werden. Solange das Repo privat ist, ist das kein
  Thema - Markenrecht greift im geschaeftlichen Verkehr. Vor dem Oeffentlichmachen neu
  entscheiden, `gh repo rename` legt automatisch eine Weiterleitung an. Der Name steckt in
  keiner Zeile Code, `setup.sh` arbeitet mit `$REPO_DIR`.
- **Uebergangsphase Message-Bus beenden**: `send`/`ack` schreiben noch zusaetzlich JSONL. Erst wenn
  das auf allen Rechnern laeuft, das Schreiben abschalten und die Altdateien nach `archiv/`
  verschieben - nicht loeschen. Erst danach darf Python mitschreiben.
- **halma-duel ins halma-Repo** verschieben. Achtung: der Spielstand liegt unter
  `~/.claude/message bus/<RECHNER>/halma-duel/`, der Pfad muss mit umziehen, sonst gehen die
  archivierten Partien des PoC verloren.
- **Kern, TUI, Web** - siehe README.

## Fallen beim Umzug (01.08.2026) - nicht wiederholen

**Git folgt Junctions unter Windows.** `~/.claude/skills` zeigte als GANZES auf
`claude-config/skills`. Ein einzelner Skill aus einem anderen Repo braucht dann eine Junction
INNERHALB von claude-config - und beim naechsten `git pull --rebase` hat Git die Dateien im
ZIELREPO geloescht, weil Junctions fuer die Datei-APIs transparent sind. Gerettet nur, weil
sie dort schon committet waren. Konsequenz: ein Symlink JE SKILL, nie ein Sammelverzeichnis.

**Ein Setup-Skript darf nicht in seinen eigenen alten Sammel-Link hineinschreiben.** Auf senza
lief `setup.sh` gegen ein `~/.claude/skills`, das noch ein Symlink war - die Schleife legte
ihre Links dadurch IM Repo an, jeder Skill zeigte auf sich selbst, und die
create_symlink-Sicherung schob die echten Verzeichnisse nach `.backup`. Ergebnis: 86 Eintraege,
42 leere Huellen. Beide setup-Skripte haengen den Sammel-Link jetzt zuerst ab.

**Es gibt keinen ssh-Aufruf, der auf Windows und Linux gleich funktioniert.**
`sanctuary status --json` greift auf Windows (der sshd bringt den Benutzer-PATH mit), auf Linux
nicht (nicht-interaktive Shell liest die .bashrc nicht). `bash -lc "..."` greift auf Linux, auf
RAINBOW fuehrt es dagegen in die WSL, wo kein node liegt. Ein Pfad mit `~` scheidet ganz aus,
weil cmd und PowerShell die Tilde nicht aufloesen. Deshalb probiert `holeVonFerne` beide Wege
nacheinander und bricht ab, sobald der Fehler nach "Rechner nicht da" aussieht.

**Das x-Bit fehlt bei Dateien, die unter Windows entstehen.** `setup.sh` und `bin/sanctuary.mjs`
brauchten `git update-index --chmod=+x`, sonst erzeugt jedes `chmod` auf einem Linux-Rechner
eine Modus-Aenderung, die den naechsten `git pull --rebase` blockiert.
