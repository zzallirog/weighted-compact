# Mechanistic audit of the importance mixture

> **Outcome (2026-06-07).** This audit measured the machine-learned `misstep`
> signal at a held-out AUC of ~0.66–0.70 — barely above chance. That near-chance
> finding is *why* `misstep` was removed from the shipped mixture, which is now
> six signals (density backbone + four span tiers + one optional label). This
> document is retained as the methodology and the finding that drove the removal;
> where it probes `misstep` below, read it as a historical audit of a signal that
> no longer ships in the default mixture.

Applied interpretability methodology, adapted from [_Beyond Behavioural
Trade-Offs: Mechanistic Tracing of Pain-Pleasure Decisions in an
LLM_](https://arxiv.org/pdf/2602.19159) (arXiv 2602.19159), and applied
to weighted-compact's importance scorer (seven signals at the time of this
audit). The goal is to separate two empirical questions that are routinely
conflated when people ask "is your mixture useful?":

- **Representation**: which subset of `importance.npz` is already
  predictable from a single signal? (Probing question.)
- **Causal contribution**: which signal, if removed or scaled, moves the
  reconstruction-fidelity needle? (Intervention question.)

The two answers can disagree. The paper's headline counter-intuitive
finding — that a lexical baseline retained substantial valence signal in
Gemma-2-9B-it — is the same structural shape as our long-standing
observation that **a single recency baseline beats the seven-signal
mixture at N=30–62** (see [bench-vs-claude-mem.md](bench-vs-claude-mem.md)
and the warnings collected in the README). Naming that shape correctly,
rather than treating it as a failure mode, is what this audit does.

---

## Why this methodology transfers

The pain-pleasure paper instruments an LLM's *internal* states —
residual stream activations, attention head outputs, MLP activations.
weighted-compact does not have a frozen network to instrument; it has
**engineered mixture coefficients on top of seven signals computed from
the substrate**. At first glance these are different objects.

They are the same object under the lens that matters here. In both
cases:

1. There is a representation (`importance.npz`, or the residual stream
   feature space) that is claimed to encode a high-level quantity
   (per-pair usefulness, or valence).
2. There is an end-task decision (which pairs to keep under k_drop, or
   which option the LLM picks) that the representation is claimed to
   drive.
3. The naive question is binary ("does the system represent the
   quantity?"). The honest answer is two-part: the *representation* may
   well exist while the *causal* path to decisions may be smaller than
   simple baselines suggest.

The methodology — probing, ablation/intervention, dose-response — is
agnostic to whether the underlying machinery is learned weights or
explicit coefficients. What it requires is:

- A target representation we can read off (here: `importance.npz`).
- A set of input features we can probe (here: the seven signals as
  separate arrays).
- A causal lever we can pull (here: zero-or-scale a coefficient and
  re-run the fidelity gate).
- A baseline that captures the "trivial" signal a sceptic would invoke
  (there: lexical bag-of-words classifier; here: rank-by-recency).

All four hold for weighted-compact's pipeline. The
representation/causal split the paper carved out is therefore directly
re-runnable in our setting, with the same epistemic discipline.

---

## Operational mapping

| Pain-pleasure paper                              | weighted-compact analogue                                      |
| ------------------------------------------------ | -------------------------------------------------------------- |
| Layer-wise linear probing across residual stream | Per-signal linear regression: each single signal → `importance` |
| Lexical baseline (bag-of-words on tokens)        | Recency baseline (rank pairs by position within session)        |
| Activation steering along valence direction      | Coefficient scaling: multiply one signal's weight by α          |
| Patching / ablation of individual heads          | Coefficient ablation: zero a signal, re-fit if needed           |
| Dose-response over ε grids on logit margin       | Coefficient sweep over α grid, measuring Δ reconstruction-fidelity |
| L14 attn_out heaviest causal weight              | Open: which signal carries the biggest fidelity drop on ablation |
| Distributed across multiple heads                | Open: distributed across 7 signals, or 1–2 dominate            |

The right column lists three "open" rows. Phase B and Phase C of this
audit close them, on the maintainer's substrate.

---

## Phase A — Per-signal linear probing

Question this phase answers: how much of `importance.npz` is already
encoded in a single signal, before any mixture is involved? This is a
*representation* question, not a *causal* one.

### Procedure

For each signal in `{misstep, density, span_keep, span_maybe,
span_skip, span_think, topic_decay, recency, cosine, label}`:

```python
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import cross_val_score
import numpy as np

importance = np.load("importance.npz")["importance"]  # shape (N,)
signal_values = load_signal(name)                     # shape (N,)
X = signal_values.reshape(-1, 1)
y = importance
score = cross_val_score(LinearRegression(), X, y, cv=5, scoring="r2").mean()
```

Report a single number per signal — the 5-fold CV R² of `single_signal
→ importance`.

### How to read the result

- **R² ≈ 1.0** on a signal means `importance` is essentially a linear
  transform of that one signal. The mixture's other six signals carry
  zero new variance over this one.
- **R² ≈ 0** means the signal contributes information orthogonal to
  whatever ends up in `importance` — it's either critical-but-suppressed
  in this fit, or it's noise.
- **R² in the middle** is the interesting band: the signal explains
  some of `importance` directly, but not all of it.

The paper's analogous finding — that a lexical baseline retained
substantial valence signal across layers — is the structural shape we
expect for recency in our pipeline, given existing benchmark behavior.
Confirming the magnitude is the cheap part of this audit; it is
expected to take ~10 s of compute on the existing substrate.

---

## Phase B — Coefficient ablation

Question this phase answers: which signals, if removed, drop the
fidelity gate? This is the *causal* question, and answers a question
the probing in Phase A *cannot* answer on its own.

### Procedure

For each signal:

1. Save the current mixture coefficients.
2. Zero the target signal's coefficient. (Optionally re-fit the
   remaining coefficients on held-out data; document the choice in the
   results.)
3. Re-run `weighted-compact qa-gate --signal judge` against
   `recon_qa_set_v2.jsonl` at the same N, seed, and k_drop as the
   baseline measurement.
4. Record the resulting per-Q fidelity. Subtract from baseline to get
   Δfidelity.

```
baseline_full      fidelity = ??.?%
ablated_misstep    fidelity = ??.?%   Δ = -?.?pp
ablated_density    fidelity = ??.?%   Δ = -?.?pp
ablated_recency    fidelity = ??.?%   Δ = -?.?pp
...
```

### How to read the result

- **Large |Δ| on signal X** — X is a heavy causal contributor. Removing
  it costs real fidelity.
- **|Δ| ≈ 0 on signal X with non-trivial Phase A R²** — this is the
  paper's lexical-baseline shape: signal X is *represented* in
  `importance` but the path from `importance` to the fidelity decision
  is mediated by other signals. X is a feature in name only.
- **|Δ| > 0 with R² ≈ 0** — X carries orthogonal causal information
  that the mixture genuinely needs. This is a signal worth tightening
  the coefficient on.

This phase is the most expensive. Per-signal eval is a full
reconstruction-QA loop. Budget ~5 minutes per signal on a local gemma3
judge, plus the cross-family Sonnet re-judge if calibration is in
scope.

---

## Phase C — Dose-response curves

Question this phase answers: how does fidelity respond as you scale a
signal's coefficient up or down — linearly, with a plateau, with a
peak before α=1, with non-monotonic interactions?

### Procedure

Pick the top-3 signals from Phase B by |Δ|. For each, sweep α ∈ {0,
0.25, 0.5, 1.0, 2.0, 4.0} on its coefficient, holding all others
fixed:

```python
baseline_coefs = load_coefficients()
fidelity_grid = {}

for signal in top3:
    fidelity_grid[signal] = {}
    for alpha in [0.0, 0.25, 0.5, 1.0, 2.0, 4.0]:
        coefs = baseline_coefs.copy()
        coefs[signal] *= alpha
        fidelity_grid[signal][alpha] = run_fidelity_eval(coefs)
```

Plot the resulting six points per signal as matplotlib lines, one panel
each.

### How to read the result

- **Monotonic increasing through α=1, still rising at α=4** — signal is
  under-weighted in baseline. Coefficient should go up.
- **Peak at α<1, dropping for higher α** — signal is over-weighted.
  Coefficient should come down. This is a Goodhart shape: more of this
  signal hurts.
- **Flat curve** — coefficient does not matter in this range. Signal is
  effectively a constant.
- **Non-monotonic, multi-modal** — interaction with another signal.
  Joint sweep (signal X × signal Y) is the natural follow-up.

---

## Honest limitations

These limitations are inherited from the paper's own framing and re-stated
to keep the writeup honest.

### Single corpus

The paper used one model (Gemma-2-9B-it) on one set of pain-pleasure
dilemmas. We use one corpus (the maintainer's `~/.claude/projects/`,
~613 pairs at the time of writing) for both probing and ablation. Any
finding here is a finding about that corpus, not a general claim about
weighted-compact pipelines on other substrates. Documenting magnitudes
without claiming universality is the discipline.

### Baseline retains substantial signal — confirmation, not novelty

Recency beating the seven-signal mixture at N=30–62 is the
weighted-compact analogue of the paper's lexical-baseline finding. This
audit can quantify the size of that effect cleanly, but it does not
*remove* it. The output of this audit is a sharper diagnosis, not a
fix; the fix is mixture-coefficient surgery informed by the diagnosis.

### Distributed mechanism null hypothesis

The paper found valence representations distributed across multiple
attention heads. We may find the opposite — that 1–2 signals dominate
both representation and causal contribution. If so, **the mixture
should be simplified, not defended**. Seven-signal architecture is a
design hypothesis, not a load-bearing claim.

### Sample size and statistical power

The probing in Phase A is reasonable on N≥100; ablation in Phase B
benefits from N≥200; dose-response in Phase C is only stable at N≥500.
With current N=613 pairs the audit is in scope across all three phases,
but error bars matter — report bootstrapped confidence intervals on
every reported Δfidelity.

### Cross-family judge calibration

Phase B and Phase C use a fidelity judge (default `gemma3:4b` local).
If the audit's findings are intended for public discussion, replicate
the same eval with a cross-family judge (Sonnet 4.6 via OpenRouter) and
publish both sets of numbers with their disagreement structure
([bench-vs-claude-mem.md](bench-vs-claude-mem.md) §"Sonnet cross-judge"
documents the κ=0.549 baseline). Don't ship Phase B–C findings on
single-judge data.

---

## What this audit is *not*

The pain-pleasure paper carefully refused to claim it had measured
"pain experience" in Gemma-2-9B-it. It claimed to have traced a causal
path between an internal representation and an end-task decision. We
inherit the same discipline.

- This audit does **not** claim that the importance mixture is "what
  the system thinks is important". It claims that the mixture is an
  engineered linear combination whose coefficients can be characterised
  empirically.
- This audit does **not** establish that the seven-signal architecture
  is "the right one". It establishes a method for asking, of any
  candidate architecture, where representation and causal contribution
  agree and where they diverge.
- This audit does **not** survive corpus replacement automatically.
  Findings on the maintainer's substrate are a starting hypothesis for
  what an independent reproducer would expect to see; the reproduction
  is its own evidence.

---

## Reproducibility

### Environment

- Python 3.11+, scikit-learn ≥ 1.5, numpy, matplotlib.
- A working `weighted-compact qa-gate` against `recon_qa_set_v2.jsonl`.
- Local `gemma3:4b` via Ollama or equivalent for the judge.
- (Optional) `OPENROUTER_API_KEY` for cross-family judge in Phase B/C.

### Inputs

- `~/work/weighted-compact/pairs.jsonl` (the substrate).
- `~/work/weighted-compact/importance.npz` (the trained mixture
  output).
- `~/work/weighted-compact/features.npz`,
  `features_density.npz`, `features_spans.npz` (signal arrays; `features_misstep.npz`
  was produced by the now-deleted `misstep_score.py` trainer and is no longer
  part of the shipped pipeline).
- `~/work/weighted-compact/recon_qa_set_v2.jsonl` (QA triples for the
  fidelity gate).

### Commands (placeholder — scripts ship with v0.3)

```bash
# Phase A — per-signal probing
weighted-compact audit probe --signals all --cv 5 \
    --out mechanistic-audit/probing-R2.json

# Phase B — coefficient ablation
weighted-compact audit ablate --signals all --N 613 --seed 42 \
    --k-drop 0.5 --judge gemma3:4b \
    --out mechanistic-audit/ablation-fidelity.json

# Phase C — dose-response on top-3 signals from Phase B
weighted-compact audit sweep --signals top3 \
    --alpha 0,0.25,0.5,1,2,4 \
    --out mechanistic-audit/dose-response.json \
    --plot mechanistic-audit/dose-response.png
```

The three output files plus the plot are the publishable artefact
set. The narrative section below them — paragraph form, not data
dump — is the second deliverable.

### Where results land

- `~/work/weighted-compact/mechanistic-audit/probing-R2.json`
- `~/work/weighted-compact/mechanistic-audit/ablation-fidelity.json`
- `~/work/weighted-compact/mechanistic-audit/dose-response.json`
- `~/work/weighted-compact/mechanistic-audit/dose-response.png`

These are gitignored as the live substrate is; the writeup that lands
in `docs/mechanistic-audit-results.md` (separate file from this one)
contains the numerical summary plus interpretation, version-pinned to
the corpus snapshot.

---

## When to run this audit

| Trigger                                                                  | Run? |
| ------------------------------------------------------------------------ | ---- |
| Discussion turns to "why doesn't your mixture beat recency?"             | Yes  |
| Before any public claim of "the mixture is load-bearing"                 | Yes  |
| Corpus grows past N≥200 with fresh signal coverage                       | Yes  |
| W3 Defect A (misstep shrinkage) is still open                            | No — fix W3 first; audit measures equilibrium |
| N<200 / one signal has <50% coverage                                     | No — statistical power too low |
| The motivation is "to defend the architecture publicly"                  | No — that's post-hoc; run audit only to *update* belief, not justify it |

The last row matters. The audit is a tool for changing your mind, not
for reinforcing a position you've already adopted. If the audit comes
out against the seven-signal mixture, the response is to simplify.

---

## References

- **Primary methodological source.** _Beyond Behavioural Trade-Offs:
  Mechanistic Tracing of Pain-Pleasure Decisions in an LLM_, arXiv
  2602.19159. The three-phase audit structure (probing, ablation,
  dose-response) is borrowed directly from this paper's experimental
  scaffolding.
- **Baseline numbers.** [bench-vs-claude-mem.md](bench-vs-claude-mem.md)
  — N=30/N=62 results, Sonnet cross-judge κ=0.549.
- **Pipeline overview.** [02-pipeline.md](02-pipeline.md) — what the
  signals are, how they're computed, how `importance.npz` is built.
- **Open issues.** Project README §"What's open" — Phase B–C results
  feed directly into v0.3 work.

## Acknowledgements

This document inherits methodology, framing, and limitations discipline
from the pain-pleasure paper above. The application to engineered
mixture coefficients (rather than learned LLM weights) is an
extrapolation by this project's maintainer; any oversimplification of
the original methodology is on us, not the paper's authors. The
audit's findings have not yet been generated; this document specifies
the scaffolding so that the audit, when it runs, produces an artefact
that can be cited and reproduced rather than narrated post-hoc.
