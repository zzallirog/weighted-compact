# 03 — Quality, not compression ratio

The metric driving development is reconstruction fidelity. Not compression
ratio, not token savings, not pair count.

This document explains why ratio is the wrong target and fidelity is the
right one.

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

---

## The ablation result

The label signal contributes `0.15` to the mixture by default. To verify
it was doing real work, the label weight was ablated from `0.15` to `0.0`
on N=57 paired evaluations across three disjoint session corpora:

- Δ judge-yes = **+0.053** (positive: keeping the label signal helps)
- 95 % CI: [−0.004, +0.109]
- Sign agreement: positive in all three corpora (+0.100 / +0.028 / +0.021)
- Paired comparison: 13:6 on non-tied pairs

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
- [`docs/importance-mixture.md`](importance-mixture.md) — the six signals and the ablation data
