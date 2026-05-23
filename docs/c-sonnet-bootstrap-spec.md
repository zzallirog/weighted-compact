# Spec C — Sonnet-first anchor bootstrap

*Adjacent spec: [b-pseudo-labels-spec.md](b-pseudo-labels-spec.md) (detector-derived
pseudo-labels from session structure). Read that in parallel; they compose.*

---

## Why this exists

`extract_pairs.py` finds correction pairs via marker regex — high precision
where the marker fires, low recall on everything else. `auto_label.py`
classifies those pairs with a local rule classifier — fast, cheap, no cloud,
but the rules are heuristics trained on one person's intuitions about what a
correction looks like. Neither produces a *calibrated, reasoned label set*
for the opening corpus.

The consequence: when `gemma3:4b` is used as the cheap judge in the
κ-calibration handshake, the reference it calibrates against is a
label set of uncertain quality. κ=0.469 (measured, 2026-05-21) tells you how
well gemma agrees with *Sonnet* on a held-out pass; it does not tell you how
well auto-labels agree with ground truth.

The user framed it directly: *«заявим что гемма может, но идеальнее
сконструировать первый — сонетом»* — "gemma can do it, but ideally the first
[anchor] should be built with Sonnet." That's what this spec describes.

A one-time Sonnet pass over a representative sample of unlabeled pairs gives
a **high-quality seed label set** — the *anchor set* — that the cheap local
pipeline calibrates against on every subsequent run. The anchor is not
re-run on each session; it is built once and treated as a ground-truth proxy
until the corpus has drifted enough to warrant renewal.

---

## Cost. Front and center.

This step talks to the Anthropic API. It costs money. The CLI makes this
impossible to miss.

### Estimation formula

Per-pair token budget (estimates, not measurements):

- Input: fixed system header (~350 tokens) + pair text (150–600 tokens) = **600–1 250 per pair**
- Output: label + reasoning chain = **80–200 per pair**

Total cost formula for N pairs:

```
cost ≈ N × (avg_input_tokens × sonnet_input_rate
            + avg_output_tokens × sonnet_output_rate)
```

`sonnet_input_rate` and `sonnet_output_rate` are per-million-token prices.
As of 2026-05 they are published at [anthropic.com/api](https://www.anthropic.com/api).
Do not hardcode a number — prices change. The CLI computes the estimate from
actual token counts after pair selection.

The CLI computes this estimate from the actual pairs selected, prints it
before any API call, and halts:

```
Anchor sample: 100 pairs
Estimated tokens: 91 400 input / 13 800 output
Estimated cost: $X.XX (Anthropic pricing 2026-05, claude-sonnet-4-6)
  (verify at https://anthropic.com/api before confirming)

Proceed? [y/N]
```

If the user types anything other than `y`, the run aborts cleanly with exit
code 0. No partial state is written.

The API key is read from `ANTHROPIC_API_KEY` in the environment. The CLI
does not read it from `.env` automatically, does not detect it from shell
config, does not silently fallback to any other credential source. If the
variable is unset at the point where the first API call would be made, the
run fails fast with a clear message before the cost confirmation prompt is
even shown.

---

## Pipeline

Two sub-commands. They are independent but designed to compose.

### Step 1: build the anchor set

```bash
weighted-compact bootstrap --sonnet-first [--n-anchor 100] [--output anchor_labels.jsonl]
```

**What it does:**

1. Reads `pairs.jsonl` from `$XDG_DATA_HOME/weighted-compact/`. If the
   substrate has not been built yet, run `weighted-compact bootstrap` first
   (no flag) to extract pairs and embed them.
2. Applies the sampling strategy (see below) to select N representative pairs.
3. Checks `ANTHROPIC_API_KEY`. If unset, exits with a diagnostic. Does not
   proceed.
4. Assembles a prompt per pair (see prompt shape below). Prints the cost
   estimate. Waits for confirmation.
5. Calls `claude-sonnet-4-6` (model ID pinned, not `latest`) once per pair
   in the selected sample. No batching across pairs in a single call — this
   keeps prompts short, avoids contamination, and makes the per-pair cost
   legible.
6. Parses the response. Expected fields: `label` (`keep` / `maybe` / `skip` /
   `false_positive`), `reasoning` (free text, 1–3 sentences), `confidence`
   (`high` / `med` / `low`).
7. Writes each result to `anchor_labels.jsonl` as it arrives — not as a
   single batch at the end. This enables graceful checkpoint on interruption.
8. On completion, prints a distribution summary and the partial file path if
   any pairs were refused or failed.

**Prompt shape (non-normative):**

```
You are labeling a correction pair from a Claude Code session.
The "premise" is the assistant turn. The "correction" is the user's
response that corrected, refined, or validated it.

Assign ONE label:
  keep          — the correction carries factual or behavioral content worth
                  preserving across sessions (flag, path, number, constraint)
  maybe         — ambiguous; useful but not critical
  skip          — filler, acknowledgement, or system output leakage
  false_positive — the trigger word fired but this is not a correction

Respond as JSON with keys: label, reasoning, confidence.
Do not add any other text.

PREMISE:
{premise_text}

CORRECTION:
{correction_text}
```

The prompt intentionally does not include prior label examples — each pair is
judged independently to avoid contaminating the anchor with a within-Sonnet
consistency bias. The anchor is the reference; it should not be circular.

**Output schema (`anchor_labels.jsonl`):**

Each line:

```json
{
  "pair_idx": 42,
  "session_id": "...",
  "label": "keep",
  "reasoning": "User corrected a specific path and confirmed the hostname. Load-bearing.",
  "confidence": "high",
  "labeled_by": "claude-sonnet-4-6",
  "model_id": "claude-sonnet-4-6",
  "timestamp": "2026-05-23T14:02:11Z"
}
```

Pairs that receive a safety refusal from Sonnet are written with `"label":
null, "refused": true` and a `"refused_reason"` field. They are not silently
dropped — the file records every attempted pair, labeled or not.

---

### Step 2: scale out with gemma

```bash
weighted-compact bootstrap --gemma-scale --from-anchor anchor_labels.jsonl
```

**What it does:**

1. Reads the anchor labels from the specified file. If any anchor pair is
   `refused: true`, it is excluded from the few-shot pool but logged.
2. Reads all unlabeled pairs from `pairs.jsonl` (pairs not covered by either
   the anchor set or any existing `labels.jsonl` entries).
3. For each unlabeled pair, finds the K nearest anchor pairs by cosine
   similarity (default K=5). Uses the existing `features.npz` e5 vectors —
   no re-embed step required.
4. Constructs a few-shot prompt: K anchor examples (correction text + premise
   text + Sonnet's label + reasoning), then the unlabeled pair. Calls
   `gemma3:4b` via the local Ollama endpoint (`:11434`).
5. Appends each result to `labels.jsonl` (the standard substrate label file)
   with `labeled_by: "gemma3:4b-conditioned-on-anchor"` and the K anchor
   indices used as `anchor_refs`.
6. After all pairs are labeled, runs the κ-calibration handshake in anchor
   mode (see Quality contract below). Prints the κ and a brief diagnosis.

This step is fully local. No API calls. The anchor serves as the few-shot
prior that lifts gemma's labeling above its unconditioned baseline.

---

### Composition

The two steps are independent by design:

```bash
# Build the anchor once (costs money, once)
weighted-compact bootstrap --sonnet-first --n-anchor 100

# Scale out on first install
weighted-compact bootstrap --gemma-scale --from-anchor anchor_labels.jsonl

# On subsequent re-runs after new sessions accumulate (no cloud call)
weighted-compact bootstrap
weighted-compact bootstrap --gemma-scale --from-anchor anchor_labels.jsonl
```

The `--sonnet-first` step is intended to be run once, or when the corpus
has accumulated enough new sessions that the anchor is stale (see Open
questions). Subsequent re-runs use `--gemma-scale` only.

---

## Sampling strategy

The anchor sample should cover the surface of the pair space, not just the
high-density or recent center. With N=100, the strategy is:

**Stratified draw across four dimensions:**

| Dimension | Strata | Rationale |
|---|---|---|
| Session age | quartiles (Q1 oldest → Q4 newest) | Avoids recency bias; old sessions may have different correction patterns |
| Density quartile | Q1 (sparse) → Q4 (dense) from `features_density.npz` | Ensures sparse pairs are represented; gemma likely underperforms on them |
| `has_correction_marker` bool | True / False | Pairs without a marker fired differently through `detect_marker`; the anchor should represent both |
| `marker_type` category | `explicit_tag`, `regex_neg`, `regex_pos` | Each type has a different FP rate in `auto_label.py`; the anchor should calibrate all three |

Draw proportionally from the 4 × 4 × 2 × 3 cell grid. If any cell is empty
(e.g., no `explicit_tag` pairs in the oldest-density-Q1 bucket), draw
uniformly from the nearest populated cell. The total draw is N; cells with
fewer than `floor(N / n_cells)` eligible pairs contribute all of them and the
remainder is redistributed.

This gives ~25 pairs per session-age quartile (coverage), ~25 per density
quartile (breadth), and proportional marker-type representation. The overlap
across dimensions is intentional — a pair can be simultaneously old, dense,
and regex_neg.

---

## Quality contract

The κ-calibration handshake that already exists in the recon-QA harness
gets a new mode: **anchor mode**.

Standard mode: judge gemma against Sonnet on a held-out set, report κ.
Anchor mode: judge gemma's `--gemma-scale` output against the anchor labels
on the intersection of pairs that both labeled.

```
weighted-compact qa-gate --calibrate --anchor-labels anchor_labels.jsonl
```

This runs at the end of `--gemma-scale` automatically and prints:

```
Anchor-mode κ calibration
  Anchor pairs used as reference: 100 (refused: 2, excluded)
  Gemma predictions on same pairs: 98
  Cohen κ (anchor vs gemma-conditioned): X.XXX
  Precision / Recall (keep class): X.XX / X.XX
  Agreement by label:
    keep:           XX / XX matched
    maybe:          XX / XX matched
    skip:           XX / XX matched
    false_positive: XX / XX matched
```

The anchor κ is the *primary calibration signal* for the label slot in the
importance mixture going forward. It replaces (or supplements) the standard
Sonnet-vs-gemma κ from the original `docs/importance-mixture.md` ablation.

Do not claim the anchor κ equals the original κ=0.469 — those were measured
under different conditions (unconditioned gemma vs conditioned, different
pair selection). Report both and treat them as distinct measurements.

---

## Failure modes

**Sonnet refuses a pair (safety block or content filter)**

The pair is written to `anchor_labels.jsonl` as:

```json
{"pair_idx": 17, ..., "label": null, "refused": true, "refused_reason": "safety_block"}
```

It is excluded from the few-shot pool in `--gemma-scale`. The user sees a
count of refused pairs in the completion summary. There is no silent drop; the
JSON line is always written.

If > 10 % of the sample is refused, the CLI prints a warning:

```
WARNING: 12/100 pairs refused by Sonnet. Anchor coverage may be insufficient
for some marker types. Consider re-running with a larger --n-anchor or
manually labeling the refused pairs via 'weighted-compact serve'.
```

---

**User exceeds budget mid-run**

If an API call returns a rate-limit or quota error, the run stops immediately.
`anchor_labels.jsonl` contains all pairs labeled up to that point. The run
can be resumed:

```bash
weighted-compact bootstrap --sonnet-first --n-anchor 100 \
  --from-anchor anchor_labels.partial.jsonl
```

With `--from-anchor`, the command reads the partial file, computes which
pairs from the original sample are already labeled, and continues from where
it stopped. The cost estimate shown at confirmation reflects only the
remaining pairs.

---

**API key invalid or missing**

Fail fast. The validity check (a cheap `POST /v1/models` or equivalent
headers-only call) runs before the cost confirmation prompt and before any
pair is processed. If the key is invalid, the run exits with a clear message
and exit code 1. No partial state is written.

---

**Sonnet returns malformed JSON**

The parser retries the parse up to 2 times (with a prompt asking Sonnet to
re-emit only JSON). If parsing still fails, the pair is written as
`"parse_failed": true` with the raw response in a `"raw_response"` field.
These pairs are excluded from the anchor pool and from the κ calibration.

---

## How this differs from b-pseudo-labels-spec

Spec B derives pseudo-labels from *session structure signals*: re-prompt
patterns, negation density, tool-error sequences. It operates on raw
transcript features without calling any LLM. Its output is label-like
annotations derived from observable structure — high recall, calibration
uncertain.

Spec C (this document) derives high-quality labels from Sonnet's *semantic
judgement* on a *sample*. Its output is an anchor — a small, expensive,
high-quality label set that everything else calibrates against.

They are complementary, not alternatives:

| | B (pseudo-labels) | C (anchor) |
|---|---|---|
| Source of signal | Session structure | Sonnet judgement |
| Coverage | Full corpus, every session | Sample (N=100) |
| Cloud cost | None | Explicit, opt-in |
| Use in mixture | Scale cheap labels out | Calibrate gemma |
| Intended cadence | Every re-bootstrap | Once, or on significant corpus drift |

The intended production path: run C once to build the anchor, then run B +
gemma indefinitely for scale. The anchor sits on disk; it does not need to
be re-built unless the corpus has shifted enough that the original sample no
longer represents it.

---

## Privacy invariant alignment

The `--sonnet-first` flag is a hard explicit opt-in. It is not activated by:

- The presence of `ANTHROPIC_API_KEY` in the environment
- Any feature detection or capability check
- A config flag in `~/.config/weighted-compact/`
- A fallback from a failed local step

The flag must be typed. The cost confirmation must be answered. If neither
happens, no text from the substrate leaves the host.

The substrate files (`pairs.jsonl`, `*.npz`) are not uploaded. Only the
*pair text* for the sampled anchor pairs is transmitted — to the Anthropic
API, under the user's own key, in a standard API call. The user is
responsible for their Anthropic account's data handling terms.

The `anchor_labels.jsonl` output file is stored locally under the substrate
directory by default (`$XDG_DATA_HOME/weighted-compact/anchor_labels.jsonl`).
It is gitignored by the framework `.gitignore`. The CI leak scan
(`scripts/leak-scan.sh`) does not scan for this file by name, but the
`.jsonl` extension pattern covers it.

---

## Open questions

- **Anchor staleness.** After N months of new sessions, does the original
  anchor still represent the current corpus? Criteria for re-run are not
  specified here — is session-count delta enough (e.g., anchor is > 6 months
  old and > 200 new sessions have accumulated), or should the trigger be
  drift in the anchor-κ metric over time?

- **OpenRouter routing.** `claude-sonnet-4-6` is the pinned model. Could
  routing through OpenRouter (or another aggregator) reduce cost with a
  cheaper model that achieves comparable κ on the anchor task? This spec
  does not make that call — the anchor's value comes from Sonnet-grade
  judgement, but that is an assertion, not a measurement.

- **Anchor regression against substrate drift.** If the user's session
  patterns shift (new domain, new language mix, different correction
  vocabulary), the anchor labels may become less representative as a
  calibration reference. Is there a cheap drift signal (e.g., cosine distance
  from new pairs to the nearest anchor pair) that could flag when to re-run?

- **Should refused pairs be surfaced in the labeler?** Currently they land in
  `anchor_labels.jsonl` as `refused: true` and are excluded from the
  few-shot pool. An alternative: route them to the CAPTCHA labeler queue
  (`build_queue.py`) so the user can label them manually. This would give
  full anchor coverage at the cost of user time.

- **Multi-user anchor sharing.** The anchor is corpus-specific (it contains
  text from the user's own sessions). Could a sanitized anchor (reasoning
  chains only, no pair text) serve as a transferable prior for other users
  bootstrapping their first corpus? Alignment with the "the substrate carries
  you, not a generalized inference about you" framing is uncertain.

---

## What this does not propose

- Sonnet as a runtime dependency. The anchor is built once; runtime is local.
- Any change to the importance mixture formula. The anchor improves the
  *calibration* of the label signal; it does not change the formula or its
  weights.
- Automatic invocation. Nothing in the install path or systemd units calls
  `--sonnet-first` without explicit user action.
- A claim that Sonnet-anchored labels produce measurably higher fidelity
  than `auto_label.py` labels. That measurement has not been run. This spec
  describes the mechanism; the ablation is filed as future work.
