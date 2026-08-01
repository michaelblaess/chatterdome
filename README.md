# claude-sanctuary

<p align="center">
  <img src="docs/flags/gb.svg" height="13" alt=""> <b>English</b> ·
  <img src="docs/flags/de.svg" height="13" alt=""> <a href="README.de.md">Deutsch</a>
</p>

---

A control room for several Claude Code sessions running side by side. It shows who is
working, how full each context window is and what every session is busy with - and it lets
those sessions hand each other tasks.

Everything stays **on your own machine**. No service, no open port, no cloud account, no
telemetry. What crosses machine boundaries goes over SSH inside your own Tailnet.

## Parts

| Part | What it does |
|---|---|
| `skills/operator` | Overview of running sessions: name, status, folder, model, uptime, context. Detail view, live view, stop, cross-machine view |
| `skills/claude-bus` | Tasks between sessions, with state and receipts. SQLite, append-only events |
| `kern/` | UI-free Python core - one source for both frontends |
| `tui/` | Textual interface for the terminal |
| `web/` | FastHTML interface, meant for the always-on machine in the Tailnet |

## Setup

```bash
git clone https://github.com/michaelblaess/claude-sanctuary.git
cd claude-sanctuary
./setup.sh                                          # Linux, macOS
powershell -ExecutionPolicy Bypass -File setup.ps1  # Windows
```

The script points `~/.claude/skills/operator` and `~/.claude/skills/claude-bus` at this repo.
Nothing changes for Claude Code - the skills stay exactly where it expects them. An existing
real directory is **never deleted**, it is moved aside as `.vor-sanctuary`.

## Usage

```bash
OP=~/.claude/skills/operator
BUS=~/.claude/skills/claude-bus

node $OP/operator.mjs status          # table of all sessions
node $OP/operator.mjs status --mesh   # include the other machines
node $OP/operator.mjs watch 2 --json  # NDJSON stream for tooling
node $OP/starte.mjs                   # new session, named from the pool

node $BUS/bus.mjs send Lino "Please run the tests" --erwartet-quittung
node $BUS/bus.mjs auftraege           # what is waiting for me
node $BUS/bus.mjs ack <id> 200 "done"
```

## Two classes of agents

The central design decision, because it explains what this tool deliberately **cannot** do:

A running **interactive** Claude session has no external inbox. A new turn only ever starts
from user input - that is an architectural boundary of Claude Code, and no transport changes
it, neither a terminal trick nor HTTP.

So this project separates two classes:

- **Interactive sessions** are your working windows. They are **observed**, not driven. Tasks
  can be left for them and are picked up next time the session is active - delivery is the
  receiver's duty, not the sender's.
- **Task agents** are started on demand (`claude -p`, headless), do one job and are gone.
  Those are remote controllable, that is their whole point.

Details in [`docs/architektur-http.md`](docs/architektur-http.md) (German).

## Where the code came from

Operator and bus moved here from the private `claude-config` repo, state `3a531c4` of
2026-08-01. Their history stays there - it starts fresh here, because the old commits almost
always touched several skills at once.

## License

Apache-2.0, see [LICENSE](LICENSE).
