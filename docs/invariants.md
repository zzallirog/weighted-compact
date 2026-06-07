# Invariants

Three locked design rules. Do not change them without an issue and explicit
sign-off. Everything else in this project is tunable — these are not.

## 1. Vector-first, classifier-secondary

Vectors are the primary representation — e5-multilingual-small embeddings
over your conversation turns, stored in `features.npz` and indexed by
positional `pair_idx`. The classifier sits on top as a **refinement layer
for weighting**, not as a gatekeeper.

### What this enables

- **Multiple classifier candidates are swappable** without redesigning the
  pipeline. Marker-trained, misstep-derived, density+entropy hybrid — all
  are optional improvements over the vector baseline.
- **The pipeline degrades gracefully** if the classifier fails or is
  missing. Top-K by density and recency still produces a usable
  compaction. Phase 2 of this project failed the marker classifier
  (F1 ceiling of 0.446 vs gate of 1.70×); the substrate kept working.

### What this forbids

- Any code path where "no classifier" means "no compaction."
- Any classifier contract that assumes a single canonical training target.
- Features that bypass the importance mixture and route classifier
  predictions directly to the compactor.

## 2. CAPTCHA labeling = gap-fill + ambiguity-merge, NOT bulk

Labeling is targeted intervention, not throughput. Two legitimate triggers
fire a labeling request:

- **Gap** — an inline marker in your live session (`(mark)`, `(think)`)
  auto-queues the surrounding turn for canonicalization.
- **Ambiguity** — classifier disagreement, low-confidence pairs, or
  audit-anchor pairs surface for human resolution.

You sit down, label twenty pairs, walk away. The tool waits.

### Stability principle

> You should match your own classifier over time.
>
> Labels should be consistent **with themselves over time**, not optimized
> toward the model.

The UI shows the five cosine-nearest prior labels next to the current pair.
This is anti-drift scaffolding, not decoration. If you label a similar pair
differently than you did three months ago, the sidebar tells you.

### What this forbids

- Bulk labeling modes that disable the anti-drift sidebar.
- Active-learning loops that select pairs by expected gradient (turns the
  user into a hill-climber for the model's loss).
- Any "auto-accept high-confidence predictions" mode that produces labels
  the user did not personally sign off on.

## 3. Independent of any agent-harness API

The tool does not assume Anthropic-side or any other vendor-side delivery
privileges. There is no system-message-slot requirement, no API hook, no
runtime injection. Output is plain Markdown; delivery is paste.

### Why

If the harness ever exposes a more privileged delivery mechanism (a context
slot the user controls), that is a bonus. But the substrate must work
without it — both because we don't want to depend on a vendor decision we
can't influence, and because the tool should be useful for any conversation
transcript, not only Claude Code's.

### What this forbids

- Telemetry, "anonymous usage stats," update checkers.
- Any feature that requires an external API key (OpenAI, Anthropic, Tencent
  Cloud, etc.).
- Bundling with closed-source harnesses where the substrate would be
  hostage to a license change.

---

## Future direction

Federation patterns are the direction past alpha. Two candidates that
fit the invariants above:

- **Anki model** — shared framework, personal substrate. No central
  server, no pooled data. Matches invariant 1 cleanly; effectively how
  the project already operates today.
- **Disagreement-as-feature** — peer-to-peer label exchange (Hypercore
  or Veilid) showing how other users labeled the same pair. Optional
  opt-in per pair. Sees others' decisions; never merges them into your
  model.

Explicitly rejected directions:

- **Bootstrap baseline + personal fork** — would mix others' definitions
  of "keep" into your starting weights, violating invariant 2.
- **Federated learning** — requires central aggregation infrastructure
  and a minimum cohort size to make DP noise tractable. Out of scope.
