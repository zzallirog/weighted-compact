# 05 — Roadmap

Honest forward look. What is solved, what is scaffolded, what is research.

---

## What is working now (v0.1.0-alpha.2)

- **Substrate pipeline end-to-end.** extract_pairs → e5 embeddings →
  six-signal importance mixture → compacted context. Runs on a real
  session corpus. Output is a ranked selection from your own turns.

- **Labeler with anti-drift.** Quiz / Drift Inspector / Fidelity views
  over one substrate. All three views write to the same `labels.jsonl`.
  Anti-drift sidebar shows cosine-nearest prior labels to keep your
  decisions consistent over time.

- **Topic segmentation.** Unsupervised sliding-window cohesion on e5
  vectors. Each pair gets a `topic_id`; the compactor penalizes
  cross-topic selections by `topic_decay ^ |Δtopic|`.

- **Reconstruction-QA loop (MVP).** The loop runs. Q&A sets accumulate.
  Fidelity scores are informative after ~50 baseline samples.
  The ablation result (label signal Δ+0.053, CI [−0.004, +0.109])
  was produced by this loop.

- **recon_qa modularized.** The monolithic `recon_qa.py` is now a
  package with five independent black boxes, each with a documented
  in/out/how-it-opens contract. Replaceable individually.

---

## What is partially done

### W3 — reconstruction-QA baseline accumulation

The loop is built; the baseline is accumulating. Practical calibration
(iter-chain mode ranges, judge confidence thresholds) requires 50+
baseline samples from your actual corpus. Scores before that threshold
are directional, not definitive.

The gate difficulty bucketing (`recon_qa/gate.py`) is scaffolded: it
correctly classifies QA entries into trivial / informative / impossible /
inverted buckets, but the downstream step — routing informative pairs
into the labeling queue automatically — is not yet wired.

### W2 — ambient background render

The importance scores and compacted context exist. The step that
renders them into a format actually delivered at session start (KEEP
spans verbatim, MAYBE spans as gist, SKIP spans as pointers or dropped)
is not built. This is the render layer. Without it, the substrate
informs the labeler UI but does not yet change what gets delivered to
Claude at session start.

### vocab_canon POC (§5.3)

The mechanism works; the config surface is minimal. See
[`docs/04-grep-vs-judge.md`](04-grep-vs-judge.md). Needs a UI for
surfacing candidate terms from the session corpus.

---

## What is open research

### Matrix importance

The current importance score for a pair is a single float. It does not
capture that a pair may be load-bearing for some questions but not others.

The research direction: model importance as a function of (pair, context)
rather than (pair) alone. A pair `P` is important for the set of questions
`Q` for which the fidelity loss is high when `P` is dropped. This is a
matrix — pair × question — rather than a vector.

Building this in a computationally tractable way, without running an
O(pairs × questions) judge-call budget per compaction, is the hard
part. One candidate approach: cluster pairs by similarity, run
representative coverage tests across clusters, generalize. Not started.

### Cross-session correlation

Pairs that appear in multiple sessions with consistent corrections carry
stronger signal than pairs that appear once. The current pipeline
processes each session independently; there is no cross-session
deduplication or signal aggregation.

The substrate is positioned to support this — `pair_idx` is unique
per ingestion run, but the `session_id` and `turn_idx` fields preserve
provenance. What is missing is the aggregation step that identifies
near-duplicate pairs across sessions and merges their importance signals.

### Persistent eval rig

The recon-QA loop produces a score at a point in time against a fixed
QA set. What is not built is a persistent eval rig that tracks score
trajectories over sessions — answering questions like: did adding the
last 30 sessions to the corpus improve or degrade fidelity on the
existing QA set?

This is straightforward to build (append score-vector to a
`fidelity_history.jsonl` after each full eval run) but has not been
prioritized.

### Federation patterns

Peer-to-peer label exchange — showing how other users labeled the same
pair, without merging their labels into your model — is filed for v0.2.
The Anki model (shared framework, personal substrate, no central server)
is the design target. Not started.

---

## What will not happen

- **Automated mixture optimization.** No gradient descent on mixture
  weights against the recon-QA score. The Goodhart trap runs both
  directions. Manual weight updates with fidelity as the gate is the
  intended loop.

- **Cloud sync or telemetry.** See [`docs/invariants.md`](invariants.md).
  The local-only guarantee is architectural, not a setting.

- **Shared baseline model.** There is no community weights file you
  inherit on install. Each substrate reflects only the sessions and
  labels of the person who ran the bootstrap.

---

## See also

- [`docs/01-substrate.md`](01-substrate.md) — the corpus framing
- [`docs/02-pipeline.md`](02-pipeline.md) — current pipeline state, maturity per box
- [`docs/03-quality-driver.md`](03-quality-driver.md) — why fidelity is the right target
- [`CHANGELOG.md`](../CHANGELOG.md) — version history
- [`docs/invariants.md`](invariants.md) — locked design rules
