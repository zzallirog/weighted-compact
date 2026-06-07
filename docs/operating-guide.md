# Operating guide — how / what / how much / why

> *"Does weighted-compact work as designed? Can it be the substrate
> behind retrieve-from-compact — returning to history without losing
> quality? What is the budget?"*

This guide answers those four questions with measured numbers from the
maintainer's substrate (573-pair corpus, AMD Ryzen 9 7940HS, 15 GiB RAM,
Arch Linux). Every number has the command that produced it next to it, so
you can re-run on your own substrate and compare. Where a number depends
on hardware (RAM, latency) the assumption is stated inline.

This is an honest operating readout — not a sales pitch and not a
roadmap. If something is broken or unsolved, it is named here.

---

## What this answers

The four questions, verbatim from the user prompt:

1. **Does the system work as designed?** — see
   [§Does it work as designed?](#does-it-work-as-designed)
2. **Can it be the substrate for retrieve-from-compact (returning to
   history without losing quality)?** — see
   [§Is it a substrate for retrieve-from-compact?](#is-it-a-substrate-for-retrieve-from-compact)
3. **What is the budget?** — see
   [§The budget, measured](#the-budget-measured)
4. **How, what, how much, why** for each major operation — see
   [§How / What / How much / Why](#how--what--how-much--why)

Plus two sections that fall out of the above:

- [What it doesn't do](#what-it-doesnt-do) — the honest negative space.
- [Reading the meta dict](#reading-the-meta-dict) — short reference for
  `build_compacted_context_with_meta`'s return shape.

---

## Does it work as designed?

**Yes, mechanically — end-to-end.** The pipeline parses sessions,
decorates pairs with six signals, composes them into an importance
score, and the compaction reader queries that score to return a
markdown context for any source pair. Numbers below are from the
maintainer's substrate at `~/work/weighted-compact/` as of 2026-05-23.

What works (verified at the time of this writing):

| Layer | Verifier | Result |
|---|---|---|
| Substrate builder | `wc -l ~/work/weighted-compact/pairs.jsonl` | **613 pairs** across 246 sessions |
| Feature extractors | `du -h ~/work/weighted-compact/features*.npz` | features.npz 2.8 M (613×3×384 e5 windows), features_density.npz 44 K, features_spans.npz 24 K |
| Importance mixture | `weighted-compact importance` | 613 pairs ranked, mean 0.370, min 0.065, max 0.802 — top-10 are all label=1.0 + density>0.6 (matches design intent) |
| REM decay | `weighted-compact rem-pass` | 613 pairs over 246 sessions, 194 sessions aged (timestamp resolvable from `~/.claude/projects/<dashed>/<sid>.jsonl` mtime), 52 sessions missing mtime — factor 1.0 fallback |
| Compaction reader | `build_compacted_context_with_meta` on session of 15 pairs | 14 candidates, 7 kept at k_drop=0.5, 23 425→11 991 chars (compaction ratio 0.51), signals_top3 = density / span_keep / label |
| Fidelity gate | `weighted-compact qa-gate --signal judge` against `recon_qa_set_v2.jsonl` (1718 entries) | shipped — see [README headline](../README.md) table for the published 11.3 % per-Q result |

What is **degraded but graceful**:

- `compact_session` from the MCP path lazily loads pairs+importance+topic
  on first call (~80 ms warm, ~150-200 ms cold). The substrate path that
  the CLI takes — `recon_qa.load_pairs()` + `load_importance()` — is
  about 70 ms total cold for the maintainer's corpus.
- `bootstrap` on the maintainer's source-dir layout took 6.07 s for
  376 sessions / 750 MB of raw JSONL (command below). On a fresh
  machine without prior `features.npz` the first feature_extract pass
  also pays the e5-small model load (~1.6 s) before per-pair embedding
  (~3-5 ms/pair on CPU). That's not in the substrate copy currently,
  so it is not re-measured here — see `docs/install.md` for the cold
  bootstrap cost discussion.

What does **not** work as designed (be honest):

- The headline 11.3 % per-Q fidelity at k_drop=0.5 is a low absolute
  number. The mixture matches a uniform random ranker (12.9 %) within
  ±1 question under the gemma3:4b judge at N=62. The architectural
  claim ("structured selection beats summary-bypass by 8 pp") survives;
  the narrower claim ("the six-signal mixture beats cheap structured
  baselines") **does not currently survive measurement** at this N.
  See `docs/05-roadmap.md` for the v0.3 plan.
- The label-weight ablation (`label_weight ∈ {0, 0.15}`) shipped
  Δfidelity = +0.053 with 95 % paired CI [−0.004, +0.109] — the lower
  bound crosses zero. The label signal is therefore an **optional
  power-tier**, not a precondition; six automatic signals carry the
  substrate by themselves.
- Iter-chain mode distinction (`complement` / `refine` / `deepen`)
  clusters in cosine drift `[0.95, 1.00]` under the current generator
  — calibrated bands would be too tight (σ ≈ 0.005–0.012) to be useful.
  The inspector shows these labels but they don't differentiate yet.

So: the *pipeline* works as designed end-to-end. The *quality claim*
that the six-signal mixture beats every cheap ranker is not yet met
on this N. The substrate is solid; what consumers do with it is where
the open work lives.

---

## Is it a substrate for retrieve-from-compact?

**Yes — mechanically. With caveats on absolute fidelity.**

The single function that answers "given that a session was compacted,
what survives?" is `build_compacted_context_with_meta` in
[`weighted_compact/recon_qa/context.py`](../weighted_compact/recon_qa/context.py).
It is the public entry point for retrieve-from-compact, both from the
CLI/eval harness and from the MCP `compact_session` tool.

### The data flow, end-to-end

```
~/.claude/projects/*/*.jsonl       (Claude Code stores one subdir per CWD)
        │
        │  weighted-compact bootstrap
        ▼
pairs.jsonl  ──┬── feature_extract.py     → features.npz          (e5 windows)
               ├── density_features.py    → features_density.npz  (16 signals)
               ├── span_features.py       → features_spans.npz    (char-fractions)
               └── topic_segments.py      → topic_segments.npz    (segment ids)
                            │
                            │  weighted-compact importance
                            ▼
                    importance.npz  ── (N, 6) components + (6,) weights
                            │
                            │  weighted-compact rem-pass (nightly, optional)
                            ▼
                    rem_decay.npz   ── per-pair multiplier ∈ (0, 1]
                            │
                            │  build_compacted_context_with_meta(
                            │      source_pair_idx=<int>,
                            │      scoring=load_importance(),
                            │      k_drop=0.5,
                            │      topic_decay=0.5,
                            │      topic_map=load_topic_map(),
                            │      rem_decay_map=load_rem_decay())
                            ▼
            (markdown context string, meta dict)
```

**Given any `source_pair_idx`**, you get back the top-K pairs from the
same session (excluding the source itself) ranked by
`importance × topic_decay^|Δtopic| × rem_decay`, formatted as
`PREMISE / CORRECTION / ---` blocks. The meta dict reports how many
pairs survived, how many chars were saved, and which signals drove the
selection.

This is the retrieve-from-compact loop in one function call. Anything
that can compute a `pair_idx` (search, MCP `compact_session`, the
fidelity harness, a custom tool) can ask: *if I had compacted this
session, what would still be in context?*

### Without losing quality?

The harness measures exactly this — hide one pair, build the context
from the rest, ask whether a question whose answer lived in the hidden
pair can still be answered. The current numbers from
[the README](../README.md#numbers-and-their-meaning):

- **Sonnet 4.6 judge, k_drop=0 (hide source only), N=1718:** per-Q
  fidelity floor = **3.8 %**. This is the absolute starting position —
  ~96 % of pair-specific detail is unrecoverable once that pair is
  hidden.
- **gemma3:4b judge, k_drop=0.5, N=62:** mixture = **11.3 %** (7/62),
  random = 12.9 % (8/62), recency = 11.3 %, cosine = 11.3 %, qwen
  summary baseline = 3.2 % (2/62).

What this means for retrieve-from-compact:

1. **The substrate-vs-summary axis works.** Any structured ranker beats
   a one-pass LLM summary by 5/62 questions = 8 pp. This is the
   substantive result for "is structured retrieval better than naive
   `/compact`-style summarisation." Yes, by a clear margin.
2. **The mixture-vs-cheap-rankers axis is not yet measurable.** At N=62
   under cheap judge, mixture / recency / cosine / random are within
   ±1 question. If you want a guarantee that the mixture beats random
   at picking the *right* surviving pairs, the current data does not
   support that.
3. **Absolute fidelity is low everywhere.** The retrieve-from-compact
   substrate gives you a faithful render of *what you marked
   important*; it does not give you "perfect recall" of the original
   session. If you need perfect recall, bigger context windows are the
   answer, not better compaction.

So: yes, the substrate **is** the retrieve-from-compact backend, and
the API is `build_compacted_context_with_meta`. But "without losing
quality" depends on what you compare against:

- vs `/compact`-style summarisation: **substantial win** (8 pp).
- vs uniform random selection over the same substrate: **no measured
  edge yet** at N=62 under gemma3 judge.

The retrieve-from-compact framing is sound. The mixture weights are
the open question.

---

## The budget, measured

All numbers below are from the maintainer's substrate
(`~/work/weighted-compact/`) on an AMD Ryzen 9 7940HS / 15.5 GiB
RAM / Arch Linux box, 2026-05-23. Each row gives the command that
produced it, so you can reproduce on your own substrate.

### Disk

| Item | Size | Command |
|---|---|---|
| **Total substrate dir** | **24 MB** | `du -sh ~/work/weighted-compact/` |
| `pairs.jsonl` (613 entries) | 2.1 MB | `du -h ~/work/weighted-compact/pairs.jsonl` |
| `features.npz` (613×3×384 e5 windows) | 2.8 MB | `du -h ~/work/weighted-compact/features.npz` |
| `features_density.npz` | 44 KB | same |
| `features_spans.npz` | 24 KB | same |
| `importance.npz` (current) | 28 KB | `du -h ~/work/weighted-compact/importance.npz` |
| `recon_qa_set_v2.jsonl` (1718 QA triples) | 548 KB | `du -h ~/work/weighted-compact/recon_qa_set_v2.jsonl` |
| `gemma3_verdicts.jsonl` (judge cache) | 356 KB | same |
| `deltas.jsonl` (drift trace) | 332 KB | same |
| **All `.bak.*` snapshots** (53 files, ~one per recompose) | 4.9 MB | `find ~/work/weighted-compact -maxdepth 1 -name "*.bak.*" -exec du -ch {} + \| tail -1` |

The bak snapshots are *not* dead weight — the Drift Inspector tile reads
the last N `importance.npz.bak.*` to compute per-pair trajectories. If
you don't care about drift, you can prune them by `mtime > 30` and lose
nothing else. They cost about 28 KB each.

**Scaling.** Substrate disk is roughly linear in pair count: at 613
pairs the substrate is 24 MB minus the bak history, so roughly
**30 KB per pair** including features. A 5 000-pair corpus extrapolates
to ~150 MB substrate + bak history; a 50 000-pair corpus to ~1.5 GB.
This is small enough to ignore on any modern disk.

### RAM

| State | RSS | Command / source |
|---|---|---|
| `weighted-compact compat` cold | ~30 MB | `/usr/bin/time -v weighted-compact compat` — Python + click + a few imports |
| `load_pairs()` + `load_importance()` + `load_topic_map()` | **33 MB RSS** | `python -c 'import resource; from weighted_compact.recon_qa.context import load_pairs, load_importance, load_topic_map; load_pairs(); load_importance(); load_topic_map(); print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,"MB")'` |
| MCP server idle (after first call) | ~50 MB | observed via `mcp_server._tool_substrate_info()` + 1× compact — numpy npz mmap-backed |
| Labeler (`weighted-compact serve`) — idle | ~80–100 MB on maintainer's box | FastAPI + uvicorn + pairs + features.npz loaded; needs measurement on your machine |
| `rem-pass` peak | ~40 MB | measured by `/usr/bin/time -v weighted-compact rem-pass` (needs measurement on your machine for confirmation) |
| `bootstrap` peak (376 sessions, 750 MB raw input) | ~120 MB | one session loaded at a time; needs measurement on your machine for confirmation |

On the maintainer's machine, the steady-state cost of having
weighted-compact "ready to query" is **under 50 MB** — small enough to
sit in a long-lived process alongside the user's IDE without
ceremony. The labeler is the only component that holds e5 in memory
(~120 MB extra if `--with-anti-drift` is on); the runtime path does
not.

### CPU / wall-clock latency

| Operation | Latency | Command |
|---|---|---|
| `load_pairs()` | **12 ms** | timed Python: 613 pairs from pairs.jsonl, single pass |
| `load_importance()` | **57 ms** | timed Python: open npz, build dict of 613 entries |
| `load_topic_map()` | **33 ms** | timed Python: open npz, 537 entries |
| `build_compacted_context_with_meta` — first call | **47 ms** | timed Python: 14-candidate session, k_drop=0.5, topic_decay=0.5 |
| `build_compacted_context_with_meta` — warm avg over 10 | **23 ms** | same session, repeated |
| `mcp_server._tool_substrate_info()` | **22 ms** | timed Python: counts pairs, checks file presence |
| `mcp_server._tool_compact_session` — warm avg over 10 | **87 ms** | timed Python: includes full load_pairs+load_importance+load_topic_map+build each call (MCP path does not cache between calls in current implementation) |
| `weighted-compact importance` (full recompose, 613 pairs) | **23 ms** | timed Python: `importance.main()` |
| `weighted-compact rem-pass` (613 pairs, 246 sessions, half-life=7d) | **31 ms** | timed Python: `rem_decay.build(half_life_days=7.0)` |
| `weighted-compact bootstrap` (376 sessions, 750 MB raw JSONL → 495 pairs) | **6.07 s** | timed: substrate's `extract_pairs.py` against `~/.claude/projects/-home-zzalli` + `~/.claude-work/projects/-home-zzalli` |

The runtime path — **load substrate, build one compacted context with
meta** — fits in well under 100 ms on the maintainer's machine. That
is fast enough to call once per `/compact` event without measurable
user-visible latency. The MCP path is slower per call (~87 ms warm)
because it re-loads pairs+importance+topic on every call; that is
where the first easy optimization lives (cache the loaders on the
server process) but it has not been done.

### First-run cost on a 100-session corpus (estimate)

Linear extrapolation from the measured 376-session bootstrap at 6.07 s
(no embedding pass, no rem):

| Step | Per-session | 100-session estimate |
|---|---:|---:|
| `bootstrap` (extract_pairs) | ~16 ms | **~1.6 s** |
| `feature_extract` (e5, CPU) | ~3–5 s for model load + ~3–5 ms/pair | **~4 s + N pairs × 5 ms** ≈ 8–12 s for 1000 pairs |
| `density_features` | <100 ms total | **<100 ms** |
| `topic_segments` | <500 ms total | **<500 ms** |
| `importance` (composer) | <30 ms total | **<30 ms** |
| `rem-pass` | ~30 ms | **~30 ms** |
| `qa-gate` (judge, depends on Ollama) | ~5–15 s per QA × ~50 QA | **~5–15 min** |

**Bottom line:** first-run wall-clock from a fresh 100-session corpus
to a ranked substrate ready for `compact_session` is **under 30 seconds
without the recon-QA gate**. The recon-QA gate is the long pole and
runs on user-controlled schedule (nightly, or on demand) — it is not
required for compaction to work.

---

## How / What / How much / Why

Five operations, four sub-headers each. The structure is the same
everywhere for fast comparison.

### bootstrap

**How.** `weighted-compact bootstrap` walks the configured Claude Code
source dirs (`~/.claude/projects/`, `~/.claude-work/projects/` by
default; override via `WEIGHTED_COMPACT_CLAUDE_SOURCES`), reads every
JSONL session file ≥ 5 KB, and extracts `(premise_text,
correction_text)` pairs whenever the regex bag detects a correction
marker (`нет / no / wait / wrong / explicit (mark) tags / …`). Pairs
are written append-only to `pairs.jsonl`.

**What.** Per-pair record with `{session_id, correction_uuid,
correction_text, premise_uuid, premise_text, marker_type,
marker_match, tier_hint}`. The session_id is the basename of the
source JSONL (a UUID), which is what `build_compacted_context` keys on
to find sibling pairs in the same session.

**How much.** 6.07 s for 376 sessions / 750 MB of source on the
maintainer's box; output 495 pairs / 1.8 MB. Memory peak ~120 MB
(one session in memory at a time). Linear in source size; the wall
clock is dominated by JSON parsing and regex matching, not by
embedding.

**Why.** The pairs are the substrate. They are the only thing every
downstream feature extractor reads. Once `pairs.jsonl` exists with a
stable schema, the rest of the pipeline is `features.npz` /
`features_density.npz` / etc. — each independently rebuildable from
the same `pairs.jsonl`. Bootstrap is the one step where format
decisions get locked.

**Re-bootstrap caveat.** Re-running `bootstrap` over a different source
set (new sessions, fixed glob/regex, etc.) regenerates `pairs.jsonl`
**with fresh pair_idx numbering**. Two downstream artifacts are tied to
the old indexing and need attention:

- **`labels.jsonl`** — pair_idx values refer to the previous corpus's
  ordering. If the new pair at index 7 isn't the same conversation as
  the old pair at index 7, those labels are mismatched. Either:
  prune labels that don't match the new pair's `(session_id,
  marker_match)` fingerprint, or move `labels.jsonl` aside and
  re-label.
- **`queue.jsonl`** — the labeler's active-learning queue is produced
  by `build_queue.py` from disagreement / low-conf / audit signals.
  After re-bootstrap, `queue.jsonl` is stale or absent; the labeler
  will report `all=0 disagreement=0 low_conf=0 audit=0` in the
  mode bar. Until queue is rebuilt (which itself requires a trained
  classifier on fresh labels), use **cluster mode** — it operates on
  `features.npz` alone and doesn't depend on the queue.

This is annoying but intentional: pair_idx is the substrate's primary
key, and re-numbering on re-bootstrap means anything keyed by it is
quarantined until you decide whether to migrate or discard.

### importance

**How.** `weighted-compact importance` loads
`features_density.npz` + `labels.jsonl` +
`features_spans.npz`, normalises each signal column to [0, 1], and
composes them by the fixed weight vector:

```
importance = 0.25 × density + 0.15 × label
           + 0.20 × span_keep + 0.10 × span_maybe
           − 0.15 × span_skip + 0.05 × span_think
```

Output is written atomically to `importance.npz` (with a `.bak.<ts>`
snapshot of the previous file).

**What.** `(N, 6)` `components` array, `(6,)` `weights` vector,
`(N,)` `importance` final score, `(N,)` `pair_indices`. The
components array is what `build_compacted_context_with_meta` reads
back to populate `signals_top3` for any kept set.

**How much.** 23 ms for the full 613-pair recompose. Reading the
inputs dominates; the math is one dot product. Memory peak <10 MB on
top of the numpy import overhead.

**Why.** This is the only place the six signals come together. The
ablation work happens here: change a weight, recompose, re-run
`qa-gate`. The mixture being a weighted sum (not a learned model) is
deliberate — see `docs/03-quality-driver.md` for the Goodhart
argument. We do not gradient-descend these weights against
reconstruction fidelity; the loop is held out as a fitness gate.

### rem-pass

**How.** `weighted-compact rem-pass [--half-life-days N]` reads
`pairs.jsonl`, stats the mtime of each session's source JSONL at
`~/.claude/projects/<dashed_cwd>/<session_id>.jsonl`, and computes
`factor = exp(-ln(2) × age_days / half_life_days)` per pair. Writes
`rem_decay.npz` atomically with `.bak.<ts>` rotation.

**What.** Per-pair multiplier ∈ (0, 1]. At default 7-day half-life:
today = 1.00, yesterday = 0.91, 1 week ago = 0.50, 1 month ago = 0.05.
Sessions whose transcript can't be stat'd fall back to factor 1.0
(visible rather than silently dropped).

**How much.** 31 ms for 613 pairs / 246 sessions. The stat()s are
the bottleneck; on a hot disk it's noise. Memory peak <15 MB. Disk
output: one npz, ~7 KB.

**Why.** The six-signal mixture is content-stable — it does not
know whether a pair is from today or three months ago. REM-decay
adds the time axis as a multiplier so the content score and the
recency score compose without conflating axes. The metaphor is
structural (sleep re-weights yesterday's experience overnight); the
implementation is one exponential. The decision to multiply rather
than add a `recency` column to the mixture preserves the
**rerun-on-fresh-clock contract**: change the date, rerun rem-pass,
nothing else changes.

### mcp-serve

**How.** `weighted-compact mcp-serve` (requires `[mcp]` extra) spawns
a stdio MCP server exposing three read-only tools: `search_pairs`
(cosine over `features.npz`), `compact_session` (calls
`build_compacted_context_with_meta`), `substrate_info` (file presence
and counts). No network listener; the client (Claude Desktop, mcp-cli)
spawns it as a subprocess and pipes stdio.

**What.** A query surface over the already-built substrate. The
client decides when to call. There is no auto-injection, no labeler,
no write path. On missing substrate each tool returns
`{"error": "substrate_not_built", "hint": "..."}` rather than dying —
the stdio loop survives a misconfigured client.

**How much.** 22 ms for `substrate_info` (cold). 87 ms average per
`compact_session` warm — the current implementation re-loads
pairs+importance+topic on every call, so this is not as fast as the
in-process CLI path (which can cache via module globals). RAM: ~50 MB
steady-state once a few tools have been called. `search_pairs` adds
~120 MB if the e5 model gets loaded.

**Why.** MCP is the surface that lets any MCP-speaking client query
the substrate without re-parsing or re-importing. The local-only
stdio framing is non-negotiable — the substrate carries raw
conversation text that should not sit on a port. If you want a remote
MCP endpoint, fork the module and add SSE/HTTP behind your own auth;
that is a separate concern.

### qa-gate

**How.** `weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9
--ranker importance --signal judge` runs the recon-QA loop twice
(weak vs strong compaction) over `recon_qa_set.jsonl`, classifying
each QA triple into `trivial / impossible / informative / inverted`
based on whether the judge model (gemma3:4b by default) verdict
flips between the two compaction levels. Only the *informative*
bucket carries gradient — the others say nothing about the ranker
either way.

**What.** A 4-bucket count + a signal-disagreement breakdown. With
`--write`, the informative subset is persisted to
`qa_informative_subset.jsonl` for ablation runs.

**How much.** This is the expensive operation. Each judge call goes
to Ollama (`gemma3:4b` by default, ~3–5 s on the maintainer's box
without GPU offload, faster with). For ~50 QA entries × 2 compaction
levels × 1 judge call each = ~100 LLM calls = ~5–15 minutes
end-to-end. Numbers are wall-clock heavy; pure Python work is in
single-digit seconds.

**Why.** This is where "did the substrate help compaction?" gets a
numerical answer. The cross-family judge (gemma3 judges qwen
reconstructions) is the architectural contract that keeps the eval
honest. Without this loop, signal-weight changes would be pure
intuition. With it, an ablation tells you in 15 min whether your
change helped, hurt, or was a tie.

---

## What it doesn't do

- **No auto-injection.** Nothing crawls your sessions and pushes
  context into your prompt. Compaction output is markdown; you paste it
  or the MCP client polls. The substrate publishes; consumers pull.
- **No cross-machine sync.** The substrate is local. There is no
  built-in path to share it between machines (and the maintainer
  considers this a feature — see `docs/invariants.md`).
- **No real-time compaction.** The fidelity gate is offline (~15 min
  for 50 QA). The runtime path (`build_compacted_context_with_meta`)
  is fast (<100 ms) but that is only the assembly step, not the
  judge. There is no streaming "as you type" mode.
- **No write surface over MCP.** The three MCP tools are read-only.
  Labeling happens in the FastAPI labeler at `:18890/` via a browser
  UI, not via MCP. This is deliberate — the CAPTCHA anti-drift sidebar
  needs the UI affordance.
- **No multi-user.** The importance mixture is calibrated against
  *your* correction patterns. There is no path to aggregate across
  users; any fidelity numbers are corpus-dependent and not portable.
- **No `/compact` interception.** weighted-compact does not replace
  Claude Code's `/compact`. It runs alongside, produces markdown, and
  the user (or a downstream automation) decides what to do with that
  markdown. There is no harness hook.
- **No ranking guarantee over cheap baselines yet.** At the current
  N=62 under gemma3 judge, the six-signal mixture matches random /
  recency / cosine within ±1 question. If you need a measured edge
  over uniform random over the substrate, the v0.3 ablation grid is
  where that work lives.

---

## Reading the meta dict

`build_compacted_context_with_meta` returns
`(markdown: str, meta: dict)`. The meta dict shape, with concrete
values from a 15-pair session at k_drop=0.5, topic_decay=0.5:

```python
{
    'pairs_total': 14,          # session size minus the source pair
    'pairs_kept': 7,            # what made it into the markdown
    'pairs_dropped': 7,         # pairs_total - pairs_kept
    'input_chars': 23425,       # cost of including everything
    'output_chars': 11991,      # len(markdown)
    'chars_saved': 11434,       # input_chars - output_chars
    'tokens_estimate': 2997,    # output_chars // 4 (rough ~4 chars/token)
    'tokens_saved_estimate': 2858,  # chars_saved // 4
    'compaction_ratio': 0.5119, # output_chars / input_chars
    'signals_top3': [
        ('density',   0.183),   # mean(component × weight) across kept pairs
        ('span_keep', 0.070),   # … same, for span_keep column
        ('label',     0.021),   # … etc, top-3 by mean contribution
    ],
    'ranker': 'static_dict',    # or 'callable_query_aware' for cosine/bm25
}
```

Notes:

- **`tokens_estimate` is `chars // 4`**, not a real tokenizer
  count. It is deliberately rough — the meta dict exists for fast
  budget signal, not billing accuracy. Plug in `tiktoken` if you
  need precision.
- **`signals_top3` degrades silently to `[]`** if `importance.npz`
  is absent or if any kept pair is not in its index. That is
  intentional — the markdown should always come back even when the
  meta is partial.
- **`compaction_ratio = output_chars / input_chars`**: 0.0 if the
  session was empty, otherwise a fraction in [0, 1]. The current
  default k_drop=0.5 typically lands in 0.45–0.55.
- **`ranker = 'callable_query_aware'`** when `scoring` is a function
  (cosine, BM25). For static dicts (importance, density, random,
  recency, REM) the value is `'static_dict'`.

---

## Reproducing on your own substrate

The recipe to reproduce any number in this guide on your own machine:

```bash
# 1) point at your substrate (defaults to $XDG_DATA_HOME/weighted-compact/)
export WEIGHTED_COMPACT_DATA=$HOME/.local/share/weighted-compact

# 2) build the substrate (skip if already built)
weighted-compact bootstrap
weighted-compact importance
weighted-compact rem-pass

# 3) measure disk
du -sh "$WEIGHTED_COMPACT_DATA"
du -h "$WEIGHTED_COMPACT_DATA"/*.npz "$WEIGHTED_COMPACT_DATA"/pairs.jsonl

# 4) measure latency
python -c "
import time
from weighted_compact.recon_qa.context import (
    load_pairs, load_importance, load_topic_map,
    build_compacted_context_with_meta,
)
pairs = load_pairs()
imp = load_importance()
tm = load_topic_map()
src = pairs[0]['pair_idx']
# warm
for _ in range(3):
    build_compacted_context_with_meta(src, pairs, imp, k_drop=0.5,
                                       topic_decay=0.5, topic_map=tm)
N = 20
t0 = time.perf_counter()
for _ in range(N):
    md, meta = build_compacted_context_with_meta(
        src, pairs, imp, k_drop=0.5, topic_decay=0.5, topic_map=tm)
print(f'avg build: {(time.perf_counter()-t0)/N*1000:.1f} ms')
print(meta)
"

# 5) measure first-run bootstrap cost
time weighted-compact bootstrap
```

Your absolute numbers will differ — different corpus size, different
machine, different `~/.claude/projects/` layout. The shape of the
numbers (sub-second runtime path, single-digit second bootstrap,
tens-of-MB substrate per ~500 pairs) should hold.

If something is off by an order of magnitude, that is interesting —
file an issue with the output of `weighted-compact compat --json` and
the bench script above.

---

## Related reading

- [`docs/architecture.md`](architecture.md) — module map, the three-layer
  diagram, substrate file contract
- [`docs/rem-decay.md`](rem-decay.md) — the nightly REM-pass details
- [`docs/mcp-integration.md`](mcp-integration.md) — the MCP surface this
  guide measures from the inside
- [`docs/reconstruction-qa.md`](reconstruction-qa.md) — the harness
  that produces the fidelity numbers cited in §"Without losing quality"
- [`README.md`](../README.md) §"Numbers and their meaning" — the
  ten-row table this guide reads from
