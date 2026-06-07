# 04 — Cheap grep, expensive judge

This chapter covers the **two-tier signal economics** that sit across
the pipeline — the cheap (regex over a canon vocabulary) vs the
expensive (LLM judge) tiers, and the rule that decides when each one
fires.

Not every signal needs an LLM call. The pipeline runs two tiers of signal
extraction that differ by orders of magnitude in cost. Understanding the
split lets you reason about why certain signals exist, when to trust each
one, and how to spend the LLM budget on the uncertain middle rather than
on cases where a regex would have answered already.

---

## The two tiers

**Tier 1 — regex over a canon vocabulary list (O(1) per pair)**

A set of terms that carry personal meaning in your sessions: project names,
technical terms you use frequently, names, domain-specific shorthand.
The vocab list is yours; it lives in a config file and grows as your
vocabulary solidifies.

When a pair's correction text contains a term from the canon list, it
receives an importance bonus. No model is invoked. No embedding is
computed. The check is a string match or a short regex. The cost is
negligible.

This is the `vocab_canon` signal — a §5.3 POC that captures the idea
that recurring vocabulary in your sessions is a cheap proxy for
personal relevance.

**Tier 2 — LLM judge (one Ollama call per question)**

The reconstruction-QA judge reads a question, the ground-truth answer,
and the reconstructed answer, and returns a verdict. This is the accurate
but expensive signal: it catches paraphrase matches that substring
matching would miss, and it catches wrong answers that look superficially
plausible.

One Ollama call at `localhost:11434` costs roughly 200–800 ms on
`gemma3:4b` depending on hardware. At 50 QA entries and 1 call each,
a full fidelity eval takes 10–40 seconds. That is acceptable for a
deliberate eval run. It is not acceptable as a per-turn filter.

---

## The split in practice

Use tier 1 (grep) for:

- Boosting pairs that mention terms you have explicitly marked as
  canonical — your project names, service addresses, key names
- Quick filtering before fidelity eval: pairs with zero canon hits and
  low density score are less likely to be informative targets
- Cheap warmup of the labeling queue when you have not labeled enough
  for the classifier to have opinions

Use tier 2 (judge) for:

- Evaluating whether the current mixture preserves specific facts
- Gating weight changes: run the judge loop before and after
- Catching reconstruction failures that grep cannot see (paraphrase
  losses, partial recoveries, plausible but wrong answers)

The key rule: **reserve the LLM judge for cases where grep is silent.**
When the grep tier assigns a strong signal — the pair explicitly mentions
a canonical term — the judge tier can be skipped for that pair in
the labeling queue. Save the expensive calls for the uncertain middle.

---

## Why vocab_canon is not just density

The density signal counts names, numbers, and quoted strings in general.
It does not know that "claw" means something specific to your work, or
that "recon_qa" is a module name you keep referring to, or that "ex44"
is a server you should never lose track of.

The vocab_canon list is personal. It does not ship with a default because
there is no canonical vocabulary for everyone. You populate it with the
terms that, when they appear in a correction, reliably mean the pair is
load-bearing for your specific work.

The density signal and vocab_canon are complementary:

- density fires on structural features (any number, any quoted string)
- vocab_canon fires on semantic features (this specific term that you care about)

Both are fast. Both feed into the importance mixture as separate signals.
Neither replaces the other.

---

## The vocab_canon signal — removed

The 5-corpus paired ablation in [`CHANGELOG.md`](../CHANGELOG.md) showed
the flat-bonus variant displaced higher-signal pairs. The signal was
**dropped** from the mixture entirely (marked DROP in the CHANGELOG) —
`vocab_canon` and `CANON_TOKENS` do not exist in the current codebase.
`config.py` has no such key; there is nothing to populate.

The concept (boost pairs whose correction text contains personally
meaningful terms) remains directionally valid. The per-Q canon bonus
variant (boost only when a canon token appears in BOTH the pair and the
question) is queued for a future release; it will be documented here when
it ships.

---

## See also

- [`docs/03-quality-driver.md`](03-quality-driver.md) — why fidelity, not ratio
- [`docs/importance-mixture.md`](importance-mixture.md) — where density and span signals sit in the six-signal mixture
- [`docs/reconstruction-qa.md`](reconstruction-qa.md) — the LLM judge in detail, failure modes, model config
- [`docs/02-pipeline.md`](02-pipeline.md) — the full pipeline, box by box
