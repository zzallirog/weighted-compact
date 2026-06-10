# Recap — a faithful, lossy navigation map

Recap is the third shipped consumer of the session source. It does not
compete with compaction; it answers a different question.

- **Compaction** asks: *which turns do I keep so the rest can still answer
  questions about what was hidden?* That is a fidelity problem, and the
  [headline table](../README.md#the-methodology-is-inspectable) is honest
  that the six-signal mixture has no measured edge there over cheap
  baselines.
- **Recap** asks: *what happened across this session, task by task?* That
  is a navigation problem. Recap answers it as a deliberately **lossy**
  map — and unlike compaction, the quality claim it makes is *positive and
  provable*.

```bash
weighted-compact recap SESSION.jsonl          # render the map
weighted-compact recap --audit SESSION.jsonl  # render + re-check invariants
weighted-compact recap --all                  # audit every session, aggregate
```

## What it produces

One section per **task** (a task boundary is a real user prompt — not a
tool return, slash-command echo, harness interrupt, or system caveat).
For each task:

- the **goal** — the user's prompt, trimmed (image-only prompts render as
  `(screenshot)`, never a blank);
- the **files touched** — sorted by churn, each with a `+adds/−rems`
  diffstat and a five-block bar, computed from the `Edit`/`Write` deltas;
  `/tmp` paths are grouped as ephemeral;
- the **commands** — deduplicated `Bash` first-lines with repeat counts;
- the **outcome** — a verbatim excerpt of the assistant's final message in
  the segment (quoted, never summarized);
- a **footprint** — the per-tool counts for the task.

```text
## 8. on sharp new loads it needs 5 ticks to settle, then it's near-instant…
`11×Bash, 10×Edit, 7×Read, 5×TaskCreate, 2×Write`   net `+557/−8`

  🟩🟩🟩🟩🟩 `+198 −0  ` ~/coolstep/coolstep/core/spike_detector.py        (write)
  🟩🟩🟩🟩🟩 `+148 −4  ` ~/coolstep/tests/test_spike_detector.py           (edit+write)
  🟩🟩🟩🟩🟩 `+94  −0  ` ~/coolstep/coolstep/daemon.py                     (edit)
  cmd: `pytest tests/test_spike_detector.py -v` · `rg -n "WorkloadProfile"` …
  → Done, commit 599cfcd. spike_detector.py — state machine enters at |res|≥5°C ×2 ticks…
```

Extraction is **fully deterministic** — no LLM, no judge. That is what
makes the next section possible.

## The four invariants

A lossy map cannot be validated by reconstruction (that is what a
compressor is for — see below). It *can* be validated for **faithfulness
and completeness**. `recap --audit` runs a second, independent pass over
the raw transcript and asserts four properties:

| Invariant | Statement | What a failure would mean |
|---|---|---|
| **I1 coverage** | every message record is assigned to exactly one segment (or the pre-first-prompt preamble) | a record was silently dropped |
| **I2 conservation** | per-tool counts summed over segments equal the counts in the raw transcript | a tool call was lost or double-counted |
| **I3 provenance** | every file path and command shown is a verbatim member of the transcript's tool inputs | something was fabricated |
| **I4 determinism** | an independent recompute of every diffstat yields the same integers the render used | a number was estimated rather than measured |

The audit is not the same code path as the render: `recap.audit()`
re-parses the file and re-tallies tools, diffstats, paths, and commands
from scratch, then compares totals. A bug in segmentation or attribution
shows up as a mismatch.

Across the maintainer's corpus the audit holds on **1007/1007** sessions
(`weighted-compact recap --all`). On any other corpus the same command
either passes or names the session and invariant that failed.

```text
$ weighted-compact recap --all
all-invariants pass: 1007/1007
  I1_coverage      1007/1007
  I2_conservation  1007/1007
  I3_provenance    1007/1007
  I4_determinism   1007/1007
  corpus 584.0 MB → 3.35 MB = 174× smaller
```

## Lossy on purpose — why recap is not an archiver

Recap's ~180× shrink is **lossy**. You cannot rebuild the session from
it, and it does not pretend you can. For lossless archival of the raw
logs, a general compressor is strictly better — this was measured, not
assumed:

| Approach | Ratio vs raw | Lossless? |
|---|---:|:--:|
| `gzip -9` | ~1.9× | yes |
| Hand-built structural fold (content-dedup + gzip) | 1.8× | yes (exact-match verified) |
| `zstd -19` / `xz -9` | ~3.0× | yes |
| **Recap (this consumer)** | **~180×** | **no — navigation map** |

The structural fold *loses* to a plain compressor: the redundancy a
content-dedup catches across a session is only ~1.1×, and the
cross-session redundancy is caught better by zstd's large window than by
splitting the file into a skeleton plus a content store. The intuition
"sessions are 90 % tool output, so diff the tool layer" does not convert
into a lossless win — re-reads use different file windows, and the
content that *would* be derivable from git/disk is byte-reproducible only
~6 % of the time (files drift between read-time and now).

So the honest split is two extremes, no clever middle:

- **lossless** → `zstd -19` on the raw `.jsonl` (~3×, exact round-trip);
- **lossy navigation** → recap (~180×, audited faithful).

The middle ground — a smart lossy compressor that still claims fidelity —
is exactly the axis where compaction's mixture shows no edge. Recap sits
on neither horn of that problem: it makes no fidelity claim, only a
faithfulness one, and the faithfulness one is checkable.

## Where it fits

Recap reads the same source as the rest of the package
(`~/.claude/projects/`, plus `~/.claude-work/projects/` if present). It
depends on **nothing beyond the standard library** — no numpy, no e5, no
judge — so it runs on a bare checkout. It is a consumer of the session
corpus, not of the computed `importance.npz` substrate; if you want to
build a consumer on the scored substrate instead, see
[`consumers-roadmap.md`](consumers-roadmap.md) for the canonical entry
points.

The module is `weighted_compact/recap.py`; its public surface is
`build(path) -> Recap`, `render(path, recap) -> str`, and
`audit(path, recap) -> dict`. Tests are synthetic-only in
`tests/test_recap.py`.
