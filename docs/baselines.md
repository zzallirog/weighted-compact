# Baselines — comparing the six-signal mixture against alternatives

The headline 3.8 % per-Q fidelity floor (Sonnet 4.6 judge, 573 pairs)
reads as an absolute number. The question this doc answers: **how does
that floor compare to alternative ranking strategies on the same
harness?**

The baselines harness runs each candidate ranker through the same
`run_eval(k_drop, ranker)` path, the same `recon_qa_set.jsonl`, the
same generator, the same judge — so the difference between two
fidelity numbers reflects only the ranker.

## What baselines are tested

| Name | Class | What it measures |
|---|---|---|
| `random` | static, drop-in | absolute lower bound — no signal at all |
| `recency` | static, drop-in | position-in-session — cheapest single-line heuristic |
| `density` | static, drop-in | legacy single signal (entropy, anchors) |
| `cosine` | query-aware | e5 dense similarity to the question |
| `bm25` | sparse, query-aware | classical lexical retrieval |
| `compact_qwen` | summarisation bypass | `/compact` analog via local qwen2.5:7b |
| `compact_sonnet` | summarisation bypass | `/compact` analog via Sonnet 4.6 (opt-in) |
| `importance` | static, shipped mixture | the six-signal mixture itself |

## Architectural axis

Three paradigms appear in the table:

1. **Static rankers** (`importance` / `density` / `random` / `recency`) —
   produce one importance score per pair, independent of which question
   gets asked. The same compacted context applies to every question
   targeting a given source pair.

2. **Query-aware retrieval** (`cosine` / `bm25`) — produce per-question
   scores, so the context differs across questions for the same source
   pair. This is the retrieval-style paradigm; the price is one ranker
   call per question.

3. **Summarisation bypass** (`compact_*`) — skip pair selection
   entirely. The LLM produces a single summary that becomes the entire
   compacted context. Closest fair analog to Claude Code's `/compact`,
   though the exact prompt is closed and version-dependent.

The table will show whether the six-signal mixture's weighting buys
anything over each paradigm.

## How to run

Build the static baseline artefacts (one-time):

```bash
weighted-compact baseline build --ranker random
weighted-compact baseline build --ranker recency
```

Run all baselines at once (overnight job — one full `run_eval` pass per
ranker over the qa_set):

```bash
weighted-compact baseline run-all
```

This auto-builds any missing static baseline npz files, runs each ranker
sequentially through the same harness, and writes the results to
`<substrate>/baseline_results.json`.

To include the opt-in cloud `/compact` tier (requires
`ANTHROPIC_API_KEY` and `pip install -e .[baselines-cloud]`):

```bash
weighted-compact baseline run-all --include all
```

Single-ranker runs are still available via the existing entry point:

```bash
weighted-compact qa-gate --ranker bm25 --easy-k 0.0 --hard-k 0.9 --signal judge
```

## Honest commitment

If any non-`/compact` baseline beats the mixture by ≥ 0.05 absolute
judge-yes fraction, the README narrative reverts: the mixture is not
buying signal beyond what the strongest baseline already provides, and
the project's positioning has to follow that. The plan file
[`/home/zzalli/.claude/plans/starry-napping-mccarthy.md`](../../../.claude/plans/starry-napping-mccarthy.md)
records this commitment.

## Fairness disclosures

- **Cross-paradigm asymmetry.** Static rankers see one context per
  source pair; query-aware rankers see one context per question. This
  asymmetry favours query-aware methods in principle; reporting both
  paradigms in one table makes that explicit.
- **`/compact` simulation prompt** is not Claude Code's exact prompt
  (that prompt is closed). The simulation hides the source pair and
  asks an LLM to summarise the rest, keeping content that would help
  answer questions about what was hidden. The intent matches `/compact`;
  the prompt does not.
- **Judge.** Default is `gemma3:4b` (the cheap-judge tier). The
  headline 3.8 % number used Sonnet 4.6; for an apples-to-apples
  comparison the user must re-run all baselines with the Sonnet judge
  (opt-in, see [`docs/05-roadmap.md`](05-roadmap.md)).
- **`compact_sonnet`** uses the user's own Anthropic credentials, not
  the maintainer's. The default `baseline run-all` excludes this tier;
  pass `--include all` to opt in.

## Results — 2026-05-21 first run

Maintainer corpus, recon_qa_set N=62, k_drop=0.5, gemma3:4b judge.

| Method | judge-yes | per-Q fidelity |
|---|---:|---:|
| Random selection (seed 42) | 8/62 | **12.9 %** |
| six-signal mixture | 7/62 | **11.3 %** |
| Recency-only | 7/62 | 11.3 % |
| Cosine retrieval (e5) | 7/62 | 11.3 % |
| Density (single signal) | 6/62 | 9.7 % |
| BM25 retrieval | 6/62 | 9.7 % |
| qwen-summarized `/compact` analog | 2/62 | **3.2 %** |

### Reading the table

**Strong finding — structured selection > summary-bypass by ~8 pp.**
Whatever ranker is used, *selecting* pairs beats discarding pair
structure for a single LLM summary. This is the value-prop the mixture's
architecture earns under the present measurement.

**Null finding — mixture vs cheap structured baselines.** At N=62 under
gemma3:4b judge (κ=0.47 vs Sonnet), the mixture is statistically
indistinguishable from random / recency / cosine. The pre-registered
"broad highlight" target (Δ ≥ +0.05 absolute vs cheap baseline) is not
met. Per the project's narrative-positioning decision matrix, this
shifts the register to **tight**: report magnitude and direction
honestly, do not claim a mixture advantage that the data does not show.

**Why this isn't formally a "revert".** The honest-revert criterion is
"any non-`/compact` baseline beats mixture by ≥0.05 absolute". Random
beat mixture by **0.016 absolute** (1 question out of 62) — that is
within noise, not a real signal. So neither the broad-positive nor the
formal-negative bar is crossed; the result sits in the null zone.

### What this changes about the project's claim

Before this measurement, the README's headline rested on a 3.8 % Sonnet
floor (with the mixture *implied* to lift above that floor when
deployed). The new measurement clarifies:

- Lifting above naive `/compact` summary is **shown** — ~8 pp.
- Lifting above cheap structured baselines is **not yet shown** at this
  scale under this judge.

So the value the mixture currently earns is *not* "the best ranker" but
"a ranker that beats summary-bypass and is architected for measurement
discipline" (replaceable parts, held-out fidelity gate, graceful
degradation). Whether the mixture's *specific* weights beat random
requires more data and a stricter judge.

### Open paths to resolve

1. **Sonnet re-judge** on the same 62-entry set — apples-to-apples with
   the existing 3.8 % Sonnet number. Filed for v0.3.
2. **Larger QA set** — N=62 has wide binomial CI (±~4 % absolute per
   row). A 200-500 entry set would shrink the noise to where 1-2 pp
   differences become measurable.
3. **Full coefficient grid ablation** — currently only the label-weight
   slot has been swept (Δ=+0.053 under cheap judge, see §Headline).
4. **Multi-user reproduction** — open invitation in §Status.

### Where the raw results live

- `<substrate>/baseline_results.json` — the JSON dump produced by
  `baseline run-all`, with per-ranker counts (judge_yes, substring_pass,
  fractions) and harness metadata (k_drop, signal, n_qa).
- `<substrate>/baseline_run_<timestamp>.log` — full run log, including
  per-ranker progress and any model-load notes.
