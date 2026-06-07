# Bench: weighted-compact vs claude-mem

Honest head-to-head on **reconstruction fidelity** (can the compacted
context still answer questions about hidden information?) and **token
economy** (how many characters does it cost to recover one question?).

> The three weighted-compact rows below contain **real numbers** from a
> partial run on 2026-05-23 (N=30, seed=42, judge=gemma3:4b, k\_drop=0.5).
> The two claude-mem rows remain TBD — see the *Partial run, 2026-05-23*
> section below for details.
>
> To reproduce or extend with claude-mem rows, run
> [`scripts/bench_vs_claude_mem.sh`](../scripts/bench_vs_claude_mem.sh)
> on a host where the npm package is installed. The script writes
> `bench-vs-claude-mem-results.json` and prints the table to stdout.

---

## What is being compared

- **weighted-compact** ([this repo](https://github.com/zzalli/weighted-compact)) —
  substrate-based compaction. Pairs are extracted from
  `~/.claude/projects/`, scored by an inspectable six-signal importance
  mixture, then a subset is kept by ranker score under a `k_drop` budget.
  Reconstruction-QA is the primary quality gate.
- **claude-mem** ([thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)) —
  hook-driven capture + LLM summarisation + Chroma vector retrieval. A
  worker service on `:37777` exposes `/api/search`, `/api/context/semantic`
  and 8 other endpoints for retrieving past observations into new sessions.

Both want to preserve information across Claude Code sessions. They
take different routes to get there.

---

## The asymmetry

This is not a perfectly symmetric comparison and pretending otherwise
would be dishonest. The two tools split labour differently.

**What is held constant:**

- The same 30 source pairs are sampled from the local
  `recon_qa_set.jsonl` (seed=42 by default).
- The same Qs from that QA journal are asked of every method.
- The same judge model (`gemma3:4b` by default) scores every answer
  with the same prompt — `weighted_compact.recon_qa.judge.llm_judge`.
- The same `k_drop=0.5` budget is used for weighted-compact static
  rankers (`importance`, `recency`).

**What is *not* held constant — and why:**

- **Ingestion path.** weighted-compact ingests pairs from a file
  (`pairs.jsonl`) once at bootstrap. claude-mem ingests observations
  via Claude Code lifecycle hooks; there is no public batch ingest
  endpoint. So `claude-mem-*` rows in the table do not see the
  weighted-compact substrate — they see whatever observations the
  user's own claude-mem worker has already captured during normal use.
  This is the only honest way to drive claude-mem in batch.
- **Selection vs summarisation.** weighted-compact selects existing
  pairs and assembles them as markdown. `compact-qwen-analog`
  summarises full history through `qwen2.5:7b`.
  `claude-mem-context-semantic` does an `e5`-style semantic search,
  formats matching observations, and returns markdown. These are
  different shapes of "compacted context"; the bench compares them
  on outcome (Q reconstructable yes/no), not on shape.
- **Per-Q vs per-source-pair context.** weighted-compact's static
  rankers use one context per source pair (the same context answers
  all Qs about that pair). claude-mem retrieves per-Q. This advantages
  claude-mem on Qs where the worker happens to have a relevant
  observation, and disadvantages it on Qs where it has none.

Both asymmetries are surfaced in the **Honest threats** section below.

---

## Methodology

The script does, in order:

1. **Preflight.** Verifies `claude-mem` CLI is reachable (or installable
   via `npx`), the claude-mem worker responds on `${CLAUDE_MEM_HOST}:${CLAUDE_MEM_PORT}/api/health`,
   the weighted-compact substrate (`pairs.jsonl` + `recon_qa_set.jsonl`)
   exists at `$WEIGHTED_COMPACT_DATA`, ollama is up, and both
   `gemma3:4b` (judge + claude-mem context evaluator) and
   `qwen2.5:7b` (recon-LLM + /compact analog) are pulled.
2. **Sample.** Loads `recon_qa_set.jsonl`, collects the distinct
   `source_pair_idx` values, seeds a `random.Random(BENCH_SEED)` and
   samples `BENCH_N` indices. With defaults (seed=42, N=30) on a 62-idx
   journal the picked set is **deterministic** — see the appendix.
3. **Run 5 methods on the same QA entries:**
   - `weighted-compact-importance` — `build_compacted_context` with
     `load_importance()` scores, `k_drop=0.5`, `topic_decay=1.0`
     (off, for cleanest comparison).
   - `weighted-compact-recency` — same, with `load_baseline_recency()`.
   - `compact-qwen-analog` — `CompactSummarizer('qwen2.5:7b')` (full
     history minus source pair, LLM summary), our `/compact` stand-in.
   - `claude-mem-search-topk` — for each Q, hit
     `GET /api/search/observations?query=<Q>&limit=10`, format top
     10 observations as markdown context.
   - `claude-mem-context-semantic` — for each Q, hit
     `POST /api/context/semantic` with `{"q": Q, "limit": 10}`,
     use returned `context` string verbatim.
4. **Score.** Same `ask_ollama` to produce the predicted answer, same
   `llm_judge` (with source-pair grounding) to verdict yes / no / other.
   Tracks `context_chars` and `build_secs` per call.
5. **Persist.** Writes `bench-vs-claude-mem-results.json` (full per-row
   detail) and prints a markdown summary to stdout.

Reproduce with:

```sh
bash scripts/bench_vs_claude_mem.sh                  # defaults
BENCH_SEED=7 bash scripts/bench_vs_claude_mem.sh     # different seed
BENCH_N=10 bash scripts/bench_vs_claude_mem.sh       # smaller sample
```

Override claude-mem location (e.g. it's on a different host or port):

```sh
CLAUDE_MEM_HOST=192.168.88.230 CLAUDE_MEM_PORT=37777 \
    bash scripts/bench_vs_claude_mem.sh
```

---

## The script

[`scripts/bench_vs_claude_mem.sh`](../scripts/bench_vs_claude_mem.sh).
High level:

- pure bash preflight + a Python driver heredoc that imports
  `weighted_compact.recon_qa` and calls existing functions
- no new code is added to the `weighted_compact` package — the bench
  wraps `build_compacted_context`, `ask_ollama`, `llm_judge`,
  `CompactSummarizer` exactly as they are
- the claude-mem driver is two small functions: `cm_search_topk` and
  `cm_context_semantic`, both hitting the documented worker HTTP API
- failures (claude-mem returns empty, ollama timeout, etc.) are
  recorded as `judge=no` with the error in `judge_reason` — they are
  not silently dropped from the denominator

---

## Partial run, 2026-05-23

This run included only the three methods that do not require a running
`claude-mem` worker. The two claude-mem rows are reserved for a future
run by someone with the npm package installed and a populated observation
DB.

**Run parameters:** N=30 (all 30 QA entries from the 62-entry journal,
one entry per source pair), seed=42, judge=`gemma3:4b`, k\_drop=0.5,
topic\_decay=0.5 (default), Python driver at `/tmp/bench_partial.py` using
the substrate at `~/work/weighted-compact/`.

**Wall-clock:** importance 374s · recency 362s · compact\_qwen 607s.
Two bench processes ran in parallel for the first ~12 minutes (an
earlier cancelled run was not yet terminated), which inflated runtimes
for the static rankers; the compact\_qwen run executed solo. Elapsed
numbers are not directly comparable across methods for this reason.

**Note on claude-mem rows:** skipped — claude-mem not installed in this
environment. See the preflight section in
`scripts/bench_vs_claude_mem.sh` for installation instructions.

## Results

| method | n | judge\_yes / n | mean\_context\_chars | mean\_build\_secs |
|---|---|---|---|---|
| weighted-compact-importance | 30 | 3/30 = **0.100** | 7 296 | 374.7 s total |
| weighted-compact-recency | 30 | 4/30 = **0.133** | 5 874 | 362.3 s total |
| compact-qwen-analog | 30 | 1/30 = **0.033** | 1 196 | 606.9 s total |
| claude-mem-search-topk | TBD | TBD | TBD | TBD |
| claude-mem-context-semantic | TBD | TBD | TBD | TBD |

*(claude-mem rows skipped — claude-mem not installed in this environment; see prerequisites in `scripts/bench_vs_claude_mem.sh`)*

`mean_build_secs` for the static rankers reflects the full 30-entry eval loop
(not per-call), because both eval instances ran concurrently on the same
ollama backend. See the Partial run note above.

---

## Sonnet 4.6 cross-judge (2026-05-23)

The same 90 (method × source\_pair) entries from the partial run above were
re-judged by `anthropic/claude-sonnet-4.6` via OpenRouter using the
*identical* prompt template as the gemma judge
(`weighted_compact.recon_qa.judge.llm_judge`, including source-dialog
grounding). This is a cross-family check on the gemma3:4b verdicts —
addresses threat #1 ("Shared judge model bias") in the Honest threats
section below. To stay apples-to-apples the underlying predictions were
not regenerated; only the verdict step changed.

The per-entry harness was a one-off rerun of `/tmp/bench_partial.py`
extended to dump `{method, source_pair_idx, q, a_truth, predicted,
gemma_verdict, ...}` per row. The recency and importance gemma counts
matched the partial run exactly; compact\_qwen flipped 1 entry under
ollama nondeterminism (1/30 → 0/30) — within the ±15pp confidence band
at n=30.

| method | n | gemma judge\_yes / n | sonnet judge\_yes / n | per-method κ |
|---|---|---|---|---|
| weighted-compact-importance | 30 | 3/30 = **0.100** | 3/30 = **0.100** | 0.630 |
| weighted-compact-recency | 30 | 4/30 = **0.133** | 4/30 = **0.133** | 0.712 |
| compact-qwen-analog | 30 | 0/30 = **0.000** | 2/30 = **0.067** | 0.000 |

**Cross-judge agreement on the 90-entry corpus:** raw 92.2 %, Cohen's
**κ = 0.549** (moderate). Confusion (gemma row × sonnet col):

|  | sonnet=yes | sonnet=no | sonnet=other |
|---|---|---|---|
| gemma=yes | 5 | 2 | 0 |
| gemma=no | 4 | 78 | 1 |
| gemma=other | 0 | 0 | 0 |

This κ is *not* the same number as the κ=0.469 cited elsewhere in the
weighted-compact docs — that figure is for a different corpus (the
warnings re-judge tracked in `[[project_weighted_compact_warnings]]`).
Both land in "moderate", which is the expected regime for a strict
two-axis verdict prompt across model families.

**Reading the headline:** on this 90-entry slice the recency ranker
wins on both judges (0.133), importance is mid (0.100), and the
qwen-summary `/compact` analog sits at the bottom (0.000 gemma /
0.067 sonnet). The 6.7pp importance-over-qwen gap claimed in the
partial-run section above shrinks to 3.3pp under the stricter judge,
and recency over compact\_qwen narrows from 13.3pp (under gemma) to
6.7pp (under sonnet) — small enough to fall inside the n=30 confidence
band either way. The honest read is: at this sample size and
`k_drop=0.5`, the three weighted-compact methods are *tied within
noise on the importance/recency side*, with compact\_qwen plausibly
worst but not certainly so.

The seven disagreements split cleanly: three are Sonnet catching a
weak reference ("текст" / "порядок" are too underspecified to be
answered by a long technical paraphrase — Sonnet votes no/other where
gemma voted yes) and four are Sonnet crediting an exact anchor (port
`8112`, command `Set-SPOSiteArchiveState`) that gemma rejected because
of surrounding noise. Both directions are sane judgements; neither
judge is systematically more generous, which is what κ=0.549 with
balanced off-diagonals shows. The compact\_qwen per-method κ of 0.000
is a small-sample artefact (the gemma column is all-no, so any sonnet
flip kills the marginal denominator), not a real disagreement signal —
read the cross-corpus κ=0.549 as the calibration number, not the
per-method row.

**Cost:** 96 321 input tokens × \$3 /M + 3 446 output tokens × \$15 /M
= **\$0.34** for 90 calls.

**Reproduction:**

```sh
OPENROUTER_API_KEY=$(cat ~/.config/openrouter-key) \
    python3 scripts/sonnet_rejudge.py /tmp/bench_per_entry.jsonl \
    > /tmp/sonnet_judge_results.jsonl \
    2> /tmp/sonnet_judge_summary.txt
```

The script is standalone (stdlib only, no project imports). It reads
the OpenRouter key from `OPENROUTER_API_KEY` env, takes a per-entry
JSONL produced by the bench harness as its positional argument, emits
rejudged rows to stdout, and prints the agreement summary table to
stderr. Concurrency is gated to 4 in-flight calls; the script refuses
to proceed if input exceeds 200 rows (cost cap ≈ \$2).

---

## Reading the numbers

- **`judge_yes / n` (primary axis — fidelity).** Fraction of Qs the
  judge calls "yes". Two-axis judge: both vector (right direction)
  and anchor (specific information) must match. Vague paraphrase that
  smells right but drops the number / name / threshold = "no". This
  is the headline.
- **`mean_context_chars` (secondary axis — token economy).** How
  expensive each compacted context is. Combined with `judge_yes / n`
  this gives **bytes-per-recovered-question** = `mean_context_chars /
  judge_yes_fraction`. Lower is better, all else equal.
- **`mean_build_secs` (operational axis).** Wall-clock for one
  context build. weighted-compact static rankers are sub-millisecond
  (npz lookup + sort). LLM-summary methods (`compact-qwen-analog`,
  optionally claude-mem if its provider routes there) are seconds.

**What counts as a win / tie / loss:**

- A method **wins** on fidelity if its `judge_yes / n` is meaningfully
  above the others *and* the gap survives a different judge model.
  With n=30, gaps under ~5 percentage points are noise.
- A method **wins** on economy if its bytes-per-recovered-question is
  meaningfully lower at *similar* fidelity. Saving bytes by dropping
  fidelity is not a win; it's a different operating point.
- **Tie** is the most common honest verdict at n=30. Say "tie", do
  not over-read the table.
- A method **loses** when both axes go the wrong way.

---

## Honest threats

1. **Shared judge model bias.** `gemma3:4b` is the same judge model
   weighted-compact's existing tooling uses for development. It may
   have a stylistic preference for the markdown shape weighted-compact
   produces. The doc says nothing definitive on this until a
   second-judge re-run (e.g. `claude-sonnet-4-5` per the existing
   judge-calibration runs in `docs/05-roadmap.md`) is done.
2. **Sample size.** n=30 is small. Confidence intervals on
   `judge_yes / n` at n=30 are roughly ±15 percentage points. A
   single source-pair-idx flipping its verdict moves the number by
   ~3.3 points. Treat differences below ~10 points as "could be
   noise, run again with more pairs".
3. **claude-mem ingestion asymmetry.** claude-mem is *not* operating
   on the weighted-compact substrate. It is operating on its own
   observation DB. If your worker has captured rich observations for
   the same topics, its rows go up. If your worker is fresh, its rows
   are near-zero. This is the only honest way to drive a hook-driven
   tool in batch — but it means `claude-mem-*` numbers depend on a
   variable this bench cannot control.
4. **One user's corpus.** The substrate at
   `$WEIGHTED_COMPACT_DATA/pairs.jsonl` is one user's
   `~/.claude/projects/` history. Results on a different topic mix
   (more code-heavy, more conversational, more multilingual) may
   reorder the table. Run on yours.
5. **`k_drop=0.5` is a free parameter.** weighted-compact lets you
   keep more (or fewer) pairs; the bench fixes it for comparability.
   Adversarial tuning (sweep `k_drop` per method) is left to a
   follow-up; this bench reports the default operating point.
6. **`/api/context/semantic` returns empty for short queries.** Its
   handler rejects `query.length < 20`. The bench pads short Qs with
   a trailing context phrase rather than dropping them, which slightly
   advantages claude-mem on shorter Qs by making them retrievable at
   all. Disclosed here; documented in `cm_context_semantic()` in the
   script.

---

## Reproduction invited

If you have both tools installed locally, please run the bench on your
own substrate and your own claude-mem observation DB, then file the
numbers as a GitHub issue on this repo with label `bench:`:

```sh
gh issue create --repo zzalli/weighted-compact --label bench: \
    --title "bench-vs-claude-mem on <your-corpus>" \
    --body-file bench-vs-claude-mem-results.json
```

Numbers from different corpora are how this comparison becomes
meaningful. One run on one user's data is a data point; ten runs
across different topic mixes is a result.

---

## Appendix — deterministic sample (seed=42, N=30)

With `BENCH_SEED=42` and `BENCH_N=30`, sampled from the 62 distinct
`source_pair_idx` values in `recon_qa_set.jsonl` as of 2026-05-23:

```
[3, 17, 24, 35, 38, 58, 82, 86, 91, 137, 147, 262, 285, 287, 315,
 357, 358, 362, 367, 392, 415, 464, 473, 481, 491, 494, 525, 532,
 540, 541]
```

If your `recon_qa_set.jsonl` has a different distinct-idx set, the
sample will differ even with the same seed (the bench samples from
*your* journal). The exact idx list is also persisted in
`bench-vs-claude-mem-results.json` under `picked_idxs` so any
reported number can be reproduced.
