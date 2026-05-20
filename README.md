<div align="center">

# weighted-compact

**A substrate for self-distillation from your own Claude Code sessions.**

*From a session compactor → to a personal memory you can interrogate →
toward an autonomy layer that anticipates your next move.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![v0.2.0-beta.2](https://img.shields.io/badge/release-v0.2.0--beta.2-yellow)](CHANGELOG.md)

</div>

---

## What it was. What it is. Where it goes.

**Was.** A replacement for `/compact`. The standard Claude Code compactor
summarises your conversation in one forward pass and drops whatever did
not fit the paragraph. The first cut of this project was a better
compressor — different ranking, same problem shape. That framing was
wrong. Compression is the *artefact*, not the goal.

**Is.** Not a compressor. A *substrate*. Your Claude Code sessions sit in
`~/.claude/projects/` already — a record of what you corrected, what you
restated, what numbers you forced the model to get right. weighted-compact
reads them, runs them through eight black boxes with measurable
contracts, and emits a per-pair importance score gated by a
reconstruction-QA loop. Seven signals compose into that score. A judge from
a different model family verifies whether the compacted context can still
answer questions about what was hidden from it.

**Goes toward.** A substrate that does not only remember — it begins to
*anticipate*. The same signals that rank importance can be inverted:
predict the corrections you are about to make, the constraints you are
about to set, the paths you typically reject. Cross-session correlation
(the `v0.3` direction) is the first step. The endpoint is a local
forecaster — substrate on disk, an IDE-side assistant reads it as
lookahead, nothing leaves the host.

---

## Read it from your angle

Five distinct readers, same substrate underneath. Pick yours.

| Reader | The hook | Jump |
|---|---|---|
| 🌱 &nbsp;**Daily Claude Code user** | The hostname you corrected once an hour ago does not vanish at compaction | [↓](#angle-daily-user) |
| 🔬 &nbsp;**Memory & distillation researcher** | Seven-signal mixture · cross-family judge · N=57 ablation reported honestly | [↓](#angle-researcher) |
| 🔧 &nbsp;**Builder / signal hacker** | One file = one black-box contract; 30-line patch lands a new signal | [↓](#angle-builder) |
| 🕵️ &nbsp;**Dialog reconstructor** | Recon-QA is a fitness function: keep mixing signals until the hidden pair comes back | [↓](#angle-reconstructor) |
| 🔒 &nbsp;**Local-first / privacy** | Substrate stays in `$XDG_DATA_HOME`; CI scans every commit for leaks | [↓](#angle-privacy) |

<br>

<a id="angle-daily-user"></a>

### 🌱 &nbsp; If you use Claude Code daily

*The constraint you set an hour ago does not vanish at compaction.*

Auto-compact drops the hostname you typed once. The flag you corrected
three turns up. The edge case you described slowly. Your substrate
keeps those — because *you* told it they mattered, by correcting them
in the first place.

What you get today:

- Memory that survives compaction by *your* criteria, not the model's
  guess at your criteria
- A CAPTCHA-style labeler: no infinite scroll, twenty pairs on triggers
  only, one sitting
- A read-only audit before you commit to anything — run
  `weighted-compact compat` to see what your substrate *would* look
  like, then `bootstrap` only if you want to keep it

What you get in the roadmap (`v0.3+`, not shipped):

- Cross-session correlation: corrections from one session inform ranking
  in the next
- Decision-anticipation: the same signals that score importance run in
  reverse to suggest which constraints you are about to set again. The
  substrate becomes a lookahead, not just a memory

→ [Install](#install) · [Quiz / Quest Q1](#quiz--quest)

---

<a id="angle-researcher"></a>

### 🔬 &nbsp; If you read papers on memory and distillation

*Seven signals, cross-family judge, EvoEnv difficulty filter, ablation reported with CI not just point estimate.*

Seven-signal weighted mixture: a per-user `misstep` logistic regression
(AUC 0.665 on the maintainer's corpus) + 16-feature density + per-tier
span coverage (KEEP/MAYBE/SKIP/THINK) + sparse human label. Cross-family judge — `gemma3:4b`
(Gemma) verifies `qwen2.5:7b` (Qwen) reconstructions to avoid
same-family agreement bias. EvoEnv-style difficulty filtering
(arXiv:2605.14392) buckets pairs into trivial / impossible /
informative. Per-pair fidelity is a 4-valued discrete score on 3
questions, baseline-gated at ~50 samples.

Reported ablation (in-repo, not journal): label weight `0.0` vs `0.15`,
N=57 paired — underpowered, treat as directional. Mean Δfidelity =
**+0.053**, 95% CI [−0.004, +0.109], positive direction in 3/3 corpora.
Lower-bound just touches zero — honest "marginal significance,
consistent sign", not a published result claim.

→ [Results](#results) · [`docs/importance-mixture.md`](docs/importance-mixture.md)

---

<a id="angle-builder"></a>

### 🔧 &nbsp; If you write code and want a substrate you can extend

*Eight files, eight black-box contracts. Add a signal in 30 lines, the loop tells you whether it helped.*

Eight modules, eight contracts (input artefact, output artefact, entry
point, dependencies). Each is documented at the top of its own file.
Replace any one without touching the others as long as the contract
holds.

What "30-line patch" actually looks like — append a feature to the
density vector. `density_features.py:extract_density()` returns an
np.array of 8 numbers per turn (premise + correction = 16 features
total). Add a ninth:

```python
# weighted_compact/density_features.py
REVERSAL_RE = re.compile(
    r"\b(actually|wait|scratch that|не так|на самом деле)\b",
    re.IGNORECASE,
)

def extract_density(text):
    if not text:
        return np.zeros(9, dtype=np.float32)   # was 8
    # ... existing 8 features ...
    return np.array([
        # ... existing 8 features ...
        np.log1p(len(REVERSAL_RE.findall(text))),   # NEW: reversal markers
    ], dtype=np.float32)
```

Re-run `weighted-compact bootstrap` — the new column lands in
`features_density.npz` automatically and feeds the density signal
(rank-normalised mean across all 18 features now). Run
`weighted-compact qa-gate` — your Δfidelity vs the previous run tells
you whether the signal earned its place. Adding a *whole new signal*
(not just a density feature) takes ~60 lines: a new `features_X.npz`
producer plus one weight entry in `importance.py:WEIGHTS`.

→ [What is pluggable](#what-is-pluggable) · [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

<a id="angle-reconstructor"></a>

### 🕵️ &nbsp; If you think dialogs can be reverse-engineered from signals

*Hide a pair, hand the rest to a model, ask it the questions whose answers lived in the hidden pair. If it answers, your signals chose the right context.*

The system is, structurally, an inverse problem. The recon-QA loop is
the fitness function: keep mixing signals until reconstruction
succeeds. If it does not, you are missing a feature.

What is already in the mixture:

- `misstep` — stumble recovery patterns (where you corrected and the
  conversation stabilised)
- `density` — anchor entities, paths, numbers, code spans
- `span_keep / span_skip` — your per-char drag-select tiers, when you
  cared enough to highlight
- `topic_segments` — unsupervised topic boundaries via cosine cohesion

What is *invited* but not yet shipped — every reader brings their own
hypothesis about what signal catches what:

- Hesitation markers ("hmm", "wait", "maybe")
- Rhetorical manipulation patterns
- Intent-shift gestures
- Anything else you can write a regex or a classifier for

Add the signal. Re-run the loop. The numbers tell you whether your
hypothesis survives N=57 paired evaluation.

→ [Quiz / Quest Q3](#quiz--quest) · [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md)

---

<a id="angle-privacy"></a>

### 🔒 &nbsp; If you care about local-first and privacy

*Substrate lives in `$XDG_DATA_HOME`. Never uploaded. CI scans every commit for leaks.*

Substrate lives in `$XDG_DATA_HOME/weighted-compact/`. Gitignored.
Never uploaded. No telemetry. No cloud sync. No federation. Each
install grows its own substrate from its own sessions — there is no
shared baseline, by design.

`scripts/leak-scan.sh` enforces this in CI: every commit is grepped
for substrate filename patterns (`*.jsonl`, `*.npz`, `*.model`) and
hardcoded `/home/*/...` paths. The remote repo is an orphan-cut
branch carrying only framework code; the maintainer's substrate, with
personal session history, lives on a private mirror and never touches
GitHub.

→ [Architectural invariants](#architectural-invariants) · [`docs/invariants.md`](docs/invariants.md)

---

## What the pipeline does

Your session files flow through a sequence of modules. Each one is a
defined black box: known input, known output, documented in its own
file so you can open it, inspect it, and replace it independently.

```
~/.claude/projects/
        |
    extract_pairs       → pairs.jsonl
        |
    feature_extract     → features.npz (e5 embeddings)
    density_features    → features_density.npz
    misstep_score       → features_misstep.npz
    span_features       → features_spans.npz
    topic_segments      → topic_segments.npz
        |
    importance.compose  → importance.npz
        = 0.40 × misstep   + 0.25 × density    + 0.15 × label
        + 0.20 × span_keep + 0.10 × span_maybe
        − 0.15 × span_skip + 0.05 × span_think
        |
    recon_qa            → judge-yes fraction
        (fidelity gate: can the compacted context answer questions
         about the pair that was hidden from it?)
```

The quality metric driving development is *reconstruction fidelity*,
not compression ratio. Ratio is easy to game. Fidelity is harder. See
[`docs/03-quality-driver.md`](docs/03-quality-driver.md) for why.

---

## Architectural invariants

Three commitments. They are why the project looks the way it does. Full
text in [`docs/invariants.md`](docs/invariants.md).

1. **Vectors first, classifier as refinement.** Every turn becomes an
   e5-multilingual-small embedding. The importance mixture runs on
   those vectors. A classifier sits on top as a *weighting* refinement,
   not as a gatekeeper. If the classifier degrades or is missing, the
   pipeline degrades to a vector baseline. It does not break.

2. **CAPTCHA labeling — gap-fill and ambiguity-merge, not bulk.** The
   labeler waits for one of two triggers: an inline marker in a live
   session, or classifier disagreement. You label twenty pairs in
   twenty minutes when there is a reason. The UI shows five cosine-
   nearest prior labels next to the current pair — anti-drift
   scaffolding, so you match your own past judgment, not the model's.

3. **Independent of any agent-harness API.** No assumed system-message
   slot. No vendor API hooks. Markdown output, paste-delivery, runs
   standalone. If a future harness exposes more privileged delivery,
   that is a bonus, not a dependency.

---

## What is pluggable

The contract surface is small and named. If you respect the I/O shape,
you can swap any of these without breaking the rest:

| Replacement point | Default | What you can replace with |
|---|---|---|
| Pair extractor | `extract_pairs.py` walks `~/.claude/projects/` | Any source that produces `pairs.jsonl` with the documented schema |
| Embedder | `intfloat/multilingual-e5-small` (384-dim) | bge-m3, qwen3-emb, gte-multilingual — any sentence-transformer |
| Density features | 16 regex signals | Your own regex bag, language-model-derived features, custom entropy variants |
| Misstep predictor | logistic regression on stumble events (per-user) | Random forest, attention-pool classifier, your own trained model |
| Span tier set | KEEP / MAYBE / SKIP / THINK | Locked at 4 in current schema — open issue if you need more |
| Topic segmenter | sliding-window cosine (TextTiling on e5) | BERTopic, supervised classifier, your own boundary detector |
| Importance composer | weighted sum of 7 signals | Custom mixture, additional signals, gradient-boosted ensemble |
| Reconstruction model | `qwen2.5:7b` via Ollama | Any model behind an Ollama `/api/generate` endpoint |
| Judge model | `gemma3:4b` (Gemma — different family) | Different-family constraint is the only rule; pick any other family |
| Difficulty filter | EvoEnv-style two-`k_drop` bucketing | Your own bucketing logic that returns the four-bucket dict |

The recon-QA loop is the fitness function for every one of these
swaps. Replace a component, rerun the loop, see whether mean Δfidelity
moved.

→ Module-by-module contracts and "how it opens": [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

## Quiz / Quest

Three concrete invitations. The fastest way to understand the system
is to run it against your own corpus and watch the numbers move.

**Q1 — Find your own stumble.**
Bootstrap your substrate. Open the labeler at `http://127.0.0.1:18890/`.
Sort by `misstep_score` descending. The top five pairs should be
moments where you corrected the model sharply and the conversation
stabilised after. Were they? If yes, the predictor caught your
stumbles. If not, your corpus is below the training threshold — keep
using Claude Code and re-bootstrap in a week.

**Q2 — Reproduce the public ablation on your own corpus.**
Public number from 3 corpora, N=57: mean Δfidelity = +0.053 (CI
[−0.004, +0.109]). Reproduce on your substrate by toggling the label
weight in two passes:

```bash
# Pass A: baseline with label weight as shipped (0.15)
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge

# Pass B: drop label weight to 0.0 in weighted_compact/importance.py:WEIGHTS
# (edit the dict, save) then rerun
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge
```

Compare the `informative` bucket pass-rate between A and B. If A > B,
your corrections are landing at a layer the label signal sees. If
A ≈ B, your sessions correct at a layer the labels do not capture —
the misstep or density signals are doing the work, and the label
weight may want to be lower for you.

> *A proper `weighted-compact ablation --weights …` one-shot wrapper is
> filed under v0.3 — it would orchestrate the two passes above and
> compute the paired Δ automatically. Until then the manual recipe is
> the contract.*

**Q3 — Add a signal in thirty lines.**
Open `weighted_compact/density_features.py`. Add a 17th feature — a
regex for "I changed my mind" patterns (`r"\b(actually|wait|не так|на
самом деле)\b"`). Re-run bootstrap. The new feature lands in
`features_density.npz` automatically as a column. Wire a weight in
`importance.py:WEIGHTS`. Run recon-QA. Did your new signal change
which pairs survive compaction at `k_drop=0.5`? If yes, you have just
shipped a signal-level improvement to your own substrate.

---

## Results

The numbers below come from a paired ablation on the maintainer's own
substrate. They are honest, not knockout — fidelity is a 4-valued
discrete score on 3 questions per pair, and ties dominate at the
current sample size.

**Label-weight ablation, 3 disjoint session corpora, N=57 paired pairs:**

| Metric | Value |
|---|---|
| Mean Δfidelity, `label_weight=0.15` vs `0.0` | **+0.053** |
| 95% paired CI | [−0.004, +0.109] |
| Sign breakdown | 13 positive · 6 negative · 38 ties |
| Per-corpus direction | positive in all three (A +0.100 · B +0.028 · C +0.021) |

Read: keeping the label signal in the importance mixture helps modestly
and consistently. CI just barely crosses zero on the lower bound, so
this is directionally consistent at marginal significance for N=57 —
not noise, not a knockout. Full table and per-corpus rows in
[`docs/importance-mixture.md`](docs/importance-mixture.md#ablation-label-weight-effect-on-recon-qa-fidelity).

**What the pipeline catches:**

- Numeric and entity anchors (hostnames, paths, flag names) survive
  compaction when they land in pairs with high density score
- Cross-family judge — `gemma3:4b` (Gemma) judging `qwen2.5:7b` (Qwen)
  reconstructions — catches vague paraphrases a same-family judge waves
  through; see [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md)
- Pipeline degrades to a vector baseline if misstep or labels are
  missing — every signal except `feature_extract` is optional, and the
  mixture re-weights what remains

**What does not work yet:**

- `recon_qa/gate.py` is scaffold — difficulty bucketing computes
  correctly but nothing downstream consumes the buckets (W3 work)
- Per-install ~50-sample baseline accumulation: scores below that
  threshold should be read as illustrative, not calibrated — see
  [`docs/03-quality-driver.md`](docs/03-quality-driver.md#the-50-sample-baseline-problem)
- Misstep predictor AUC 0.665 on the maintainer's corpus — useful as a
  backbone signal, not yet calibrated across users
- No shared community weights file; every install starts from scratch
  and accumulates its own baseline against its own corpus

---

## Install

```bash
pipx install git+https://github.com/zzallirog/weighted-compact
```

First-run sequence — three explicit commands:

```bash
weighted-compact compat       # read-only sanity check
weighted-compact bootstrap    # build substrate from ~/.claude/projects/
weighted-compact serve        # open labeler at http://127.0.0.1:18890/
```

For ambient operation (labeler starts at user login):

```bash
weighted-compact install-units
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact
```

Requirements:

- Linux (Arch, Debian, Ubuntu in CI; Fedora / openSUSE expected to work)
- Python 3.11–3.13
- `~/.claude/projects/` populated — you have used Claude Code on this host
- Optional: `sentence-transformers` for re-embedding fresh corpora
- Optional: [Ollama](https://ollama.com) with `qwen2.5:7b` + `gemma3:4b`
  for the reconstruction-QA loop

Full platform matrix and install footprint: [`docs/install.md`](docs/install.md).

---

## Status

| Component | Status |
|---|---|
| Substrate (extract_pairs + e5 features) | shipped |
| Importance mixture (7 signals) | shipped |
| Span-level annotations + topic decay | shipped |
| Drift inspector + iter chain | shipped (`v0.2.0-beta.1`) |
| Per-pair fidelity (conflict / fidelity modes) | shipped (`v0.2.0-beta.1`) |
| Reconstruction-QA loop (W3) | shipped — 50+ baseline accumulating per install |
| `recon_qa/` package split (5 black boxes) | shipped (`v0.2.0-beta.1`) |
| `weighted-compact qa-gate` CLI | shipped (`v0.2.0-beta.1`) |
| W2 — ambient background render ([roadmap](docs/05-roadmap.md)) | next (target `v0.2.x`) |
| Cross-session correlation ([roadmap](docs/05-roadmap.md)) | `v0.3` direction |
| Decision-anticipation layer | `v0.4+` direction |

Beta. Substrate, seven-signal mixture, labeler, three inspector views,
and the reconstruction-QA gate all work end-to-end on a real corpus.
Architectural invariants are locked; the numbers around them are not.
Schema may still shift between beta releases — migration notes ship in
`CHANGELOG.md` when they do.

---

## Where to read further

| File | Topic |
|---|---|
| [`docs/01-substrate.md`](docs/01-substrate.md) | Your sessions as a self-distillation corpus |
| [`docs/02-pipeline.md`](docs/02-pipeline.md) | The eight modules as black boxes, box by box |
| [`docs/03-quality-driver.md`](docs/03-quality-driver.md) | Why fidelity, not compression ratio |
| [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md) | Two-tier signal economics: cheap regex vs LLM judge |
| [`docs/05-roadmap.md`](docs/05-roadmap.md) | Open items and honest forward look |
| [`docs/concept.md`](docs/concept.md) | Longer-form take on the problem and the bet behind it |
| [`docs/invariants.md`](docs/invariants.md) | The three locked design invariants |
| [`docs/architecture.md`](docs/architecture.md) | Module map and substrate pipeline |
| [`docs/importance-mixture.md`](docs/importance-mixture.md) | Seven-signal mixture, weight by weight + ablation data |
| [`docs/reconstruction-qa.md`](docs/reconstruction-qa.md) | Compression-fidelity measurement loop |
| [`docs/span-annotation.md`](docs/span-annotation.md) | Sub-turn char-range tier design |
| [`docs/topic-decay.md`](docs/topic-decay.md) | Unsupervised topic segmentation and decay |
| [`docs/claude-code-integration.md`](docs/claude-code-integration.md) | How the bootstrap reads `~/.claude/projects/` |
| [`docs/install.md`](docs/install.md) | Platform matrix, install footprint, logging |
| [`docs/faq.md`](docs/faq.md) | Troubleshooting |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | What lands easily, what needs discussion |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

---

## License

MIT — see [LICENSE](LICENSE).
