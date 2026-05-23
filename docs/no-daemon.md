# No daemon

## TL;DR

Nothing in weighted-compact runs when you are idle. The only process
that ever starts is the one you started. There is no worker held open
between sessions, no hook watching every tool call, and nothing
writing to disk while you think. The entire runtime footprint collapses
to zero the moment the last query returns.

By contrast, claude-mem maintains an always-on Express worker
(Bun/Node, ~60–100 MB idle RAM estimate per the L5 budget report)
started at SessionStart and never stopped. Six lifecycle hooks fire on
every Claude Code event: `PostToolUse` on every tool call, `PreToolUse`
on every file read, `UserPromptSubmit` on every prompt, and a `Stop`
hook that makes a Claude API call at session end. A typical 50-tool-call
session spawns ~50–100 short-lived Node child processes for those
hooks — processes that exist only to notify a worker that was already
running (per the L5 budget report, §2). weighted-compact spawns zero.

---

## What runs when

| Event | weighted-compact | claude-mem |
|---|---|---|
| System boot | Nothing | Nothing (worker starts at first session) |
| User opens Claude Code session | Nothing | Worker starts on `SessionStart` hook (~60–100 MB RSS, estimate) |
| User runs a tool (Bash, Edit, Read, Write) | Nothing | `PostToolUse` hook fires, spawns Node child process; `PreToolUse` fires on Read calls |
| User types a prompt | Nothing | `UserPromptSubmit` hook fires, spawns Node child process |
| Stop hook fires | Nothing | `Stop` hook fires, spawns Node child process + Claude API call |
| User idle for an hour | Nothing | Worker process stays resident (~60–100 MB) |
| 04:00 local time | `rem-pass` oneshot: ~31 ms, ~40 MB peak, then exits (per `docs/operating-guide.md`) | Worker still resident |
| User runs /compact | Nothing (user pastes output manually, or MCP client calls `compact_session`) | Worker receives hook; SQLite + Chroma grow |

MCP server (`weighted-compact mcp-serve`) is excluded from the table
because it starts only when a client spawns it and exits when the client
disconnects. It is not a resident process.

---

## Footprint, side by side

| Metric | weighted-compact | claude-mem |
|---|---|---|
| Idle RAM (user not actively querying) | **0 MB** — nothing runs | **~80–150 MB estimate** — worker always resident (per L5 budget report, §2) |
| Busy RAM (MCP server, first call warmed) | **~50 MB** (per `docs/operating-guide.md`, §RAM) | ~80–150 MB worker + Chroma embed model if loaded |
| Per-tool-call overhead | **0** — no hooks | **1–2 Node child processes** per tool call (PostToolUse on `*`, PreToolUse on Read) |
| Hook tax per session (50 tool calls) | **0** | ~50–100 short-lived processes (per L5 budget report, §5) |
| Live substrate disk | **~7 MB** (per L5 budget report, §3): `pairs.jsonl` 2.1 MB, `features.npz` 2.8 MB, `importance.npz` 28 KB, three smaller npz files | Unbounded — SQLite + Chroma grow per-session without explicit vacuum (per L5 budget report, §4) |
| Cold-start latency (MCP, first tool call) | **~116 ms** one-time per process lifetime (per L5 budget report, §3) | HTTP round-trip to worker: ~1–5 ms minimum + JSON serialization (estimate) |
| Warm query latency | **0.04 ms** (per L5 budget report, §3, `build_compacted_context` second call) | HTTP to local worker (~1–5 ms, estimate) |
| Runtime dependencies | numpy + stdlib | Bun/Node + SQLite bindings + Chroma (Python/uv) + Claude API |

Disk numbers for weighted-compact are from a 613-pair / 246-session
corpus on the maintainer's machine (AMD Ryzen 9 7940HS / 15.5 GiB,
Arch Linux, 2026-05-23). claude-mem RAM figures are estimates from the
L5 budget report, §2 — no real measurement is available without
running the tool; the Bun/Express baseline with SQLite bindings floors
at 60+ MB RSS.

---

## Why no daemon

### Goodhart

A daemon whose job is to ship context creates a goal: keep context
flowing. If the daemon is always running, always listening, always
writing — something is always happening, even during silence. That
background activity is not neutral. An always-on process has an
incentive to be seen doing something, which is exactly the wrong
incentive for a signal whose value comes from being quiet when nothing
happened. weighted-compact's importance mixture already has this
property at the signal level (the Goodhart argument against
gradient-descending the weights is documented in
`docs/03-quality-driver.md`). The daemon-free architecture extends
that same logic to the process level.

### Trust

A daemon you forgot is running is a daemon you cannot audit. "What is
it doing right now?" is not a question you should have to ask about a
tool that reads your conversation history. The stdio MCP server exits
with its client. The labeler is opt-in and you started it. The nightly
rem-pass timer fires at 04:00, takes 31 ms, and exits (per
`docs/operating-guide.md`, §rem-pass). At any moment, the full set of
weighted-compact processes is the set of things you consciously
launched. That set is auditable; an always-on worker is not.

### Failure-mode shape

"Nothing happened" is observable. Open `journalctl --user -u
weighted-compact-rem-pass` and nothing is there — the pass has not run.
That is a detectable absence. "The daemon crashed silently six hours
ago" is not detectable without explicit health-check tooling, and a
silent crash means six hours of context events went uncaptured without
any signal to the user. weighted-compact's failure mode is the first
kind: a command you forgot to run leaves the substrate stale, and the
substrate's age is visible in the pair timestamps. The crash-and-silent
failure class does not exist because the resident process does not exist.

---

## What this costs you

Choosing no-daemon has real costs. Cold-start for the MCP server's
first tool call is ~116 ms (one-time per process lifetime, per the L5
budget report, §3) — perceptible as a slight hesitation on the first
`compact_session` call of a session, invisible on all subsequent calls.
You must remember to run `weighted-compact bootstrap` after a period of
heavy session activity; otherwise the substrate ages out and new
correction pairs are invisible to the ranker until the next manual
bootstrap. Cross-session context is rebuilt on demand rather than
maintained continuously: there is no background process accumulating
observations as you work, so if you skip the bootstrap step, the
substrate is behind. These are deliberate tradeoffs, not gaps to be
filled later.

---

## What this gains you

The gains are the mirror of those costs. Idle resource use is zero —
nothing holds RAM or CPU between your queries, which matters on a
machine running twelve other services. There is no hook latency tax on
every tool call: a session with 50 Bash and Edit calls incurs zero
overhead from weighted-compact during those calls (compared to ~50–100
Node child-process spawns for a hook-per-event system, per the L5 budget
report, §5). The substrate is plain files — `pairs.jsonl`, `importance.npz`,
and a few smaller npz files — readable with numpy and stdlib, auditable
with a text editor, prunable with a single `find` command. There is no
SQLite vacuum to remember, no Chroma index to evict, no worker to
restart after a crash. And because the only write path is `bootstrap`
(which you run) and `rem-pass` (which runs at 04:00 and exits), the
substrate never changes behind your back.

---

## Related reading

- [`docs/operating-guide.md`](operating-guide.md) — measured numbers
  for disk, RAM, and latency on the maintainer's substrate
- [`docs/rem-decay.md`](rem-decay.md) — the nightly timer, what it
  writes, and how to enable it
- [`docs/mcp-integration.md`](mcp-integration.md) — the stdio MCP
  server: how it starts, what it exposes, when it exits
- [`docs/bench-vs-claude-mem.md`](bench-vs-claude-mem.md) — head-to-head
  on reconstruction fidelity (the quality axis; this doc covers the
  resource axis)
