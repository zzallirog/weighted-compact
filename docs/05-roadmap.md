# 05 — Roadmap

This chapter is the honest forward look — what is solved, what is
scaffolded, what is open research. Read after the pipeline docs to see
where each box sits on that ladder.

---

## What is working now (v0.2.0-beta.1)

- **Substrate pipeline end-to-end.** extract_pairs → e5 embeddings →
  seven-signal importance mixture (plus topic-decay multiplier) →
  compacted context. Runs on a real session corpus. Output is a
  ranked selection from your own turns.

- **Labeler with anti-drift.** Quiz / Drift Inspector / Fidelity views
  over one substrate. All three views write to the same `labels.jsonl`.
  Anti-drift sidebar shows cosine-nearest prior labels to keep your
  decisions consistent over time.

- **Topic segmentation.** Unsupervised sliding-window cohesion on e5
  vectors. Each pair gets a `topic_id`; the compactor penalizes
  cross-topic selections by `topic_decay ^ |Δtopic|`.

- **Reconstruction-QA loop (MVP).** The loop runs. Q&A sets accumulate.
  Fidelity scores are informative after ~50 baseline samples. The
  2026-05-21 honest-baseline run below is the loop's gold-standard
  output under Sonnet 4.6; the earlier label-weight ablation result
  (gemma3 judge, Δ+0.053, CI [−0.004, +0.109]) is now read as a
  cheap-judge proxy result with the gemma3 vs Sonnet κ=0.47 noise
  envelope.

- **recon_qa modularized.** The monolithic `recon_qa.py` is now a
  package with five independent black boxes, each with a documented
  in/out/how-it-opens contract. Replaceable individually.

---

## 2026-05-21 — honest baseline run (substrate snapshot)

The reconstruction-QA loop was run end-to-end with Claude Sonnet 4.6 as
the cross-family judge over the maintainer's substrate (573 pairs, 1718
question-answer triples). Numbers are corpus-specific; methodology is
reproducible on any user's substrate.

**Headline.**

- Sonnet 4.6 with strict vector-AND-anchor policy: **3.8% per-question
  fidelity** when the source pair is hidden from context. Two pairs at
  fidelity 1.0; 518 of 573 at 0.0.
- The honest framing: most pair-specific detail is genuinely lost on
  compaction; what survives is anchor-rich content (specific entities,
  numbers, file paths). The substrate framing holds — this is the floor
  weighted-compact has to lift, not a regression.

**What 4% survives.** Sample yes-verdict patterns from the Sonnet judge:
verbatim matches on short technical identifiers (`compute.slice`,
`ollama.service`, file paths, numeric ranges like `0-3,8-11`),
entity-preserving paraphrase ("3+ repeats → alert"), session-scoped
semantic equivalents where multiple phrasings point at the same
concrete artefact. This is the catalogue that drives W2 verbatim-tier
policy.

**Where the 96% goes.**

- ~40% of failure verdicts: the **generator** itself returned an explicit
  "I don't know" (qwen-7b on this hardware). This is a generator-quality
  bottleneck, not a retrieval failure — switching to a stronger generator
  may recover anchors without changing retrieval at all.
- ~24%: vague paraphrase — context held the topic, anchor dropped.
- ~6%: actual ranking failure (`direction_wrong`) — chain selected wrong
  neighbours.

The smaller-than-expected ranking-failure share is itself a finding: the
debug target for importance scoring is narrower than it looked.

**Cheap-judge calibration.** gemma3:4b as judge against Sonnet 4.6 on the
same 1433 predictions: Cohen κ = 0.469, precision 0.70, recall 0.51, no
"other" verdicts. gemma3 is viable for routine continuous monitoring;
Sonnet remains the ground-truth judge for definitive scoring. The earlier
informal "10× inflation" reading of historical cache mismatch was wrong —
that was pipeline drift between runs, not judge leniency.

**Iter-chain QC verdict (newly known limitation).** Mode calibration on 45
real chains (15 pairs × complement/refine/deepen) showed all three modes
cluster in `[0.95, 1.00]` cosine drift; the hardcoded heuristic ranges
(0.45-0.93) achieved 0/45 in-range. The generator does not differentiate
modes at the mean-vec-cosine level under the current prompt + qwen-7b +
e5-mean-pool combination. Calibrated p10-p90 bands would be too tight
(σ ≈ 0.005-0.012) to be meaningful. The framework needs a redesign step
— stronger generator, explicit mode prompts that reference prior items
by ID, per-Q max-cosine instead of mean-of-means, or accept that modes
don't differentiate and drop the in-range check — before iter-chain QC
can be re-shipped as a useful signal.

**Classifier-as-fidelity-proxy verdict.** A first attempt at training a
predictor for Sonnet fidelity from the engineered substrate features
(e5 + density + misstep + spans, 411 dims, 572 pairs, 54 positive)
landed at AUC ≈ 0.5 across LR / RF / GB. The engineered signals don't
predict the fidelity label as currently formulated; either the sample
is too small for the imbalance, the features were optimised for a
different target (importance ranking, not fidelity prediction), or the
fidelity signal is emergent from retrieval+generator interaction rather
than an intrinsic pair property. Parked; not a current dev target.

---

## What is partially done

### W3 — reconstruction-QA baseline accumulation

The loop is built; the Sonnet baseline above made it measured. Practical
calibration of judge confidence thresholds, anchor-density features, and
the gate difficulty bucketing (`recon_qa/gate.py` — which classifies QA
entries into trivial / informative / impossible / inverted) still needs
the downstream wiring that routes informative pairs into the labeling
queue automatically.

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
