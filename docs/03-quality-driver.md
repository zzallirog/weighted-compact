# 03 — Quality, not compression ratio

This chapter is about the **recon_qa** box at the end of the pipeline
(see the schema in [README](../README.md)) — the gate that asks whether a
compacted context can still answer questions about a pair that was hidden
from it. The quality metric driving development comes out of that box:
reconstruction fidelity, not compression ratio. Before getting into why,
the shape of what the gate is measuring against — and what falls out of
it for you.

---

## What it grows into

The substrate lives on your machine. Nothing leaves it. The pipeline reads
`~/.claude/projects/`, walks your own session history, and builds a ranked
index over your own turns — weighted by signals derived from your own
behavior across several sessions plus a couple of dozen labeled pairs.

What that becomes, with normal use, is a **searchable vault of your own
reasoning across a scattered spectrum of tasks**. Every constraint you set,
every correction you pushed back on, every variant phrasing you used for
the same idea across three different projects — grouped into a coherent
narrative the next session can read. Not a transcript. A distillation
indexed by relevance.

The next time a small local model needs to talk to you, it does not start
from a generic prior. It reads the vault. It picks up your vocabulary,
your corrections, your phrasing — and shapes its replies against criteria
that came from you, not from its pre-training.

In measured fidelity (judge-yes fraction in the reconstruction-QA loop),
the substrate-weighted path runs roughly **+4 percentage points** above a
vector-only baseline across the band where the loop currently operates
(judge-yes ~0.70–0.99 depending on session and corpus). Modest in absolute
terms, load-bearing in practice — the difference between a context that
loses your hostname and one that keeps it.

This is a direction, not a destination. The weights tune by hand. The
substrate grows session by session. The fidelity gate decides whether each
tuning step counts. What follows is why that gate measures reconstruction,
and not how much was thrown away.

---

## The ratio trap

Compression ratio is easy to optimize. A system that drops everything scores
perfectly on ratio. A system that keeps only dates and names compresses
aggressively and loses everything that matters. Neither is useful, but both
look good on a ratio chart.

More precisely: if you optimize for ratio, ratio becomes the target —
and the moment ratio becomes the target, it stops being a signal. The
mixture will converge toward whatever produces smaller output regardless
of whether that output is useful. This is Goodhart's law applied to
context compaction.

Ratio is a constraint, not a metric. The constraint is: fit the output
into the context budget. Within that constraint, the right question is
whether the output preserves what mattered.

---

## Reconstruction fidelity

Fidelity asks a concrete question: if you hide a pair from the session and
compact the rest, can the compacted context still answer questions about
the hidden pair?

The mechanism:

1. Pick a session. Pick a pair.
2. Remove the pair from the session.
3. Compact the remaining session under the current importance weights.
4. Ask a local LLM to answer questions about the hidden pair using only
   the compacted context.
5. Judge the answers against ground truth using a second LLM (different
   model family — cross-model anti-bias).

Fidelity score is the judge-yes fraction over the questions. If the hidden
pair contained a hostname and the question asks for that hostname, the
score measures whether the compacted context preserved enough context to
recover it.

The two LLMs in step 4 and step 5 come from different families on purpose:
`qwen2.5:7b` reconstructs, `gemma3:4b` judges (see
`recon_qa/_constants.py`). If a single model both produced and graded the
reconstruction, you would be measuring its self-agreement, not fidelity.
Cross-family makes the agreement non-trivial to fake.

This is a harder target than ratio. You cannot cheat it by dropping more
text. The only way to improve it is to keep the right text.

---

## Why tri-value verdict (yes / no / other)

The judge returns one of three values: `yes`, `no`, `other`.

Binary yes/no would force the judge to commit under uncertainty. When the
reconstruction is a plausible paraphrase that is neither clearly correct
nor clearly wrong, binary scoring pushes toward a false yes. `other` is
the honest label for that case.

In practice, the judge-yes fraction is the primary metric, but the
`other` rate is a secondary health indicator. A high `other` rate
signals that the reconstruction model is hedging — often a sign that
the compacted context does not contain enough signal to recover the
hidden content. That is useful information.

---

## The 50-sample baseline problem

The recon-QA loop needs roughly 50 baseline Q&A samples before the
scores stabilize. On a fresh install, the first sessions through the
loop are producing data, not consuming verified output.

In practical terms, that is on the order of a few days of normal Claude
Code use — the loop accumulates samples as you label and as the ambient
background render walks the substrate. There is no shortcut; the counter
moves at the pace of real sessions.

This is not a flaw in the loop. It is a property of any empirical
measurement: you need enough observations before the aggregate is
meaningful. The labeler shows a `baseline: N / 50` counter and dims
confidence indicators below the threshold.

Do not draw conclusions from recon-QA scores in the first day. After
50 samples, the scores become informative. Before that, they are
collecting signal.

---

## How fidelity feeds back into the mixture

It does not feed back automatically.

The recon-QA loop is the gate, not the optimizer. If a weight change
improves fidelity, you update the mixture manually in
`importance.py:WEIGHTS`. There is no automated gradient descent on
the mixture weights.

This is intentional. Automated optimization against recon-QA scores would
close the Goodhart loop in the other direction — the mixture would
converge toward whatever the fidelity loop happens to measure, at the
cost of signals it does not measure. Manual updates keep the human in
the loop and preserve the multi-source independence the mixture was
designed for.

The practical workflow: change one weight, re-run `weighted-compact eval`,
compare the before and after fidelity scores in the UI. If the score
goes up on the questions you care about and does not go down on the ones
you care about more, commit the weight change. If it goes down, revert.

In practice, weight nudges are infrequent once the mixture is roughly
calibrated — the loop is there to catch a regression in the occasional
tuning step, not to drive constant gradient updates. The cadence is
weeks, not minutes.

---

## The ablation result

The label signal contributes `0.15` to the mixture by default. To verify
it was doing real work, the label weight was ablated from `0.15` to `0.0`
on N=57 paired evaluations across three disjoint session corpora:

- Δ judge-yes = **+0.053** (positive: keeping the label signal helps)
- 95 % CI: [−0.004, +0.109]
- Sign agreement: positive in all three corpora (+0.100 / +0.028 / +0.021)
- Paired comparison: 13:6 on non-tied pairs

The three corpora were drawn from the maintainer's own
`~/.claude/projects/` and split by topic — infra/coding sessions, doc
writing, debugging — so they share host and operator but not subject
matter. That is the level of independence the test was designed for: not
strict orthogonality, but enough topic separation that a result agreeing
across all three is unlikely to be a single-corpus artifact.

Marginal significance at this N. Consistent sign across corpora — enough
to keep the weight load-bearing pending a larger corpus. Not enough to
call it definitive. The point is that the question has a measurable
answer, and the answer is in a file you can rerun.

Full ablation details in [`docs/importance-mixture.md`](importance-mixture.md).

---

## See also

- [`docs/02-pipeline.md`](02-pipeline.md) — where fidelity sits in the pipeline
- [`docs/reconstruction-qa.md`](reconstruction-qa.md) — the eval loop in full detail
- [`docs/04-grep-vs-judge.md`](04-grep-vs-judge.md) — two-tier signal economics
- [`docs/importance-mixture.md`](importance-mixture.md) — the seven signals and the ablation data
