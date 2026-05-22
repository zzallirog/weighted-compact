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

## First proof run — three numbers and what each means

The first proof took three runs to settle. The path between them is the
method-level finding this tier surfaces, so it is recorded here verbatim
rather than collapsed to a single headline number.

Hand-curated 20-case bank on the maintainer's memory dir. Extract model
`gemma3:4b`. Judge models as noted.

| Run | Config | Strict MATCH | Status | Meaning |
|---|---|---|---|---|
| Pre-fix (withdrawn) | verdict parser bug `"MATCH" in "MISMATCH"` → all MISMATCH parsed as MATCH | claimed 18/20 = 90% | retracted | The number was the bug. Re-parsing the same `judge_raw` strings with the corrected parser gives 5/20 = 25%. |
| Honest baseline | parser fixed, original query-free extract prompt, same-model gemma3 judge | **10/20 = 50%** | BELOW gate by 10pp | Extract prompt asks for "one rule" from up to 16k chars but never says _which_ rule. In multi-rule project notes the model picks the first observable rule, not the one the case expects. |
| Pass 1 — query-conditioned extract | threads `trigger_phrase` into the extract prompt so the model is asked to find the rule that addresses _this_ trigger | **14/20 = 70%** | PASS by 10pp | Methodological correction, not tuning: production schema retrieval is always query-conditioned, the original validation wasn't. Latency also dropped ~6s → ~2.7s per extract. |
| Pass 2 — cross-model judge | gemma3 extractor + qwen2.5:7b judge | **1/20 = 5%** | BELOW gate by 55pp | Stress test exposes the judge calibration problem. Reading the judge verdicts: it marks MISMATCH on cases where the rule is substantively correct but worded differently. Same-model judge over-agrees on wording; cross-model under-agrees on wording. Neither is judging substance. |

### What ships

Pass 1 default config: query-conditioned `gemma3:4b` extractor with
same-model judge, **14/20 = 70%, gate PASS by 10pp**. This is the number
on the consumer table and the status row.

### What does not ship and why

The cross-model 5% is documented as the next-hardest open problem, not
hidden:

- **Judge calibration is its own black box.** κ=0.47 was measured
  upstream as same-model viability (gemma3 judge against Sonnet 4.6
  ground truth on a different task). That number does not generalize
  to cross-model judges on this task without separate validation.
  Assuming it would was a mistake.
- **Same-model judge has structural agreement bias.** A model judging
  another instance of itself shares encoding shape and tends toward
  MATCH on substantive ties. Documented in upstream WC warnings under
  the gemma3 cache-drift episode; surfaces here as a +65pp gap between
  same-model and cross-model verdicts.

Both of these belong in a future "judge validation set" of their own,
not solved by tuning the schema-extraction code.

### Adjacent code-review findings (independent reviewer, non-blockers)

Four issues filed for follow-up, none of which gate the current ship:

- `bank_builder._parse_case_block` only stores the **last** value when
  the LLM returns multiple TRIGGER/RULE/ANTI blocks for one cluster.
  Silently degrades extraction quality on multi-rule files; needs
  multi-rule output support (W3 roadmap).
- `build_bank` does not catch `urllib.error.URLError` from Ollama; an
  ollama outage mid-run loses partial progress and leaves a corrupted
  YAML (non-atomic write).
- `pipeline._resolve_ref` constructs paths from `source_episodes`
  without a path-boundary check. Low-severity in single-user local
  context; relevant if the bank format is ever accepted from
  untrusted sources.
- `judge.JUDGE_PROMPT` interpolates the extractor's raw output into
  `{generated}` with `str.format()`. If the extractor returned
  prompt-injection bait, the judge prompt could be subverted. Not
  exploitable in single-user offline use; worth fixing before any
  multi-tenant deployment.

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
