# chatterdome

<p align="center">
  <img src="docs/flags/gb.svg" height="13" alt=""> <a href="README.md">English</a> ·
  <img src="docs/flags/de.svg" height="13" alt=""> <b>Deutsch</b>
</p>

---

<p align="center">
  <img src="docs/banner.jpg" alt="Chatterdome - zwei KI-Agenten debattieren an Rednerpulten unter einer Glaskuppel, dazwischen ein Moderatorentisch mit Glocke" width="100%">
  <br>
  <sub>Dieses Banner ist KI-generiert (Google Gemini) und trägt sein signiertes C2PA-Manifest
  (<code>trainedAlgorithmicMedia</code>).</sub>
</p>

Eine Zentrale für mehrere gleichzeitig laufende Claude-Code-Instanzen. Sie zeigt, wer gerade
arbeitet, wie voll die Kontextfenster sind und woran jede Sitzung sitzt - und sie erlaubt es
den Instanzen, einander Aufträge zu geben.

Alles bleibt **auf dem eigenen Rechner**. Kein Dienst, kein Port nach außen, kein Cloud-Konto,
keine Telemetrie. Was über Rechnergrenzen geht, geht über SSH im eigenen Tailnet.

## Bestandteile

| Teil | Was es tut |
|---|---|
| `skills/operator` | Übersicht aller laufenden Instanzen: Name, Status, Ordner, Modell, Laufzeit, Kontext. Detailansicht, Live-Ansicht, Beenden, rechnerübergreifende Sicht |
| `skills/claude-bus` | Aufträge zwischen Instanzen, mit Zustand und Quittungen. SQLite, append-only Ereignisse |
| `kern/gedaechtnis.py` | Analyse der Gedächtnisnotizen: Index gegen Bestand, Verweise, Prüfungen, tatsächliche Abrufe aus den Transkripten |
| `kern/busansicht.py` | Auswahl und Kennzahlen für den Bus-Tab: Zeitraum, Status, Adressart, Freitextsuche |
| `kern/transkripte.py` | Wo die Transkripte liegen und wie sie zu lesen sind: Claude Code samt Subagenten, Codex CLI. Eine Quelle für Statistik und Suche |
| `kern/suche.py` | Volltextindex über alle Transkripte, SQLite mit FTS5, inkrementell über die Dateizeit |
| `kern/statistik.py` | Auswertung der Transkripte und des Bus: Flotte, Verbrauch nach Art, Sitzungsdauer, Frühwarnung |
| `kern/` | UI-freier Python-Kern - eine Quelle für beide Oberflächen |
| `tui/` | Textual-Oberfläche fürs Terminal |
| `web/` | FastHTML-Oberfläche, gedacht für den Dauerläufer im Tailnet |

## Einrichten

```bash
git clone https://github.com/michaelblaess/chatterdome.git
cd chatterdome
./setup.sh                                        # Linux, macOS
powershell -ExecutionPolicy Bypass -File setup.ps1  # Windows
```

Das Skript hängt `~/.claude/skills/operator` und `~/.claude/skills/claude-bus` auf dieses
Repo. Für Claude Code ändert sich dadurch nichts - die Skills liegen weiterhin dort, wo sie
erwartet werden. Ein vorhandenes echtes Verzeichnis wird **nie gelöscht**, sondern als
`.vor-chatterdome` beiseitegelegt.

### Umzug von claude-sanctuary

Bis zum 29.09.2026 hieß das Projekt **claude-sanctuary**. Ein Rechner mit dem alten Klon zieht
in zwei Schritten um. Erst alles schließen, was im Ordner läuft (Claude-Sitzungen, die alte
Oberfläche, Terminals), dann im alten Ordner:

```bash
git pull
bash scripts/umzug-chatterdome.sh                                   # Linux, macOS
powershell -ExecutionPolicy Bypass -File scripts\umzug-chatterdome.ps1  # Windows
```

Das Skript benennt den Ordner in `chatterdome` um, stellt das Git-Remote um, baut die `.venv`
neu und ruft Setup und Bootstrap auf. Einstellungen, Suchindex und Diskussionsarchiv werden
beim ersten Start von `~/.claude-sanctuary` nach `~/.chatterdome` kopiert. Der alte Befehl
`sanctuary` bleibt als Alias: andere Rechner rufen ihn über ssh auf, und deren Stand kann
älter sein als dieser.

## Benutzen

Das Setup legt den Kurzbefehl `chatterdome` in `~/.local/bin` an - beide Skills hängen darunter:

```bash
chatterdome status              # Tabelle aller Instanzen
chatterdome status --mesh       # zusätzlich die anderen Rechner
chatterdome status --json       # maschinenlesbar
chatterdome watch 2 --json      # NDJSON-Strom für Werkzeuge
chatterdome start [Name]        # neue Instanz mit Namen im Tab-Titel
chatterdome stop <Name>         # Instanz beenden

chatterdome send Klara "Bitte Tests laufen lassen" --erwartet-quittung
chatterdome auftraege           # was liegt für mich an
chatterdome ack <id> 200 "erledigt"
chatterdome hilfe               # alle Befehle
```

Die Skripte lassen sich weiterhin direkt aufrufen
(`node ~/.claude/skills/operator/operator.mjs status`), das braucht man aber nur zum Debuggen.

## Agentennamen

Jede Sitzung bekommt einen Namen aus einem Pool, damit Du sie ansprechen kannst statt über
eine Prozessnummer. `skills/operator/namenspool.json` hält mehrere Motive und merkt sich,
welches aktiv ist. Mitgeliefert werden zwei gemeinfreie Motive, `heilige` (katholische
Heilige) und `schauspieler`. Ein eigenes Motiv ist ein zusätzlicher Eintrag unter `pools`.

Motive aus Figuren eines geschützten Werks werden bewusst **nicht** mitgeliefert. Eine blosse
Namensliste sieht harmlos aus, aber sobald `motiv` das Werk benennt, ist der Bezug
hergestellt, und die Rechteinhaber handeln durchaus: Zu Comicmotiv bestehen EU-Marken in Klasse
9, also für Software, und 2016 wurden zwei GitHub-Repositories vollständig abgeschaltet.

Der Spass an einem Motiv bleibt trotzdem, nur eben lokal. Anregungen, deren Rechtslage Du vor
einer Veröffentlichung selbst prüfen solltest:

- **Comicmotiv** - Snorre, Charlene, Lino, Luzie, Marga, Franko, Schmid, Piet
- **Beispielteam** - Bauernfeind, Tamino, Amalia, Olsen, Kerstin, Engelhardt
- Alles, was niemandem gehört: Sternbilder, Vögel, Bäume, Flüsse, Minerale

## Der Message-Bus-Tab

Taste `u` in der Oberfläche. Links eine Tabelle aller Nachrichten im Bus dieses
Rechners, rechts entweder die Übersicht oder die gewählte Nachricht samt allen
Quittungen. Gefiltert wird über drei Auswahlfelder - Zeitraum, Status und
Adressart - dazu ein Suchfeld über Agenten, Thema, Inhalt und Quittungsnotizen.
Die Kopfzeile sortiert per Klick, `Esc` führt aus der Detailansicht zurück.

Die Spalte **Adresse** ist die interessanteste, und sie hat einen Anlass. Am
07.08.2026 legte die Oberfläche einen Auftrag an eine Instanz namens Marga ab.
Marga holte ihn nie ab, ihre Sitzung endete, der Name ging zurück in den Pool -
und vier Tage später bekam eine völlig andere Sitzung denselben Namen und
arbeitete den Auftrag ab. Ein Name ist eine Pacht, keine Person.

Seitdem unterscheidet der Bus zwei Adressarten:

- **Person** - der Auftrag ist an die Sitzung gebunden, die den Namen beim
  Absenden trug. Ein späterer Träger bekommt ihn nicht.
- **Rolle** - der Auftrag meint den Namen, wer immer ihn trägt. Ausdrücklich zu
  wählen (`--rolle`), und nur zusammen mit dem Verfall zu verantworten.

Die Übersicht rechts nennt deshalb nicht nur offen, erledigt und gescheitert,
sondern auch **wie viele offene Nachrichten überhaupt noch vererbbar sind**.
Genau diese Zahl hätte den Vorfall vorhergesagt. Dazu die Verfallsfrist
(Vorgabe 24 Stunden, über `chatterdome config` zu ändern) und der älteste noch
offene Auftrag mit seinem Alter.

Auch dieser Tab ist rein lesend. Gesendet wird weiterhin im Agenten-Tab.

## Der Statistik-Tab

Taste `k`. Ein Dashboard aus sechs Sektionen, gezeichnet mit plotext im
Terminal. Die Zahlen kommen aus den Transkripten unter `~/.claude/projects`
und aus dem Bus. Ein voller Durchgang durch 369 MB dauert gemessen 2,3 s bei
warmem Dateicache, beim ersten Lauf nach dem Start rund 7,6 s. Beides ist
schnell genug, dass der Tab bei jedem Öffnen frisch rechnet, statt einen
Zwischenspeicher zu pflegen, der veralten kann.

- **Gleichzeitigkeit** - wie viele Sitzungen an einem Tag höchstens parallel
  aktiv waren, daneben wie viele es insgesamt waren. Rückwirkend aus den
  Sitzungsintervallen rekonstruiert, es musste dafür nie etwas mitgeschrieben
  werden.
- **Verarbeitet je Tag** - Token nach Cache-Aufbau, frisch Gelesenem und
  Ausgabe, gestapelt. Die Cache-Lesung fehlt hier mit Absicht: sie macht
  gemessen **96 bis 98 Prozent** aus und würde das Diagramm zu einem
  einfarbigen Balken machen. Als eine Zahl steht sie in der Kopfzeile, dort
  sagt sie mehr.
- **Was Länge kostet** - Median-Verbrauch je Korb der Sitzungsdauer. Median
  und nicht Mittelwert, weil eine einzelne sehr lange Sitzung ihren Korb
  sonst allein bestimmt.
- **Verarbeitet je Ordner** - als Liste mit Textbalken, eine Zeile je Ordner.
  Gezählt wird dasselbe Mass wie oben, also ohne die Cache-Lesung: mit ihr
  stünden dort fast zwei Milliarden Token für einen einzigen Ordner, und zwei
  Diagramme nebeneinander meinten zwei verschiedene Dinge.
- **Message-Bus** - Aufträge je Tag nach Ausgang, dazu die Liegezeit der noch
  offenen.
- **Frühwarnung** - vier Zahlen mit Ampel, darunter die, die den Vorfall vom
  07.08.2026 vorhergesagt hätte: wie viele offene Nachrichten ein späterer
  Träger desselben Namens noch erben kann.

**Ausgewertet wird je Sitzung, nie je Agentenname.** Ein Name ist eine Pacht -
gemessen trugen vier Namen im Auswertungszeitraum bereits je zwei
verschiedene Sitzungen. Eine Rangliste je Name würde sie zusammenwerfen, und
das ist derselbe Denkfehler, der den Busauftrag an die falsche Marga
geliefert hat.

Eine Einschränkung steht als Fussnote im Tab, weil sie die Zahlen prägt:
Gemessen wird die **aktive** Dauer, also erste bis letzte Anfrage - nicht, wie
lange ein Fenster offen stand.

**Subagenten zählen seit dem 24.08.2026 mit.** Vorher stand hier, ihr Anteil
sei nicht messbar - `isSidechain` steht in den Haupttranskripten bei 35.498 von
35.498 Anfragen auf false. Das stimmt, führt aber in die Irre: die Subagenten
liegen eine Ebene tiefer, unter `<projekt>/<sitzung>/subagents/*.jsonl`, und
dort steht das Feld auf true. Der Glob traf diese Ebene nicht. Gemessen am
24.08.2026 waren es 255 Anfragen gegenüber 14.608 im Hauptbestand - 1,7 Prozent
der Anfragen und 1,3 Prozent der Ausgabe-Token. Sie zählen zur Elternsitzung,
denn ihre `sessionId` ist deren Id. Die Kopfzeile weist sie getrennt aus, sobald
welche im Zeitraum liegen. Der Agententyp und eine lesbare Aufgabenbeschreibung
stehen in einer `*.meta.json` neben der Datei.

**Ein Antwortzug steht auf mehreren Zeilen**, und jede wiederholt denselben
kumulativen Verbrauch. Bis zum 24.08.2026 summierte die Auswertung pro Zeile
und zählte ihn damit mehrfach - gemessen Faktor 2,25, also 30,45 statt 13,51
Millionen Ausgabe-Token. Seitdem zählt sie je `requestId` nur den letzten Stand.
**Alle Zahlen des Statistik-Tabs sind dadurch kleiner geworden und mit früheren
Ständen nicht vergleichbar.**

## Der Suchreiter

Taste `f`. Volltextsuche über alle Transkripte - Claude Code und Codex CLI -
mit SQLite und FTS5. Der Index liegt unter `~/.chatterdome/suche.db` und
ist jederzeit wegwerfbar: er enthält nichts, was nicht auch in den
Transkripten steht.

Gemessen am 24.08.2026 auf RAINBOW: 98 Transkripte mit 7.600 Textstellen,
Erstaufbau **1,8 s**, Index 22,9 MB. Jeder weitere Lauf vergleicht nur
Änderungszeit und Grösse je Datei und ist nach **0,01 s** durch. Eine Abfrage
dauert 1 bis 2 ms, deshalb sucht der Reiter schon beim Tippen und verlangt
kein Enter.

Zwei Dinge, die der Index bewusst nicht tut:

- **Werkzeugaufrufe und deren Ausgaben bleiben draussen.** Sie machen den
  Grossteil der Zeichen aus, und was darin steht - Dateiinhalte,
  Befehlsausgaben - findet man besser dort, wo es herkommt. Gesucht wird in
  dem, was gesagt wurde.
- **Sortiert wird nach Relevanz, nicht nach Zeit.** Wer sucht, will den besten
  Treffer sehen. Eine nach Datum sortierte Trefferliste wäre eine andere Frage
  als die gestellte.

Umlaute werden normalisiert, `koln` findet also `Köln`. Das scharfe s bleibt
davon unberührt: `grusse` findet `Grüße` nicht. Enter auf einem Treffer öffnet
das Transkript im zuständigen Programm.

## Der Gedächtnis-Tab

Taste `m` in der Oberfläche. Der Tab liest die Notizen unter `~/.claude/memory`
und zeigt, was Claudes Gedächtnis wirklich kostet. Der Pfad lässt sich in den
Einstellungen umstellen, wer je Projekt ein eigenes Verzeichnis führt.

Ganz oben steht die dringlichste Zahl: **wie voll der Index ist.** `MEMORY.md`
hat ein hartes Limit von 200 Zeilen oder 25.000 Zeichen, je nachdem was zuerst
greift. Was darüber steht, wird beim Sitzungsstart **still abgeschnitten**, und
zwar das zuletzt Angelegte. Es gibt keine Einstellung, die das hebt. Der Tab
zeigt beide Grenzen als Balken und warnt ab 80 Prozent.

Das Gedächtnis besteht aus zwei Teilen mit sehr verschiedenen Kosten:

- **`MEMORY.md`** ist der Index und liegt bei **jedem** Sitzungsstart im
  Kontext. Jede Zeile darin kostet in jeder künftigen Sitzung.
- **Die Einzelnotizen** kosten nur beim Abruf etwas, und der ist selten.

Genau diese beiden Zahlen stellt die Übersicht nebeneinander, samt der
Hochrechnung des Index über die gemessenen Sitzungen. Daraus folgt die
praktische Lehre: eine Notiz zu löschen spart am Kontext fast nichts, eine
Zeile weniger im Index dagegen schon. Bündeln schlägt Löschen.

Dazu kommen die Prüfungen, die nachweisbare Mängel finden statt Meinungen
abzugeben: Notizen ohne Eintrag im Index, Index-Einträge ohne Datei, Verweise
ins Leere, fehlende Typangaben.

Wie oft eine Notiz **tatsächlich** abgerufen wurde, liest der Tab aus den
Transkripten. Gezählt wird ausschliesslich der Abrufhinweis, den Claude Code
vor einen geladenen Eintrag setzt. Eine blosse Suche nach dem Dateinamen wäre
wertlos, denn der steht auch in jeder Ausgabe von `git diff`. Die Zahl ist eine
Untergrenze: gezählt wird nur, was in den noch vorhandenen Transkripten steht.

Der Tab ist rein lesend. Er ändert und löscht nichts.

## Zwei Klassen von Agenten

Die wichtigste Entwurfsentscheidung, weil sie erklärt, was dieses Werkzeug **nicht** kann:

Eine laufende **interaktive** Claude-Sitzung hatte lange keinen externen Eingang. Ein neuer Zug
entstand ausschließlich durch eine Eingabe des Benutzers - eine Architekturgrenze von Claude
Code, an der kein Transport etwas änderte, weder ein Terminal noch HTTP.

**Auf macOS und Linux gilt das seit Claude Code 2.1.224 nicht mehr.** Jede Sitzung bindet dort
einen Unix-Socket, in den von außen geschrieben werden darf, und der Bus nutzt ihn - siehe
[Sofortzustellung](#sofortzustellung). Auf **nativem Windows** bleibt die Grenze bestehen.

Die Trennung in zwei Klassen bleibt trotzdem sinnvoll:

- **Interaktive Sitzungen** sind Michaels Arbeitsfenster. Sie werden **beobachtet**, nicht
  gesteuert. Auf macOS und Linux erreicht ein Auftrag sie sofort, auf Windows liegt er bis zum
  nächsten Stop-Hook.
- **Auftrags-Agenten** werden bei Bedarf gestartet (`claude -p`, headless), erledigen eine
  Sache und sind wieder weg. Sie sind fernsteuerbar, das ist ihr Zweck.

Details in [`docs/architektur-http.md`](docs/architektur-http.md).

## Sofortzustellung

Ein Auftrag landet direkt in der wartenden Sitzung, statt bis zu ihrer nächsten Antwort liegen
zu bleiben. Gesteuert über die Einstellung `zustellung`:

| Wert | Verhalten |
|---|---|
| `auto` | Vorgabe. Sofort über den Inbox-Socket, wo es den gibt (macOS, Linux), sonst Stop-Hook. |
| `socket` | Nur sofort. Klappt es nicht, gibt es eine Warnung - der Auftrag liegt trotzdem bereit. |
| `stop-hook` | Immer der bisherige Weg. Auf Windows ohnehin der einzige. |

```bash
chatterdome bus config zustellung socket
```

**Voraussetzung:** In `~/.claude/settings.json` muss `"crossSessionInbound": "accept"` stehen.
Ohne das hält eine Sitzung im Bypass-Modus jede Einspeisung von außen zur Freigabe zurück und
zeigt stattdessen einen Dialog. Auf Windows ist die Einstellung wirkungslos und schadet nicht.

Über Rechnergrenzen bleibt der Weg unverändert ssh im Tailnet. Nur der letzte Meter auf dem
Zielrechner wird sofort - dort kennt der Bus den Socket, der Absender kann ihn nicht kennen.

### Derselbe Name auf zwei Rechnern

Der Name ist eine Pacht **pro Rechner**. `Petra` kann gleichzeitig auf RAINBOW und SENZA
laufen - beide Sitzungen sind echt und haben eigene IDs. Eindeutig sein muss nicht der Name,
sondern die Adresse:

```bash
chatterdome send Petra@SENZA "..."
```

Ist der Name im Mesh eindeutig, bleibt `send Petra` wie bisher. Ist er doppelt, bricht der Bus
ab und nennt beide Fassungen, statt still eine zu wählen. Die Tabelle zeigt solche Namen als
`Petra@RAINBOW`, und `chatterdome bus doctor` listet sie auf.

### Verwaiste Sitzungen

Eine Sitzung, die läuft, aber seit 24 Stunden nichts mehr getan hat, bekommt in der
Aktiv-Spalte ein rotes `⚠`. Die Ampel bleibt grün - die Sitzung **kann** Aufträge annehmen,
sie tut nur nichts. Markiert wird dort, wo auch der Beleg steht.

### Zwei Fallen

⚠ **Die erste Sitzung nach einem Claude-Code-Update bekommt das Feature nicht.** Die
Feature-Flags sind dann noch nicht abgerufen, die Sitzung bindet keinen Socket. Ein Neustart
der Sitzung behebt es. Nach einem Update also einmal neu starten, bevor man die
Sofortzustellung für kaputt hält.

⚠ **`/list-agents` taugt nicht als Prüfung**, ob das Feature läuft - obwohl Anthropics Doku
das vorschlägt. Der Befehl wird auch ohne das Feature erkannt und meldet dann nur "No subagents
or other Claude sessions", denn er listet auch Subagenten. Belastbar sind die Zeile
`Peer address` in `/status` und von außen `ss -xlp | grep cc-socks`. Ein erneuter Test ist für
Ende August 2026 vorgesehen.

## SSH: interaktiv oder mit Befehl

Ein Unterschied, der überrascht, wenn man ihn zum ersten Mal trifft:

```bash
ssh senza                          # interaktive Login-Shell - alles wie gewohnt
chatterdome status                   # funktioniert dort einfach

ssh senza "chatterdome status"       # NICHT gefunden
ssh senza 'bash -lc "chatterdome status"'   # so schon
```

Der Grund: `ssh rechner "befehl"` startet **keine** Login-Shell. Ubuntu bricht in den ersten
Zeilen der `.bashrc` ab, wenn die Shell nicht interaktiv ist - `~/.local/bin` landet dann nie
im PATH. Auf **Windows** ist es genau umgekehrt: der sshd übergibt den PATH aus der Registry,
also funktioniert der direkte Aufruf, dafür führt `bash -lc` dort in die **WSL** statt in die
Git Bash, wo es kein node gibt.

**Für die tägliche Arbeit ändert sich nichts** - wer sich mit `ssh senza` eine Konsole holt,
merkt davon gar nichts. Betroffen sind nur Skripte, die Befehle über SSH absetzen. `--mesh`
probiert deshalb beide Wege.

## Neue Skills

`~/.claude/skills` enthält einen Symlink **je Skill**, nicht einen für das ganze Verzeichnis.
Das erlaubt Skills aus mehreren Repos, hat aber einen Preis: ein neu hinzugekommener Skill
erscheint nicht von allein nach einem `git pull`.

Darum kümmert sich der SessionStart-Hook `session-sync-check.sh` aus `claude-config` - er legt
fehlende Verweise beim nächsten Sitzungsstart an und meldet das (`Neue Skills verlinkt: ...`).
Was bereits verlinkt ist, wird nie angefasst, Skills aus diesem Repo bleiben also unberührt.
Wer nicht warten will, ruft `setup.sh` erneut auf - es ist idempotent.

**Auf Windows-Zielen setzt das Setup außerdem einen PATH-Eintrag.** Ohne `~\.local\bin` im
**Benutzer**-PATH findet zwar die eigene Shell den Kurzbefehl, aber `status --mesh` scheitert -
der Windows-sshd reicht genau diesen Benutzer-PATH an eingehende Verbindungen weiter. Der
Eintrag wird nur angehängt, nie neu gesetzt.

## Woher der Code kommt

Operator und Message-Bus sind aus dem privaten Repo `claude-config` hierher gezogen, Stand `3a531c4`
vom 01.08.2026. Die Entstehungsgeschichte steht dort in der Historie - hier beginnt sie neu,
weil die alten Commits fast immer mehrere Skills gleichzeitig betrafen.

## Lizenz

Apache-2.0, siehe [LICENSE](LICENSE). Die Weboberfläche bringt xterm.js und Tabler mit (beide
MIT), siehe [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
