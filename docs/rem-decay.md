# REM-decay: daily wall-clock importance refresh

The seven-signal mixture in `importance.py` is **content-stable**: it
scores misstep probability, density, span coverage, label state, and so
on, but it does not know whether the conversation it is reading happened
today or three months ago. REM-decay adds that axis on top.

A nightly pass — modelled, semantically, on the REM phase that
re-weights yesterday's experience overnight — re-evaluates every pair
against the current wall-clock time and writes a per-pair multiplier
between 0 and 1. The compaction reader composes this multiplier into the
ranking score, so recent sessions outweigh distant ones every morning
without any change to the underlying substrate.

## What it does

For each pair with session timestamp `t`, the factor is

```
factor = exp(-ln(2) * age_days / half_life_days)
```

At the default `half_life_days = 7`:

| Age          | Factor |
|--------------|-------:|
| today        | 1.00   |
| yesterday    | 0.91   |
| 3 days ago   | 0.74   |
| 1 week ago   | 0.50   |
| 2 weeks ago  | 0.25   |
| 1 month ago  | 0.05   |
| 3 months ago | <0.01  |

Session timestamps come from the mtime of the corresponding transcript
at `~/.claude/projects/<dashed_cwd>/<session_id>.jsonl`. Claude Code
appends to the transcript during the session, so mtime tracks
last-activity time. Sessions whose transcript can't be located fall back
to `ref_ts` (today) — they get factor 1.0 and remain visible rather than
silently dropping out.

REM-decay is a **multiplier**, not a replacement for any of the seven
signals. The composition is

```
effective_score = importance[pair_idx] * rem_decay[pair_idx]
```

which preserves the relative ordering of pairs that are equally old,
and gradually demotes pairs as their session ages out.

## What it is *not*

- **Not the recency baseline.** `baseline_recency.npz` is
  position-in-session — a within-session monotonic rank used as a
  cheap-baseline check in the fidelity table. REM-decay is
  cross-session wall-clock aging. They are orthogonal.
- **Not a signal in the mixture.** The mixture weights (`WEIGHTS_BASE`
  in `importance.py`) describe content properties of a pair, not its
  age. Adding a time term to the mixture would conflate two axes and
  break the rerun-on-fresh-clock contract.
- **Not auto-injected.** Like everything else in this repo, REM-decay
  publishes a file that consumers opt in to read. Nothing crawls
  your sessions or pushes context into your prompt automatically.

## Operational details

```
weighted-compact rem-pass                        # default: 7-day half-life
weighted-compact rem-pass --half-life-days 14   # gentler decay
weighted-compact baseline build --ranker rem    # same npz, baseline-shape registration

weighted-compact qa-gate --rem-decay             # consume REM in the gate
```

To run every night automatically:

```
weighted-compact install-units --force          # writes the .timer template
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact-rem-pass.timer
systemctl --user list-timers weighted-compact-rem-pass.timer
```

Fires at 04:00 local with a randomized 15-minute delay. The output
`rem_decay.npz` lives under `$XDG_DATA_HOME/weighted-compact/`, rotates
the previous version to `rem_decay.npz.bak.<UTC-ts>`, and publishes
atomically via tmp-rename.

## Why the metaphor

The user-facing framing is "REM phase, every day." Sleep consolidates
experience by re-weighting which fragments survive into long-term
memory; weighted-compact does the same shape of operation, on the same
cadence, with an explicit numerical decay curve instead of a biological
one. The metaphor is structural, not aesthetic — every morning the
substrate has been re-ranked by what *just happened* against what
*used to matter*.

## Composition with topic-decay

The compaction reader already supports `topic_decay` — a multiplier
that demotes pairs from a different topic than the source pair. REM
composes orthogonally:

```
effective = scores[pid] * (topic_decay ** topic_distance) * rem[pid]
```

Both multipliers are opt-in (`topic_decay=1.0` and `rem_decay_map=None`
disable cleanly). The combined ranker thus reads: *prefer pairs that
are content-important, in the same topic as the source, and recent.*

## Honest limitations

- **Session-level resolution.** Every pair in a session shares the same
  age. Pairs from a sub-conversation early in a long session look
  exactly as recent as pairs from its tail. Per-turn timestamps would
  be more precise, but the Claude transcript schema does not expose
  per-message wall-clock times in a uniformly machine-readable form
  across versions, so the session-mtime proxy ships first.
- **mtime drift.** A session reopened months later for a single turn
  will have its mtime stamped today. This is a feature, not a bug —
  the conversation *was* touched today — but worth knowing if you do a
  forensic comparison.
- **Half-life choice is heuristic.** 7 days fits a workflow where
  context that mattered last week still matters; flatten via
  `--half-life-days 30` if your problem domain wants longer memory.
  No ablation has yet swept the half-life axis on the fidelity gate.
