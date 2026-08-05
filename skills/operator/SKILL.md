---
name: operator
description: Übersicht und Steuerung aller laufenden Claude-Code-Instanzen auf diesem Rechner - Tabelle mit Name, Status, Ordner, Laufzeit und Kontextgröße, Detailansicht je Instanz, Live-Ansicht und Beenden einzelner Instanzen. Jede Instanz bekommt einen festen Namen aus einem Pool. Verwende diesen Skill, wenn Michael "Operator", "welche Instanzen laufen", "status <Name>", "stop <Name>", "was machen die anderen", "/operator" sagt oder wissen will, wie voll der Kontext einer Sitzung ist.
---

# Operator

Übersicht und leichte Steuerung aller Claude-Code-Instanzen auf diesem Rechner.

```bash
OP=~/.claude/skills/operator

node $OP/operator.mjs status            # Tabelle
node $OP/operator.mjs status Agatha     # Detailansicht einer Instanz
node $OP/operator.mjs status all        # Detailansicht aller Instanzen
node $OP/operator.mjs status --tokens   # zusätzlich Gesamtverbrauch (langsamer)
node $OP/operator.mjs status --json     # maschinenlesbar statt Tabelle
node $OP/operator.mjs status --mesh     # zusätzlich die Rechner aus mesh.json
node $OP/operator.mjs watch 2 --json    # NDJSON-Strom, eine Zeile je Takt
node $OP/operator.mjs watch 10          # alle 10 s neu zeichnen
node $OP/operator.mjs stop Patrick      # beenden, fragt vorher nach
node $OP/operator.mjs stop Patrick --force   # ohne Rueckfrage
node $OP/operator.mjs names             # vergebene Namen
node $OP/operator.mjs motif [name]      # Namensmotive anzeigen oder umschalten
node $OP/operator.mjs reset-names       # beendete Sitzungen aufräumen
node $OP/operator.mjs become-operator   # diese Sitzung auf "Operator" umbenennen

node $OP/update.mjs --check             # installierte Claude-Version
node $OP/update.mjs SENZA --method npm  # Claude auf einem anderen Rechner aktualisieren

node $OP/starte.mjs                     # neue Instanz mit Namen im Tab-Titel
node $OP/starte.mjs Klara               # bestimmter Name
node $OP/starte.mjs -- --resume         # alles nach -- geht an claude durch
```

```
  Claude-Instanzen auf RAINBOW   31.07.26, 23:03

  Name         Status Ordner                  Modell      Läuft   Kontext
  -----------------------------------------------------------------------
* Operator    busy   ~                       Opus 5     1h 36m      181k
  Charlene     idle   ~                       Opus 5     1h 35m        8k
  Jeanne      idle   …\retro-text-effects.js Opus 5        28m+       6k
  Lino       idle   ~                       -             34m         -
  Therese     idle   ~\Repos\webshop             Opus 5        27m+     641k

  5 Instanzen, davon 1 beschäftigt   * = diese Sitzung   + = fortgesetzte Sitzung
  1 Sitzung(en) mit großem Kontext: Therese - dort lohnt /compact
```

Ein `-` beim Modell heißt, dass die Sitzung noch keinen Modellaufruf hatte - dann steht
auch beim Kontext nichts. Die Kurzform kommt aus der Modell-ID im Transkript
(`claude-haiku-4-5-20251001` wird zu `Haiku 4.5`). Läuft eine Sitzung im 1M-Fenster, steht
`Opus 5 1M` - das erklärt, wie ein Kontext überhaupt 600k erreichen kann.

## Warum Node und nicht PowerShell

Gemessen am 31.07.2026 auf RAINBOW, beide als eigener Prozess, fünf Läufe:

| | PowerShell 5.1 | Node 24 |
|---|---|---|
| Startzeit je Aufruf | 235 ms | **51 ms** |
| Spitzenspeicher | 83,7 MB | **48,5 MB** |

Node ist 4,6 mal schneller und braucht 42 Prozent weniger Speicher. Dazu kommt: es läuft auf
allen Rechnern (Windows, Linux, macOS), kennt JSON nativ, und die PowerShell-5.1-Fallen
entfallen - kein BOM-Zwang, keine `{0,>7}`-Formatstrings, kein leeres `.Count` bei
einelementigen Ergebnissen.

**Bun, Nuitka und `scriptc` wurden geprüft und bringen unter Windows nichts.** Gemessen am
31.07.2026, je 20 Läufe: Node 151 ms für `statusline.mjs`, Bun 148 ms, eine mit
`bun build --compile` erzeugte Binary 147 ms. Der Grund steht eine Zeile tiefer - `cmd.exe`
mit `exit` kostet allein schon 69 ms, `where.exe` 105 ms. **Der Prozessstart ist der Boden,
nicht die Laufzeit darüber**, und den unterbietet kein Compiler. Auf Linux und macOS wäre
Bun deutlich schneller, unter Windows verschwindet der Vorteil hinter den Fixkosten.
Der Hebel heisst deshalb weniger Prozesse, nicht schnellere: allein der npm-Shim von Bun
kostete 114 ms extra, weil er ein zusätzlicher Prozess ist. Details in
`reference_windows_prozessstart_boden`.

**Es gibt deshalb bewusst nur eine Fassung**, keine getrennte für Windows und Linux. Zwei
Fassungen bedeuten zwei Fehlerquellen und Auseinanderdriften. Das war schon beim Namenspool
zu sehen, der kurzzeitig doppelt existierte und deshalb in `namenspool.json` ausgelagert
wurde.

## Warum es keine Anmeldung gibt

Die Instanzliste kommt von Claude Code selbst - seit dem 01.08.2026 direkt aus
`~/.claude/sessions/<pid>.json`, mit `claude agents --json` als Rückfall. Dort steht je
Sitzung PID, Arbeitsverzeichnis, Session-ID und der Live-Status `idle`/`busy`. Die Registry
ist damit schon vorhanden - es braucht keinen Anmeldevorgang, keinen Daemon und keinen
Broker. Jede Instanz taucht automatisch auf.

Unter Windows findet `execFileSync` ein blosses `claude` nicht, weil das dort ein Wrapper
ist. Deshalb wird `CLAUDE_CODE_EXECPATH` bevorzugt, mit Shell-Aufruf als Rückfall.

## Namen und Motive

`namenspool.json` hält **mehrere Motive** und merkt sich, welches aktiv ist:

| Schlüssel | Motiv | Namen |
|---|---|---|
| `heilige` | Katholische Heilige | 26 |
| `schauspieler` | Schauspieler | 22 |
| `comicmotiv` | Comicmotiv | 19 |

```bash
node $OP/operator.mjs motiv            # anzeigen, aktives ist markiert
node $OP/operator.mjs motiv comicmotiv    # umschalten
```

Ein weiteres Motiv ist ein zusätzlicher Eintrag unter `pools` in `namenspool.json`, mehr
nicht. Namen dürfen nur Buchstaben, Ziffern und Bindestrich enthalten - `Piet` geht,
Umlaute und Leerzeichen nicht, weil der Name sonst die per `printf` gebaute JSON-Ausgabe des
Hooks zerlegen könnte.

**Reservierte Namen stehen vor jedem Motiv.** `reserviert` auf oberster Ebene von
`namenspool.json` hält Namen, die unabhängig vom aktiven Motiv als erste vergeben werden -
derzeit `Operator`. Die erste Instanz heisst damit immer so, egal welches Motiv läuft, und
ein neues Motiv erbt das automatisch. Der Eintrag steht bewusst **nicht** in jeder
Motivliste: dreifache Pflege ist genau der Weg, auf dem der Pool schon einmal auseinander
gelaufen ist.

Das koppelt allerdings "als erste gestartet" an "hier bediene ich den Operator", und das ist
nicht dasselbe. Wer ein bestimmtes Fenster meint, vergibt den Namen gezielt:
`node $OP/starte.mjs Operator`. Beliebige Namen sind dabei erlaubt, sie müssen nur frei sein
und dem Zeichenschema entsprechen.

**Pflicht beim Skill-Aufruf: wer den Operator bedient, heisst auch so.** Wird dieser Skill
aufgerufen und die eigene Sitzung trägt noch einen Poolnamen, ist als Erstes

```bash
node $OP/operator.mjs werde-operator
```

auszuführen - ohne Rückfrage, das ist Michaels Vorgabe vom 01.08.2026. Das Kommando schreibt
`namen.json` um, gibt den bisherigen Namen wieder frei und wirkt damit auf Tabelle **und**
Statuszeile, weil beide aus derselben Datei lesen. Die Statuszeile zeigt den neuen Namen beim
nächsten Neuzeichnen. Hält eine **laufende** Sitzung den Namen bereits, bricht das Kommando ab
statt ihn wegzunehmen - sonst stünden zwei Instanzen unter einem Namen in der Tabelle. Hält ihn
eine beendete Sitzung, wird die Zuordnung gelöst. Der Zielname kommt aus `reserviert[0]` in
`namenspool.json`, ist also nicht fest verdrahtet.

In der Zählung von `names` werden reservierte Namen getrennt ausgewiesen - sonst hätte
"Comicmotiv" plötzlich 20 statt 19 Namen.

**Umschalten wirkt nur auf noch nicht vergebene Namen.** Laufende Instanzen behalten ihren -
sonst wäre die Übersicht mitten im Betrieb wertlos. `names` kennzeichnet Einträge aus einem
anderen Motiv, `reset-names` räumt beendete Sitzungen weg.

Die Ladelogik liegt in `pool.mjs`, das Operator, Starter und Hook gemeinsam benutzen. Vorher
stand sie dreifach da - genau so fängt Auseinanderdriften an. Aus demselben Grund liegt die
Instanzabfrage in `instanzen.mjs`: der Hook braucht sie für Stufe 2, könnte sie aber nicht
aus `operator.mjs` holen, ohne dessen CLI-Teil mitzuladen.

Die Zuordnung Session-ID zu Name liegt in `~/.claude/message bus/<RECHNER>/namen.json`.

**Geht der Pool zur Neige, sucht der Hook in drei Stufen weiter** - Michaels Vorgabe: erst
den Pool zu Ende abarbeiten, erst dann aufräumen.

1. Ein freier Name des aktiven Motivs (Wolfram, Salma, Patsy ...).
2. Ist keiner mehr da, werden **beendete Sitzungen automatisch aufgeräumt** und es wird
   erneut gesucht. Das kostet den Aufruf von `claude agents --json`, also knapp eine
   Sekunde - deshalb passiert es erst hier und nicht bei jedem Sitzungsstart.
3. Laufen wirklich alle: ein Name aus einem **anderen Motiv**. Ein Heiligenname ist immer
   noch besser als `Snorre-21`.

Erst wenn alle 68 Namen aller Motive gleichzeitig belegt sind, wird durchnummeriert.

**Eine leere Instanzliste löscht nichts.** `claude agents --json` liefert im Fehlerfall
dasselbe wie bei "nichts läuft", nämlich ein leeres Array. Wer daraus Einträge entfernt,
nimmt im Fehlerfall allen laufenden Instanzen den Namen - deshalb räumt Stufe 2 nur auf,
wenn die Abfrage tatsächlich Instanzen gemeldet hat, und fällt sonst auf Stufe 3 durch.
`reset-names` bleibt daneben als Handgriff bestehen, wenn die Liste einfach sauber sein soll.

Es gibt **zwei Wege**, wie eine Instanz zu ihrem Namen kommt:

**1. SessionStart-Hook** (`hooks/session-name.sh` ruft `whoami.mjs`). Greift bei jedem neu
geöffneten Fenster automatisch. Die Instanz erfährt ihren Namen als Kontext und reagiert
darauf, wenn Michael sie so anspricht. Der Hook kann aber **nicht** den Terminal-Titel
setzen.

**2. `starte.mjs`** als Wrapper. Sucht einen freien Namen, reicht ihn über
`CLAUDE_INSTANZ_NAME` weiter und startet `claude -n <Name>`. Das Flag `-n/--name` setzt einen
Anzeigenamen, der in der Prompt-Box, im `/resume`-Picker **und in der Terminal-Titelleiste**
erscheint. Nur so steht der Name im Tab. Der Hook erkennt die Vorgabe und übernimmt sie,
statt einen zweiten Namen zu vergeben.

## Wo der Name sichtbar ist

Beide Wege oben vergeben einen Namen, aber **sichtbar** war er lange nur bei Weg 2. Wer
einfach `claude` tippt, sah im Tab den KI-generierten Titel ("Im Bus nachschauen") und den
Namen nirgends - Claude Code überschrieb den Tab-Titel laufend mit diesem Titel. Seit dem
03.08.2026 hält `titel.mjs` dagegen (eigener Abschnitt unten).

Deshalb gibt es `statusline.mjs`: Claude Code schickt die Sitzungsdaten als JSON auf stdin
und zeigt die Ausgabe in einer **eigenen Zeile über den eingebauten Badges** - die Zeile mit
`bypass permissions` bleibt also erhalten. Eingetragen in `settings.json`:

```json
"statusLine": { "type": "command", "command": "node ~/.claude/skills/operator/statusline.mjs" }
```

Die Zeile zeigt `Name · Ordner · Modell · Prozent Kontext`, der Prozentwert ab 70 gelb und ab
90 rot. Der Name kommt über `session_id` aus `namen.json`, also aus derselben Quelle wie die
Operator-Tabelle. Fehlt dort ein Eintrag, greift `session_name` als Rückfall.

Wichtig für Michaels Aufbau: Der Pfad steht mit **Schrägstrichen** und `~` in der Config.
Unter Windows führt Claude Code das Kommando über Git Bash aus, und dort verschluckt ein
unmaskierter Backslash die Trennzeichen - das Skript startet dann ohne sichtbaren Fehler
gar nicht. So bleibt derselbe Eintrag auf allen Rechnern gültig, was nötig ist, weil
`settings.json` über claude-config auf alle synct.

### Der Titel: Name und Aufgabe zugleich

`titel.mjs` hängt als `UserPromptSubmit`-Hook (über `hooks/session-title.sh`) am Prompt und
gibt `sessionTitle` aus. Claude speichert das als **zwei** Einträge in der Sitzungsdatei,
`custom-title` und `agent-name`. In der Titel-Priorität `agentName || customTitle || aiTitle`
gewinnt damit der eigene Titel - nur so klebt der Name stabil im Tab.

Der Preis fiel beim Resume-Hinweis auf: `claude --resume "Luzie · claude-sanctuary"` sagte
nicht mehr, woran die Sitzung sass, weil die automatische Zusammenfassung verdrängt wurde.
Seit dem 05.08.2026 schlägt der Hook sie deshalb selbst nach. Sie steht als
`{"type":"ai-title","aiTitle":"..."}` in derselben Datei und wird bei jedem Prompt neben dem
`custom-title` fortgeschrieben, liegt also verlässlich am Dateiende. Der Titel lautet nun
`<Name> · <Aufgabe>`, der Ordner entfällt (er steht in der Statuszeile).

Drei Punkte, die den Bau bestimmt haben:

- **Nicht die ganze Datei lesen.** Sitzungsdateien werden zweistellig megabytegross (gemessen:
  43 MB), und der Hook läuft bei jedem Prompt. Gelesen werden nur die letzten 64 KB
  (`SCHWANZ_BYTES`) - 18 ms bei der 43-MB-Datei, unabhängig von der Länge. Der Aufschlag
  gegenüber der Fassung ohne Nachschlagen liegt bei rund 11 ms pro Lauf und verschwindet im
  Node-Prozessstart (~120 ms).
- **Den Dateipfad nicht auf die Escaping-Regel stützen.** Claude verstümmelt den
  Arbeitspfad zum Ordnernamen (`C:\ZusatzSW\x` wird `C--ZusatzSW-x`, auch der Unterstrich in
  `BUERO_PC2` wird zum Bindestrich). Das ist nirgends zugesichert, also nur ein schneller
  Versuch - danach werden die Projektordner abgesucht.
- **Nicht jede Sitzung bekommt eine Zusammenfassung.** Gemessen am 05.08.2026 hatten nur 2 von
  12 Sitzungen überhaupt einen `ai-title`. Woran das liegt, ist **unbelegt**. Fehlt er, fällt
  der Titel auf `<Name> · <Ordner>` zurück, also auf das bisherige Verhalten.

## Was der Operator kann und was nicht

| Wunsch | Stand |
|---|---|
| `status` Tabelle | geht |
| `status <Name>` Detail | geht: Modell, letztes Werkzeug, Kontext, Verbrauch, aktuelle Aufgabe |
| `status all` Detail für alle | geht: ein Sammellauf, dann jede Instanz nacheinander |
| `watch` Live-Ansicht | geht |
| `stop <Name>` | geht per Prozesssignal, fragt vorher nach |
| Name im Tab-Titel | geht: `titel.mjs` setzt bei jedem Prompt `<Name> · <Aufgabe>`, unabhängig vom Start |
| Name dauerhaft sichtbar | geht über die Statuszeile, unabhängig vom Start |
| maschinenlesbare Ausgabe | geht: `--json`, mit `watch` als NDJSON-Strom |
| rechnerübergreifende Sicht | geht: `--mesh`, Hosts in `mesh.json` |
| Claude aktualisieren | geht: `update.mjs`, lokal und über ssh |
| `compact <Name>` | **geht nicht** |

## Englische Befehle, deutsche Aliase (02.08.2026)

Michaels Vorgabe: die Kommandozeile spricht Englisch. Umbenannt wurden
`motiv` zu `motif`, `werde-operator` zu `become-operator`, im Bus
`auftraege` zu `tasks`, `verlauf` zu `history`, `offen` zu `open`,
`kosten` zu `cost`, `uebernehmen` zu `receive`, dazu die Flags `--alle`
zu `--all`, `--von` zu `--from`, `--erwartet-quittung` zu
`--expect-receipt` und `--einrichten` zu `--setup`.

**Die deutschen Namen bleiben als stille Aliase bestehen, und das ist keine
Bequemlichkeit.** `uebernehmen` ruft ein Rechner auf dem anderen per ssh auf
(`zustellenAn` in `bus.mjs`). Dessen Stand kann älter sein - die Repos werden
je Rechner von Hand gezogen. Wer den alten Namen entfernt, bricht die
Zustellung zu jedem Rechner, der noch nicht nachgezogen hat. Aus demselben
Grund SENDET `zustellenAn` weiterhin `uebernehmen`: das versteht jede Fassung,
`receive` nur die neue. Umstellen erst, wenn alle Rechner nachgezogen haben.

## Aktualisieren: `update.mjs`

`sanctuary update [RECHNER] [--method claude|npm|winget|choco|brew]`, mit
`--check` nur die Version melden, mit `--json` maschinenlesbar.

**Das Verfahren wird mitgegeben und NICHT erraten.** Wie Claude Code
installiert wurde, weiss nur der Anwender - es steht in den Einstellungen der
Oberfläche. Ein geratenes Verfahren ist schlimmer als keins: `winget upgrade`
auf einer npm-Installation meldet Erfolg und ändert nichts.

Für den fernen Rechner dieselben zwei Anläufe wie beim Bus (erst direkt, dann
über `bash -lc`), weil `~/.local/bin` in einer nicht-interaktiven Shell fehlt.

**Windows-Wrapper NICHT über `shell: true` aufrufen.** `claude`, `npm` und
`winget` sind dort Skripte, die `execFileSync` ohne Hilfe nicht findet. Der
naheliegende Schalter `shell: true` ist seit Node 22 abgekündigt und meldet
DEP0190 auf stderr (gesehen am 02.08.2026), weil die Argumente dann unmaskiert
aneinandergehängt werden. Stattdessen `cmd /c` davorsetzen - damit bleibt die
Argumentliste eine Liste.

## Ausgabe für Werkzeuge: `--json` und der Strom

Die Tabelle ist für Menschen gebaut. Wer sie zurückparst, hat ANSI-Farben im Text und bricht
bei der nächsten Layoutänderung - deshalb liefert `--json` dieselben Daten roh: ein Objekt mit
`rechner`, `zeit`, `anzahl` und `instanzen[]`, je Instanz alle Felder aus `sammle()`
(`name`, `status`, `pid`, `sessionId`, `selbst`, `laufzeit`, `gespraech`, `fortgesetzt`,
`pfad`, `post`, `kontext`, `tokens`, `modell`, `letztesTool`, `letzteZeit`, `aufgabe`,
`aufrufe`, `nachCompact`, `cwd`). `status <Name> --json` filtert auf eine Instanz.

**Mit `watch` wird daraus NDJSON** - eine Zeile je Takt, kompakt, ohne Farben. Das ist für
die geplante Agenten-TUI gedacht und der eigentliche Grund für das Feature: ein langlebiger
Prozess, den die Gegenseite über eine Pipe zeilenweise mitliest, statt im Sekundentakt einen
neuen zu starten. Der Prozessstart kostet unter Windows 70-105 ms
([[reference_windows_prozessstart_boden]]), `claude agents --json` weitere 728 ms - bei
60 Aufrufen je Minute ist das der gesamte Kostenblock.

**gzip lohnt dabei nicht**, gemessen am 01.08.2026 mit nachgebauten Datensätzen:

| Instanzen | roh | gzip | Rechenzeit |
|---|---|---|---|
| 1 | 669 B | 429 B (-36 %) | 0,6 ms |
| 5 | 3.069 B | 621 B (-80 %) | 0,1 ms |
| 100 | 60.094 B | 3.584 B (-94 %) | 0,3 ms |

Die Rate ist gut und trotzdem bedeutungslos: selbst 100 Instanzen ergeben 60 KB, die über
eine lokale Pipe in unter einer Millisekunde durch sind. Gegen 728 ms Abfragezeit ist die
Nutzlast Rauschen. Brotli komprimiert besser, braucht bei 100 Instanzen aber 93 ms und kostet
damit mehr, als es je einspart. Auch über SSH bleibt es dabei - dort dominiert die Latenz,
und `ssh -C` könnte komprimieren, ohne dass wir etwas bauen.

## Rechnerübergreifend: `--mesh`

`mesh.json` neben dem Skript listet die Hosts (`rainbow`, `senza`, `dell`), der eigene wird
übersprungen. Abgefragt wird über ssh **derselbe Befehl** wie lokal
(`operator.mjs status --json`) - keine zweite Auswertungslogik, die auseinanderlaufen kann.
Die Namen müssen in `~/.ssh/config` stehen, das erledigt das ssh-mesh-Kit.

**Offline gemeldete Rechner werden vorher aussortiert.** Ohne das bestimmt der langsamste
Host die Gesamtzeit, denn jeder abgeschaltete kostet den vollen ConnectTimeout: gemessen
5.864 ms mit dem offline dell, obwohl lokal und senza längst geantwortet hatten.
`tailscale status --json` weiss es in 69 ms, damit sind es **1.149 ms**. Fällt die Abfrage
aus (kein Tailscale, Dienst tot), werden alle Hosts probiert - lieber langsam als eine
laufende Instanz verschweigen.

Zwei Fehlerbilder werden unterschieden, weil sie verschiedene Handgriffe brauchen:
`ssh: connect to host ... Connection timed out` heisst Rechner weg,
`keine JSON-Antwort - dort git pull noetig?` heisst, die Gegenseite kennt `--json` noch nicht.
Der rohe Parserfehler (`Unexpected token`) stand zuerst da und schickte prompt auf die
falsche Fährte.

**Zu `compact`:** Es gibt keinen dokumentierten Weg, eine fremde Sitzung von aussen zum
Kompaktieren zu bringen - kein CLI-Flag, kein Hook, keine API. Kompaktierung wird nur durch
`/compact` in der Sitzung selbst oder durch Claude Codes eigene Heuristik ausgelöst. Der
Operator kann deshalb nur **melden**, wer nah an der Grenze ist (Spalte Kontext färbt sich ab
600k gelb, ab 800k rot, plus Hinweiszeile). Getippt werden muss `/compact` dort.

## Fallstricke

- **`stop` fragt nach - und liest die Antwort vom Terminal des Aufrufers.** Bis zum
  02.08.2026 rief die Oberfläche `stop <Name> --ja` auf. Dieses Flag gibt es nicht, es
  heisst `--force`. Der Operator stellte also wie vorgesehen seine Rückfrage und hängte
  seinen Zeileneditor in die geerbte Standardeingabe - das war das Terminal der laufenden
  TUI. Ergebnis: Rückfrage mitten im Bild, Maus-Steuerzeichen überall, Oberfläche blockiert
  bis zum Timeout. Es sah nach einem Absturz aus und war keiner. Nachgestellt mit
  `sanctuary stop <Name> --ja < /dev/null`, worauf `... wirklich beenden? [j/N]` in der
  Ausgabe stand. `frage()` prüft jetzt `process.stdin.isTTY` und lehnt ohne Terminal ab,
  statt zu fragen. Die Gegenseite (`stdin=DEVNULL`) steht im python-specialist.
- **Die PID aus `sammle()` ist eine Momentaufnahme.** Ist die Instanz zwischen Abfrage und
  Signal ausgestiegen, kann das Betriebssystem dieselbe Nummer längst neu vergeben haben -
  unter Windows geschieht das schnell. Ein SIGTERM ginge dann an einen Unbeteiligten, und
  weil Windows dafür `TerminateProcess` benutzt, stirbt der ohne aufzuräumen. `stoppe()`
  prüft deshalb vorher den Prozessnamen (`tasklist` bzw. `ps -o args=`) und bricht ab, wenn
  "claude" nicht darin vorkommt - fail-closed. Auf Linux MUSS es `args=` sein und nicht
  `comm=`: auf senza liegt Claude als ELF-Binary unter
  `~/.local/share/claude/versions/2.1.220`, der blosse Prozessname trägt die Version, nicht
  den Namen (geprüft am 02.08.2026).
- **`Select-Object -First 1` hinter nativem Aufruf** verfälscht `$LASTEXITCODE`. Betraf die
  alte PowerShell-Fassung, dort lief der Git-Guard deshalb erst nicht an.
- **Keine Anführungszeichen im Hook-Text.** Die JSON-Ausgabe wird per `printf` gebaut, weil
  `jq` nicht auf allen Rechnern vorhanden ist. Ein einzelnes `"` zerlegt sie.
- **Ein Resume behält den Namen, setzt aber die Laufzeit zurück.** Die Zuordnung in
  `namen.json` hängt an der Session-ID, und `claude --resume` führt dieselbe Sitzung fort -
  Jeanne kam am 31.07.2026 nach einem Resume unter derselben ID `e238f1cd` zurück, also
  auch unter demselben Namen. Das ist so gewollt. `startedAt` aus `claude agents --json`
  misst dagegen den **Prozess**: eine neun Stunden alte Sitzung stand nach dem Resume auf
  "5m". Die Spalte zeigt deshalb ein `+`, wenn das Gespräch mehr als fünf Minuten älter ist
  als der Prozess, und die Detailansicht nennt beide Werte getrennt.
- **Der erste Transkript-Eintrag hat keinen Zeitstempel.** Er ist vom Typ `last-prompt` und
  trägt nur `leafUuid` und `sessionId`. Wer für das Gesprächsalter nur Zeile eins parst,
  bekommt `null` und sieht den Resume nie - beim ersten Versuch genau so passiert.
  `beginnDesGespraechs` liest deshalb 64 KB und nimmt den ersten Eintrag **mit** `timestamp`.
- **Nach einem Compact gibt es keinen Modellaufruf.** Die Kontextspalte kam ursprünglich nur
  aus dem `usage`-Block des letzten Assistant-Turns - nach `/compact` blieb deshalb der alte
  Wert stehen, bis die Sitzung wieder antwortete. Belegt am 31.07.2026: Charlene zeigte 83k,
  obwohl im Transkript direkt daneben `system`/`compact_boundary` mit
  `compactMetadata.postTokens = 8460` stand. Der Operator liest jetzt beide Marker rückwärts,
  der jüngere gewinnt, und die Detailansicht schreibt "(Stand nach Compact)" dazu. Ohne das
  war die Zeile "dort lohnt /compact" nach genau dem empfohlenen Compact weiter zu sehen.
- **Transkripte werden vom Ende her gelesen, nicht komplett.** Die Annahme "bei wenigen MB
  ist ein Vollread vertretbar" hat sich überlebt: am 31.07.2026 lagen 189 MB Transkripte auf
  RAINBOW, die grösste Datei hatte 35 MB, eine laufende Sitzung 8,3 MB. Gemessen über die
  sechs grössten Dateien - Vollread 194 ms, Seek über ein 400-KB-Fenster 3 ms.
  **Der Engpass ist es trotzdem nicht:** `claude agents --json` allein braucht 970 ms von
  rund 1080 ms je `status`-Lauf. Die Umstellung spart also nur etwa 3 Prozent, verhindert
  aber, dass die Lesezeit mit Sitzungsdauer und Instanzzahl weiterwächst.
  Standardmässig werden die letzten 400 Zeilen ausgewertet, `--tokens` liest die ganze Datei.
- **`claude agents --json` war der Engpass - und ist vermeidbar.** Claude Code legt unter
  `~/.claude/sessions/<pid>.json` je laufender Sitzung eine Datei ab, deren Inhalt die Ausgabe
  des CLI-Aufrufs **vollständig enthält** (pid, sessionId, cwd, startedAt, kind, name, status)
  und zusätzlich `version` und `procStart` führt. Direkt gelesen kostet das 3 ms statt 758 ms,
  `operator status` fällt damit von rund 840 ms auf **105 ms**. Gegenprobe am 01.08.2026: beide
  Wege liefern zeichengleich dieselbe Liste. Weil das Verzeichnis nicht dokumentiert ist,
  bleibt der CLI-Weg als Rückfall bestehen - `instanzen.mjs` nimmt ihn, sobald das Verzeichnis
  fehlt, und `OPERATOR_INSTANZEN_VIA_CLI=1` erzwingt ihn für einen Vergleich.
  **Pflicht ist die Lebendprüfung:** die Datei wird bei Statuswechseln geschrieben, nicht per
  Herzschlag, ein Zeitstempel war im Test 285 s alt. `process.kill(pid, 0)` stellt nichts zu,
  sondern prüft nur die Existenz - `EPERM` bedeutet dabei "lebt, gehört jemand anderem" und
  zählt als lebend.
- **Eine Wartezeit in der Statuszeile kostet bei JEDER Nachricht.** `nameFuer()` fasste dreimal
  im Abstand von 100 ms nach, falls der Poolname noch nicht in `namen.json` stand. Gemessen
  waren das 200 von 265 ms, also drei Viertel der Laufzeit - und zwar dauerhaft, nicht nur beim
  Sitzungsstart. Richtig ist: liegt ein Rückfall vor (der KI-Titel aus `session_name`), sofort
  den nehmen. Die Zeile wird ohnehin bei jeder Nachricht neu gezeichnet, ein Fallbackname für
  ein oder zwei Durchgänge kostet nichts.
- **Token naiv zu summieren zählt um Faktor 2 zu hoch, und das falsche dazu.** Streaming-
  Zwischenstände bekommen eigene Transkript-Zeilen: über den gesamten Bestand gemessen 22.667
  Zeilen mit `usage` zu nur **10.687 eindeutigen `message.id`** (Faktor 2,085). Deduplizieren
  nach `message.id`, dabei gewinnt der **spätere** Eintrag - first-wins lag messbar daneben.
  Schwerer wiegt der zweite Fehler: `cache_read_input_tokens` ist kein Verbrauch, sondern
  derselbe Kontext, der bei jedem Turn erneut gelesen wird. In einer Sitzung standen 1,16 Mrd
  gelesene gegen 9,9 Mio neu erzeugte Token. Echter Neuverbrauch ist
  `output + cache_creation + input`, der Cache-Anteil wird getrennt ausgewiesen.
  `<synthetic>` als Modell markiert Abbruchzeilen mit lauter Nullen und wird übersprungen.
- **Das `cwd` aus `claude agents --json` ist das Startverzeichnis, nicht das aktuelle.**
  Am 01.08.2026 stand in der Tabelle `~` für eine Sitzung auf SENZA, die in
  `~/repos/senza` arbeitete. Michael meldete den falschen Ordner, die Rohdaten gaben
  ihm recht: `claude agents --json` lieferte `"cwd": "/home/michael"`, und
  `readlink /proc/<pid>/cwd` bestätigte, dass auch der Prozess selbst dort steht - die
  Sitzung war schlicht im Home gestartet worden. Der Fehler lag also **nicht** in der
  Anzeige. Das Transkript führt dagegen in jedem Eintrag ein `cwd` mit und kannte
  `/home/michael/repos/senza`. `leseTranskript` nimmt beim ohnehin stattfindenden
  Rückwärtslauf den ersten Treffer mit, `sammle` bevorzugt ihn (`t.cwd || i.cwd`) -
  kostet keine zusätzliche I/O. Der Rückfall bleibt wichtig für Sitzungen ohne
  Modellaufruf, die noch kein Transkript haben.

## Ausblick

Phase 1 ist bis auf `stop` rein lesend. Offen:

- **Warnung bei parallelem `update-skill`**: mehrere Instanzen schreiben gleichzeitig nach
  `claude-config` und überholen sich (belegt durch Merge-Commit `91a8d48` und mehrfaches
  Rebasen am 31.07.2026). Michael will ausdrücklich eine Warnung, **keine Sperre**.
- Nachrichten an Instanzen über [[claude-bus]].
- Message-Bus-Nachrichten überwachen: es gibt `read` (eigene neue) und `offen` (eigener Stand), aber
  keine Sicht auf **alle** Nachrichten und kein Löschen oder Bearbeiten. `messages.jsonl` und
  `receipts.jsonl` sind bewusst append-only, ein Widerruf müsste deshalb als eigener Eintrag
  modelliert werden statt als Löschung.
- Agenten-TUI (Python/Textual) auf Basis von `watch --json`.
