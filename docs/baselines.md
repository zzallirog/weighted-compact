# Baselines — comparing the seven-signal mixture against alternatives

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
| `importance` | static, shipped mixture | the seven-signal mixture itself |

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

The table will show whether the seven-signal mixture's weighting buys
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

## Where the results live

After a `baseline run-all` run:

- `<substrate>/baseline_results.json` — JSON with per-ranker fidelity
  fractions, ready to populate the README §Headline table.

The README §Headline placeholder will be filled when the run completes.
Until then, the table reads as "harness ready, measurement pending".
