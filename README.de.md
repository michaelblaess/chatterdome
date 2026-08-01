# claude-sanctuary

<p align="center">
  <img src="docs/flags/gb.svg" height="13" alt=""> <a href="README.md">English</a> ·
  <img src="docs/flags/de.svg" height="13" alt=""> <b>Deutsch</b>
</p>

---

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
| `kern/` | UI-freier Python-Kern - eine Quelle für beide Oberflächen |
| `tui/` | Textual-Oberfläche fürs Terminal |
| `web/` | FastHTML-Oberfläche, gedacht für den Dauerläufer im Tailnet |

## Einrichten

```bash
git clone https://github.com/michaelblaess/claude-sanctuary.git
cd claude-sanctuary
./setup.sh                                        # Linux, macOS
powershell -ExecutionPolicy Bypass -File setup.ps1  # Windows
```

Das Skript hängt `~/.claude/skills/operator` und `~/.claude/skills/claude-bus` auf dieses
Repo. Für Claude Code ändert sich dadurch nichts - die Skills liegen weiterhin dort, wo sie
erwartet werden. Ein vorhandenes echtes Verzeichnis wird **nie gelöscht**, sondern als
`.vor-sanctuary` beiseitegelegt.

## Benutzen

```bash
OP=~/.claude/skills/operator
BUS=~/.claude/skills/claude-bus

node $OP/operator.mjs status          # Tabelle aller Instanzen
node $OP/operator.mjs status --mesh   # zusätzlich die anderen Rechner
node $OP/operator.mjs watch 2 --json  # NDJSON-Strom für Werkzeuge
node $OP/starte.mjs                   # neue Instanz mit Namen aus dem Pool

node $BUS/bus.mjs send Lino "Bitte Tests laufen lassen" --erwartet-quittung
node $BUS/bus.mjs auftraege           # was liegt für mich an
node $BUS/bus.mjs ack <id> 200 "erledigt"
```

## Zwei Klassen von Agenten

Die wichtigste Entwurfsentscheidung, weil sie erklärt, was dieses Werkzeug **nicht** kann:

Eine laufende **interaktive** Claude-Sitzung hat keinen externen Eingang. Ein neuer Zug
entsteht ausschließlich durch eine Eingabe des Benutzers - das ist eine Architekturgrenze von
Claude Code und ändert sich durch keinen Transport, weder über ein Terminal noch über HTTP.

Deshalb trennt dieses Projekt zwei Klassen:

- **Interaktive Sitzungen** sind Michaels Arbeitsfenster. Sie werden **beobachtet**, nicht
  gesteuert. Aufträge können für sie hinterlegt werden, abgeholt werden sie beim nächsten
  Mal - Zustellung ist eine Bringschuld des Empfängers.
- **Auftrags-Agenten** werden bei Bedarf gestartet (`claude -p`, headless), erledigen eine
  Sache und sind wieder weg. Sie sind fernsteuerbar, das ist ihr Zweck.

Details in [`docs/architektur-http.md`](docs/architektur-http.md).

## Woher der Code kommt

Operator und Bus sind aus dem privaten Repo `claude-config` hierher gezogen, Stand `3a531c4`
vom 01.08.2026. Die Entstehungsgeschichte steht dort in der Historie - hier beginnt sie neu,
weil die alten Commits fast immer mehrere Skills gleichzeitig betrafen.

## Lizenz

Apache-2.0, siehe [LICENSE](LICENSE).

## SSH: interaktiv oder mit Befehl

Ein Unterschied, der überrascht, wenn man ihn zum ersten Mal trifft:

```bash
ssh senza                          # interaktive Login-Shell - alles wie gewohnt
sanctuary status                   # funktioniert dort einfach

ssh senza "sanctuary status"       # NICHT gefunden
ssh senza 'bash -lc "sanctuary status"'   # so schon
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
