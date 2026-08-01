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

Setup installs a `sanctuary` shortcut into `~/.local/bin` covering both skills:

```bash
sanctuary status              # table of all sessions
sanctuary status --mesh       # include the other machines
sanctuary status --json       # machine readable
sanctuary watch 2 --json      # NDJSON stream for tooling
sanctuary start [name]        # new session, named in the tab title
sanctuary stop <name>         # end a session

sanctuary send Lino "Please run the tests" --erwartet-quittung
sanctuary auftraege           # what is waiting for me
sanctuary ack <id> 200 "done"
sanctuary hilfe               # all commands
```

The scripts can still be called directly
(`node ~/.claude/skills/operator/operator.mjs status`), but that is only needed for debugging.

## SSH: interactive versus one-shot

A difference that catches everyone once:

```bash
ssh senza                          # interactive login shell - everything as usual
sanctuary status                   # simply works there

ssh senza "sanctuary status"       # NOT found
ssh senza 'bash -lc "sanctuary status"'   # this works
```

Reason: `ssh host "command"` does **not** start a login shell. Ubuntu bails out in the first
lines of `.bashrc` when the shell is not interactive, so `~/.local/bin` never reaches the PATH.
On **Windows** it is the other way round: sshd hands over the PATH from the registry, so the
direct call works - but `bash -lc` lands in **WSL** instead of Git Bash, where there is no node.

**Daily work is unaffected** - grabbing a console with `ssh senza` never notices any of this.
Only scripts issuing commands over SSH are, which is why `--mesh` tries both ways.

## New skills

`~/.claude/skills` holds one symlink **per skill**, not one for the whole directory. That is
what allows skills from several repos, but it has a price: a newly added skill does not show up
on its own after a `git pull`.

The `session-sync-check.sh` SessionStart hook from `claude-config` takes care of that - it
creates missing links at the next session start and reports them (`Neue Skills verlinkt: ...`).
Anything already linked is never touched, so skills from this repo stay untouched. If you
cannot wait, run `setup.sh` again - it is idempotent.

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
