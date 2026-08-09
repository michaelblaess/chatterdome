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
| `kern/gedaechtnis.py` | Memory analysis: index versus collection, links, checks, actual recalls from the transcripts |
| `kern/busansicht.py` | Selection and figures for the bus tab: period, state, address kind, free-text search |
| `kern/statistik.py` | Analysis of transcripts and bus: fleet, spend by kind, session duration, early warning |
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

## The message bus tab

Press `u` in the interface. On the left a table of every message in this
machine's bus, on the right either the overview or the selected message with all
its receipts. Three dropdowns filter by period, state and address kind, plus a
search field covering agents, topic, body and receipt notes. Clicking a header
sorts, `Esc` leaves the detail view.

The **address** column is the interesting one, and it has a reason. On
07.08.2026 the interface posted a task to an instance called Marga. That Marga
never picked it up, its session ended, the name went back into the pool - and
four days later a completely different session received the same name and worked
the task. A name is a lease, not a person.

Since then the bus distinguishes two kinds of address:

- **Person** - the task is bound to the session that held the name when it was
  sent. A later holder does not receive it.
- **Role** - the task means the name, whoever holds it. Chosen explicitly
  (`--rolle`), and defensible only together with expiry.

So the overview does not just count open, done and failed, it also states **how
many open messages can still be inherited at all**. That number would have
predicted the incident. Next to it the expiry deadline (24 hours by default,
changed via `sanctuary config`) and the oldest task still open, with its age.

This tab is read-only as well. Sending still happens in the agents tab.

## The statistics tab

Press `k`. A dashboard of six sections, drawn with plotext in the terminal.
The numbers come from the transcripts under `~/.claude/projects` and from the
bus. A full pass over 369 MB takes a measured 2.3 s with a warm file cache,
about 7.6 s on the first run after startup. Both are fast enough for the tab to
recompute on every open rather than keep a cache that can go stale.

- **Concurrency** - how many sessions were active at the same time on a given
  day, at most, next to how many there were in total. Reconstructed
  retroactively from the session intervals; nothing ever had to be recorded.
- **Processed per day** - tokens by cache write, fresh reads and output,
  stacked. Cache reads are deliberately absent: they account for a measured
  **96 to 98 percent** and would turn the chart into a single-colour bar. As
  one number they sit in the header, where they say more.
- **What length costs** - median spend per bucket of session duration. Median
  rather than mean, because a single very long session would otherwise define
  its bucket on its own.
- **Processed per folder** - a list with text bars, one row per folder. Same
  measure as above, so cache reads excluded: with them one folder alone would
  read almost two billion tokens, and two adjacent charts would mean two
  different things.
- **Message bus** - tasks per day by outcome, plus how long the open ones have
  been waiting.
- **Early warning** - four numbers with a traffic light, among them the one
  that would have predicted the incident of 07.08.2026: how many open messages
  a later holder of the same name could still inherit.

**Everything is aggregated per session, never per agent name.** A name is a
lease - in the measured period four names had already served two different
sessions each. A ranking by name would merge them, and that is the same
mistake that delivered the bus task to the wrong Marga.

Two limitations appear as a footnote in the tab, because they shape the
figures: what is measured is the **active** span, first to last request - not
how long a window stayed open. And **subagents do not appear in the
transcripts** (`isSidechain` is false for 35,498 of 35,498 requests), so their
share is not measurable and is not estimated.

## The memory tab

Press `m` in the interface. The tab reads the notes under `~/.claude/memory`
and shows what Claude's memory actually costs. The path can be changed in the
settings for anyone keeping a separate directory per project.

The most urgent figure sits at the top: **how full the index is.** `MEMORY.md`
has a hard limit of 200 lines or 25,000 characters, whichever bites first.
Anything beyond that is **silently truncated** at session start, and it is the
most recent entries that go. No setting lifts it. The tab shows both limits as
bars and warns from 80 percent.

Memory comes in two parts with very different costs:

- **`MEMORY.md`** is the index and sits in context at **every** session start.
  Every line in it costs in every future session.
- **The individual notes** only cost something when recalled, and that is rare.

The overview puts those two numbers side by side, along with the index
projected across the sessions measured. The practical lesson follows from
that: deleting a note saves almost nothing, while one line less in the index
does. Merging beats deleting.

The checks look for demonstrable defects rather than offering opinions: notes
missing from the index, index entries without a file, links pointing nowhere,
missing type fields.

How often a note was **actually** recalled is read from the transcripts. Only
the recall marker Claude Code places before a loaded entry is counted. Simply
searching for the file name would be worthless, since it also appears in every
`git diff` output. The figure is a lower bound: only what the surviving
transcripts contain is counted.

The tab is strictly read-only. It changes and deletes nothing.

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

**On Windows targets setup also adds a PATH entry.** Without `~\.local\bin` in the **user**
PATH your own shell finds the shortcut, but `status --mesh` fails - the Windows sshd hands
exactly that user PATH to incoming connections. The entry is only appended, never replaced.

## Two classes of agents

The central design decision, because it explains what this tool deliberately **cannot** do:

For a long time a running **interactive** Claude session had no external inbox. A new turn only
ever started from user input - an architectural boundary of Claude Code that no transport could
work around, neither a terminal trick nor HTTP.

**On macOS and Linux that stopped being true with Claude Code 2.1.224.** Every session binds a
Unix socket there that accepts writes from outside, and the bus uses it - see
[Instant delivery](#instant-delivery). On **native Windows** the boundary still stands.

The split into two classes remains useful regardless:

- **Interactive sessions** are your working windows. They are **observed**, not driven. On
  macOS and Linux a task reaches them right away, on Windows it waits for the next stop hook.
- **Task agents** are started on demand (`claude -p`, headless), do one job and are gone.
  Those are remote controllable, that is their whole point.

Details in [`docs/architektur-http.md`](docs/architektur-http.md) (German).

## Instant delivery

A task lands in the waiting session directly instead of sitting there until its next reply.
Controlled by the `zustellung` setting:

| Value | Behaviour |
|---|---|
| `auto` | Default. Straight through the inbox socket where one exists (macOS, Linux), stop hook otherwise. |
| `socket` | Instant only. If it fails you get a warning - the task is still queued. |
| `stop-hook` | Always the previous route. The only one available on Windows anyway. |

```bash
sanctuary bus config zustellung socket
```

Across machines the route is unchanged: ssh inside the tailnet. Only the last metre on the
target machine becomes instant, because that is where the socket lives - the sender cannot
know it.

### Two traps

⚠ **The first session after a Claude Code update does not get the feature.** Its feature flags
have not been fetched yet, so the session binds no socket. Restarting that session fixes it.
After an update, restart once before concluding instant delivery is broken.

⚠ **`/list-agents` is not a usable check** for whether the feature is on, even though
Anthropic's documentation suggests it. The command is recognised without the feature too and
then merely reports "No subagents or other Claude sessions", because it also lists subagents.
What holds up is the `Peer address` row in `/status`, and `ss -xlp | grep cc-socks` from
outside. A re-test is planned for late August 2026.

## Where the code came from

Operator and message bus moved here from the private `claude-config` repo, state `3a531c4` of
2026-08-01. Their history stays there - it starts fresh here, because the old commits almost
always touched several skills at once.

## License

Apache-2.0, see [LICENSE](LICENSE).
