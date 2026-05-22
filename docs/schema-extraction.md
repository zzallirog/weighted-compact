# Schema extraction — third retrieval tier

Status: **v0 proof of concept**, shipped 2026-05-22 with weighted-compact v0.2.0b3.

## What it is

Most "memory" systems for LLMs are flat: chunks of text, retrieved by cosine
similarity. Recurring patterns — your conventions, your environment's quirks,
the same debug arc you walk through every quarter — get retrieved as **raw
chunks** every time. No generalization, no cheap top-tier.

Schema extraction adds a third retrieval tier:

```
schema  →  episode  →  chunk
(cheap)    (mid)       (deep)
```

A **schema** is a generalized rule extracted from N≥k structurally similar
episodes: `(trigger, rule, anti-pattern, stable_since)`. On retrieval,
schemas are checked first — if one fires, you get the rule without diving
into raw text. Episodes and chunks remain available for drill-down.

This is **not** summarization. Not autoencoder. Not hand-written prompt
rules. Schemas are *extracted from your history*, not authored.

## Anti-decay weight (`stability_age`)

Inside a schema, the resolution-anchor's weight **grows** with time of
non-revision. The signal "this rule has stood for 21 days without
contradiction" is itself confidence — anchors that survive get reinforced;
anchors that get contradicted reset to zero stability. This is symmetric
to non-use decay: one is removal, the other is reinforcement of survivors.

Think of it as REM sleep for memory — consolidation paired with pruning.

## The pipeline (4 black boxes)

| Module | Input | Output |
|---|---|---|
| `bank_builder` | Memory + HANDOFF roots | `schema-bank.yaml` (case bank) |
| `synthesizer` | Episode content | `TRIGGER/RULE/ANTI` text |
| `judge` | Generated + expected | `MATCH` / `NEAR` / `MISMATCH` |
| `pipeline` + `report` | Bank + models | Markdown + JSON coverage report |

Each is replaceable independently. The default model for both extraction
and judging is local `gemma3:4b` — swappable via `$WC_SCHEMA_EXTRACT_MODEL`
and `$WC_SCHEMA_JUDGE_MODEL`.

## Quickstart

```bash
# Build case bank from your memory dir (one-time, idempotent)
weighted-compact schema build-bank

# Validate: extract rules from source episodes, judge against bank
weighted-compact schema run

# Or both in one shot
weighted-compact schema all

# Where things live
weighted-compact schema paths
```

The bank lives at `$XDG_DATA_HOME/weighted-compact/schema-bank.yaml` and is
gitignored. Reports go to `$XDG_DATA_HOME/weighted-compact/schema-runs/`.

## First proof run (maintainer corpus)

Initial validation against a hand-curated 20-case bank on the maintainer's
own memory dir:

| Metric | Value |
|---|---|
| **Strict MATCH** | 18/20 = **90.0%** |
| **MATCH+NEAR** (loose) | 20/20 = **100%** |
| Total runtime | ~70 s |
| Model | local `gemma3:4b` |
| Tuning | none — first run |

Ship-gate is **≥60% strict MATCH on case bank**. First-run result clears
it by 30 points on cold-start gemma3:4b with zero prompt tuning, which is
the proof the tier deserves to exist at all.

The two NEAR cases are diagnostic:

- One was a wording difference (`>5000 chunks` vs `pagination 5k chunks`)
  — calibration knob, not a defect.
- One was a multi-rule project file that produced 10 rules where the
  bank expected 1 — empirical confirmation that **one project note can
  encode multiple schemas**, and the cluster-extraction step needs to
  permit multi-rule output, not assume a single top-level rule.

## Architectural fit

The locked invariants of weighted-compact apply unchanged:

1. **Vector-first, classifier-secondary.** Schemas are a refinement layer
   above existing retrieval, not a gatekeeper. If LLM extraction degrades
   or model is unavailable, chunk retrieval keeps working as before.
2. **CAPTCHA-style labeling, not bulk.** Case-bank entries can be
   reviewed/edited by hand — but only for ambiguity resolution, not
   bulk authoring. The build step is unattended.
3. **Independent of any agent harness.** Output is markdown + YAML on
   disk. No delivery-side privilege assumed.

Schema extraction is the fourth tier in the modular pipeline; it composes
with substrate, importance mixture, and reconstruction-QA without
disturbing them.

## What is pluggable

- **Extraction model.** Default `gemma3:4b`. Anything reachable on the
  Ollama API works (qwen2.5, larger gemma, etc.).
- **Judge model.** Same swap; can be a different model from the extractor.
- **Source roots.** `bank_builder.discover_memory_roots()` honors
  `WEIGHTED_COMPACT_CLAUDE_SOURCES` env var (same convention as
  bootstrap).
- **Stability heuristic.** `CANDIDATE_PATTERNS` in `_constants.py` —
  add language-specific markers as needed.

## Honest limitations

- Bank construction relies on LLM-driven extraction over project notes;
  noise filters but is not perfect. Expect a manual pruning pass on
  first build for users with messy memory dirs.
- Ship-gate is currently 60% strict, calibrated for the maintainer's
  corpus. Other users may need adjustment after their first run; the
  number is a starting point, not a fixed constant.
- The "21 days stable" anti-decay weight is currently inferred from
  `stable_since` dates; full contradiction-tracking loop (resetting
  stability on conflict) is roadmap, not v0.
- Bank → schema synthesis (multi-rule per cluster) is roadmap. v0 ships
  validation, the next cut ships cluster→rule extraction proper.

## Roadmap

- **W1 — Active forgetting loop.** Symmetric to extraction: "if I drop
  block K, does reconstruction-QA fidelity fall?" If no, drop. Turns
  importance scoring into self-pruning. (REM sleep analogue.)
- **W2 — Episode-boundary detector.** Replaces today's whole-file
  fallback with proper episode unit (start → struggle → resolution).
- **W3 — Multi-rule cluster output.** Drop the one-rule-per-cluster
  assumption; produce N rules per project file when the file is
  multi-profile.
- **W4 — Continuous `stability_age`.** Today the value comes from
  `stable_since`. Tomorrow it should accumulate per use without
  conflict, reset to zero on contradiction (P-g from the design HANDOFF).

## See also

- `weighted_compact/schema_extraction/` — the code, ~700 LOC across
  six small modules.
- `examples/schema-bank.example.yaml` — template showing the bank format.
- Internal design HANDOFF (private) — postulates P-a..P-g and case-bank
  shape, frozen 2026-05-22.
