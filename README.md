<div align="center">

# weighted-compact

**A substrate for self-distillation from your own Claude Code sessions.**

*Your session is your flow. The substrate keeps it — shaped by what
you corrected along the way.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![v0.2.0-beta.2](https://img.shields.io/badge/release-v0.2.0--beta.2-yellow)](CHANGELOG.md)

</div>

---

## Headline

| Metric (maintainer corpus, 2026-05-21) | Value |
|---|---:|
| Per-question fidelity floor — Claude Sonnet 4.6 judge, 573 pairs / 1718 Q-A triples | **3.8 %** |
| Label-weight ablation — mean Δfidelity (paired, N=57, gemma3 cheap-judge) | **+0.053** |
| Per-corpus sign agreement, 3 disjoint corpora | **3 / 3 positive** |
| Cheap-judge calibration — Cohen κ (gemma3:4b vs Sonnet 4.6, 1433 paired predictions) | **0.469** |

Read each row plain. **Floor** — how much pair-specific detail you lose
when a pair is hidden from context. **Δ** — how much one signal lifts
that floor when you turn it on. **Sign agreement** — whether the lift
holds across separate session corpora, not just one. **κ** — how much
the free local judge agrees with the paid cloud judge, scale-aware.
Numbers are this corpus; the methodology reproduces on yours.

---

## The case

When `/compact` paraphrases your session, the hostname you corrected an
hour ago, the flag you restated three turns up, the edge case you
described slowly — these vanish. The summarizer makes one forward pass
over your conversation with no memory of which parts mattered to *you*.
It guesses.

Your session log already contains the signal. You corrected. You
restated. You highlighted spans with the labeler. The importance of each
turn is not in the model's policy — it is in the substrate of your own
session files. The question is whether that signal can be extracted into
a usable per-pair score without a stronger external model deciding for
you.

Seven signals compose into one importance score: a per-user `misstep`
predictor as backbone, sixteen density features, four span tiers, one
sparse human label, modulated by an unsupervised topic-decay multiplier.
Vectors first; the classifier is a refinement layer, not a gatekeeper.
Reconstruction fidelity — can the compacted context still answer
questions about what was hidden from it — is the metric. Not compression
ratio.

Today: a substrate that remembers what you marked, ranked by signals you
can read and replace. The v0.3 direction is cross-session correlation —
corrections from one session inform ranking in the next, so recurring
constraints accumulate weight instead of resetting at each compact. The
v0.4+ direction is the same signals running in reverse: predict the
corrections you are about to make, the constraints you are about to set,
the paths you typically reject. Substrate on disk; an IDE-side assistant
reads it as lookahead; nothing leaves the host. The substrate becomes a
memory you can interrogate, then a forecaster you can override.

---

## Numbers and their meaning

Eight tests. Four shipped with numbers; the rest with the gap named.
Each result cell has the number on line one and the reading on line two.

| # | Test | Status | Result |
|---|---|---|---|
| 1 | **Ground-truth fidelity** under cross-family judge | shipped | Sonnet 4.6, 573 pairs → 3.8 % per-Q fidelity floor; failure split: ~40 % IDK / ~24 % paraphrase / ~6 % ranking error.<br>*≈96 % of pair-specific detail vanishes when that pair is hidden from context — the absolute starting point, before the mixture does any work.* |
| 2 | **Coefficient ablation** — `label_weight ∈ {0, 0.15}` | shipped, partial sweep | Δ=+0.053, 95 % paired CI [−0.004, +0.109]; per-corpus signs 3 / 3 positive.<br>*Turning the human-label term on raises per-Q fidelity by ≈5 percentage points; CI just crosses zero on the lower bound — direction holds, magnitude borderline.* |
| 3 | **Cross-corpus consistency** — 3 disjoint session corpora | shipped | A +0.100 / B +0.028 / C +0.021; sign breakdown 13 pos · 6 neg · 38 ties.<br>*Three independent maintainer corpora all show positive Δ — the row-2 effect is not an artefact of one session window.* |
| 4 | **Cheap-judge calibration** — gemma3:4b vs Sonnet 4.6 | shipped | κ = 0.469, precision 0.70, recall 0.51, zero "other" verdicts.<br>*The free local judge agrees with the paid cloud judge at "moderate" Landis-Koch level — cheap enough for continuous monitoring, not strict enough for definitive scoring.* |
| 5 | **Anti-baseline** — vs naive `/compact` paraphrase | filed | Comparison harness scheduled; current floor is the open-loop measurement.<br>*No number yet for whether weighted-compact beats Claude Code's native `/compact` — row 1 is the absolute floor, not a delta vs naive selection.* |
| 6 | **Full coefficient grid** — all 7 signal weights | filed | `weighted-compact ablation --weights` one-shot wrapper, v0.3.<br>*Only one of the seven mixture weights has been swept so far; the other six contribute under their heuristic defaults.* |
| 7 | **Compositional / long-run** — fidelity across rolling 48-pair windows | scaffold | `recon_qa/gate.py` computes buckets; downstream routing partial.<br>*Fidelity is scored per pair, not as a function of accumulated history — cannot yet answer "did the last 30 sessions improve or degrade older recall."* |
| 8 | **Multi-user scaling** — reproduction on second corpus | open invitation | Methodology is the contribution; magnitudes are not portable.<br>*If you run on your corpus, the absolute numbers will not match — but the direction of the label-weight effect should reproduce.* |

The label-weight ablation clears the positive bar on two independent
axes: the paired mean (Δ=+0.053) and the per-corpus signs (3/3 positive,
+0.100 / +0.028 / +0.021). The 95 % paired CI [−0.004, +0.109] crosses
zero on the lower bound under the cheap-judge κ=0.47 noise envelope —
that is the qualifier on the magnitude, not a retraction of the
direction.

---

## Pick your door

Same substrate, five readers. The one that names you is yours.

<a id="angle-daily-user"></a>

### 🌱 &nbsp; If you use Claude Code daily

You correct the model. You restate flags. You watch summaries lose the
hostname you typed thirty turns ago. The pain is concrete.

*Would make this irrelevant to you:* your sessions never run long enough
to hit compact, or you reset between threads instead of compacting. The
substrate's whole job kicks in at that boundary.

*The claim:* memory that survives compaction by your criteria, not the
model's guess. Three commands to first run; no daemon required to try it.

*Action:* `pipx install` → `weighted-compact compat` → `bootstrap`. The
labeler opens at `:18890/`. Twenty pairs, twenty minutes, one sitting. The
output is a memory shaped by your corrections.

→ [Install](#install) · [Q1 — find your own stumble](#quiz--quest)

---

<a id="angle-researcher"></a>

### 🔬 &nbsp; If you read papers on memory, distillation, compaction

The framing is *substrate, not policy*: the user's own corrections are the
training signal, extracted from `~/.claude/projects/` rather than from
preference data or RL rollouts. Cross-family judge by contract
(`gemma3:4b` Gemma judges `qwen2.5:7b` Qwen reconstructions), cheap-judge
calibrated against Sonnet 4.6 on identical predictions.

*Would make this irrelevant to you:* you want SOTA on a public benchmark.
This is one corpus, one user, 573 pairs. No CIMemories-style scaling
table; no cross-method shoot-out. Reproduction is invited, not packaged.

*The number:* 3.8 % per-Q fidelity floor (Sonnet) defines the open
question — what raises it. The +0.053 Δ ablation says *one signal* moves
the needle directionally; six more are uncharted.

*Action:* read [`docs/importance-mixture.md`](docs/importance-mixture.md)
for the full ablation table, reproduce on your own corpus, file an issue
with the sign agreement (or disagreement) across your sessions.

→ [Results](#headline) · [`docs/05-roadmap.md`](docs/05-roadmap.md)

---

<a id="angle-builder"></a>

### 🔧 &nbsp; If you write code and want a substrate you can extend

Eight modules, eight black-box contracts (input, output, entry point,
dependencies). Each contract is at the top of its own file. Replace any
single box without touching the rest, as long as the I/O shape holds.

*Would make this irrelevant to you:* you want a finished tool with a
config UI. This is a workbench. The contract surface is named and
documented; the framework around it is light on purpose.

*The number:* ~30 LOC to add a new density feature; ~60 LOC to add a
whole new signal with its own `features_X.npz` producer plus a weight
entry in `importance.py:WEIGHTS`.

*Action:* open `weighted_compact/density_features.py`, append a regex
feature, rerun `bootstrap` + `qa-gate`. The Δfidelity vs the previous
run tells you whether the feature earned its column.

→ [What is pluggable](#what-is-pluggable) · [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

<a id="angle-reconstructor"></a>

### 🕵️ &nbsp; If you think a dialog can be reverse-engineered from signals

Structurally, this is an inverse problem. Hide one pair, hand the rest
to a model, ask it the questions whose answers lived in the hidden pair.
If the model answers, the importance mixture chose the right context. If
not, you are missing a feature.

*Would make this irrelevant to you:* you want compaction that works
out-of-the-box. The reconstructor angle is for people who want to add
a signal and prove it earns its slot.

*The number:* the cross-family judge keeps the loop honest at κ=0.47
against ground truth — high enough to be a useful fitness gate, low
enough that magnitudes don't survive without a sign-agreement check.

*Action:* write a regex or a classifier for a pattern the mixture isn't
catching (hesitation markers, intent-shifts, rhetorical reversals).
Re-run the loop. The numbers tell you whether your hypothesis holds
up under paired evaluation.

→ [Q3 — add a signal in thirty lines](#quiz--quest) · [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md)

---

<a id="angle-privacy"></a>

### 🔒 &nbsp; If you care about local-first and privacy

Substrate lives in `$XDG_DATA_HOME/weighted-compact/`. Gitignored. The
default pipeline runs entirely on Ollama (`qwen2.5:7b` generator +
`gemma3:4b` cheap judge). Zero outbound calls on that path.

*Would make this irrelevant to you:* you noticed Sonnet 4.6 in the
results table. Yes — the calibration in [Headline](#headline) is a
maintainer-side one-time cloud-judge run, explicitly disclosed. Users
who want a Sonnet-grade verdict opt in to their own API key; the
default binds nothing.

*The number:* zero outbound network calls on the default path; one CI
job (`scripts/leak-scan.sh`) scans every commit for substrate filename
patterns and hardcoded personal-home paths. The remote repo is an
orphan-cut branch carrying only framework code; the maintainer's
substrate, with personal session history, lives on a private mirror
and never touches GitHub.

*Action:* run `weighted-compact bootstrap` on an air-gapped host. Read
`docs/invariants.md` for the architectural commitments behind the
guarantee.

→ [Architectural invariants](#architectural-invariants) · [`docs/invariants.md`](docs/invariants.md)

---

## What we crossed

Concepts the project ran into on the way. Each one forced a design
decision — named, so you can see what the choice was.

**Goodhart's law.** Optimize a metric long enough and the metric stops
being a metric. We do not gradient-descent the mixture weights against
the recon-QA fidelity score — the loop is held out as a fitness gate,
not used as a training loss. Mixture weights are heuristic and fixed
before recon-QA runs. The price is that the weights are not optimal;
the price of the alternative is that the score becomes meaningless.

**Cohen's κ and the Landis-Koch scale.** A free local judge is cheap to
run but suspect; a paid cloud judge is the reference but cannot be the
default. Cohen's κ between `gemma3:4b` and Sonnet 4.6 on identical
predictions came in at **0.469** — "moderate" agreement per the
Landis-Koch convention. Usable as a routine cheap proxy; not a
substitute for definitive scoring. We publish κ instead of raw
accuracy so the dispersion is legible.

**Same-family judge agreement.** When the judge model and the generator
model share a backbone or training corpus, they tend to concur unfairly.
The pipeline avoids this by contract: Gemma judges Qwen reconstructions;
no Qwen judging Qwen. The cross-family choice is the architecture, not
a robustness ablation. The cheap-judge κ above measures how much this
default already costs you.

**Sign agreement under a noisy magnitude.** The label-weight ablation
produced Δ=+0.053 with 95 % paired CI [−0.004, +0.109] — the magnitude
crosses zero on the lower bound. The per-corpus signs, separately, were
3 / 3 positive (+0.100 / +0.028 / +0.021). Direction reproduces;
magnitude wobbles. We report both and call the CI a qualifier on the
magnitude, not a retraction of the direction.

**Graceful degradation as contract.** A pipeline that breaks when one
piece fails is brittle. Each signal in the mixture is optional — missing
misstep, the weights re-balance; missing spans, the four tier-terms
collapse to zero. The system degrades to a vector baseline. A
single-classifier gatekeeper design has no analog for this; we picked
the weighted-sum mixture in part for exactly this property.

---

## Honest limitations

- **One corpus, one user.** 573 pairs from the maintainer's Claude Code
  sessions. Magnitudes are not portable; the methodology is what
  reproduces. A scaling story across users does not exist yet — it
  requires others running on their own substrate and reporting back.
  *What this means for you:* your absolute numbers will be different;
  the direction of effects should reproduce, the magnitudes likely will
  not.

- **Per-question fidelity floor is 3.8 %.** Most pair-specific detail is
  genuinely lost on compaction; what survives is anchor-rich content
  (entities, paths, numbers, short verbatim). This is the absolute
  starting position, not a regression.
  *What this means for you:* expect that most fine detail vanishes at
  the compact boundary without intervention. The substrate's job is to
  make what survives match what you marked — not to restore everything.

- **Misstep AUC 0.665 on the maintainer's corpus** — useful as a backbone
  signal, not yet calibrated cross-user.
  *What this means for you:* if your sessions look very different from
  the maintainer's (different language, very short, very technical), the
  misstep signal may be weaker for you. Drop its weight or replace with
  your own predictor.

- **Classifier-as-fidelity-proxy is parked.** A first attempt at training a
  Sonnet-fidelity predictor from 411-dim engineered features landed at
  AUC ≈ 0.5. Either the sample is too small for the imbalance, the
  features are optimised for ranking rather than fidelity prediction, or
  fidelity is emergent from retrieval+generator interaction. Not a
  current dev target.
  *What this means for you:* the substrate runs on the seven-signal
  mixture; the parked classifier you may see in logs is not weighted
  into the score. Nothing user-facing depends on it shipping.

- **Iter-chain mode-distinction QC is parked.** All three modes
  (complement / refine / deepen) cluster in cosine drift `[0.95, 1.00]`
  under the current generator+prompt; calibrated bands would be too
  tight (σ ≈ 0.005-0.012) to be useful.
  *What this means for you:* the iter-chain modes in the inspector look
  usable but their quality signal doesn't differentiate yet. Treat those
  rows as illustrative until the redesign ships.

- **50-sample baseline is the threshold** for individual scores to read
  as calibrated rather than illustrative. Below that, you have an
  importance ranking; you do not yet have a stable fidelity measurement.
  *What this means for you:* if you just installed and the fidelity
  number looks weird, that's expected — keep using Claude Code, let your
  corpus accumulate, re-bootstrap, then trust the number.

- **No comparison number against Anthropic `/compact` yet.** Filed.
  *What this means for you:* we can say what the absolute floor is
  (3.8 %); we cannot yet say "X percentage points better than
  `/compact`". That comparison is the next quality measurement.

---

## What the pipeline does

Session files in. Eight modules score each turn against seven signals.
The most important content rebuilds the compacted context. A judge from
a different model family checks whether the result still answers
questions about what got cut.

The composer formula:

```
importance = 0.40 × misstep + 0.25 × density + 0.15 × label
           + 0.20 × span_keep + 0.10 × span_maybe
           − 0.15 × span_skip + 0.05 × span_think
```

The eight modules are independent black boxes — each documented at the
top of its own file, replaceable individually. The quality metric
driving development is *reconstruction fidelity*, not compression
ratio: ratio is easy to game, fidelity is harder. See
[`docs/03-quality-driver.md`](docs/03-quality-driver.md) for the
argument, [`docs/architecture.md`](docs/architecture.md) for the
module map.

---

## Architectural invariants

Three commitments — full text in [`docs/invariants.md`](docs/invariants.md).

1. **The system won't break when something's missing.** Every turn becomes
   an e5-multilingual-small embedding. The importance mixture runs on
   those vectors. The classifier is a *weighting* layer on top, not a
   gatekeeper. If it degrades or is missing, the pipeline degrades to a
   vector baseline. (Vectors first, classifier as refinement.)

2. **You label only when there's a real reason to.** Two triggers: an
   inline marker in a live session, or classifier disagreement. Twenty
   pairs in one sitting when there is a reason. The UI shows five
   cosine-nearest prior labels alongside the current pair — anti-drift
   scaffolding so you match your own past judgment, not the model's.
   (CAPTCHA labeling: gap-fill + ambiguity-merge, not bulk.)

3. **No Anthropic-side dependencies.** A *harness* is the side that hosts
   an assistant — Claude Code itself, ChatGPT's app, Cursor's IDE plugin.
   Each one decides what system message goes in, what tools are exposed,
   how output gets delivered. weighted-compact assumes none of those
   privileges: it writes Markdown, you paste it, it runs standalone. If a
   future harness exposes more privileged delivery, that is a bonus, not
   a dependency.

---

<a id="what-is-pluggable"></a>

## What is pluggable

Every replacement point is named. Swap a component, rerun the recon-QA
loop, watch Δfidelity — the loop tells you whether your version helped.

| Replacement point | Default | What you can replace with |
|---|---|---|
| Pair extractor | `extract_pairs.py` walks `~/.claude/projects/` | Any source producing `pairs.jsonl` with the documented schema |
| Embedder | `intfloat/multilingual-e5-small` (384-dim) | bge-m3, qwen3-emb, gte-multilingual, any sentence-transformer |
| Density features | 16 regex signals | Your own regex bag, LM-derived features, custom entropy variants |
| Misstep predictor | logistic regression on stumble events (per-user) | Any model returning `P(stumble)` per pair |
| Span tier set | KEEP / MAYBE / SKIP / THINK | Locked at 4 in current schema |
| Topic segmenter | sliding-window cosine on e5 vectors | BERTopic, supervised classifier, your own boundary detector |
| Importance composer | weighted sum of 7 signals | Custom mixture, additional signals, GBM ensemble |
| Reconstruction model | `qwen2.5:7b` via Ollama | Anything behind an Ollama `/api/generate` endpoint |
| Judge model | `gemma3:4b` (Gemma family) | Any other family — distinct-family constraint is the only rule |
| Difficulty filter | EvoEnv-style two-`k_drop` bucketing | Your own bucketer returning the four-bucket dict |

→ Module-by-module contracts: [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

## Quiz / Quest

Three concrete invitations. The fastest way to understand the system is to
run it against your own corpus and watch the numbers move.

**Q1 — Find your own stumble.** Bootstrap. Open the labeler. Sort by
`misstep_score` descending. Top five pairs should be moments where you
corrected the model sharply and the conversation stabilised after. Were
they? If yes, the predictor caught your stumbles. If not, your corpus is
below the training threshold — keep using Claude Code and re-bootstrap
in a week.

**Q2 — Reproduce the label-weight ablation on your own corpus.** Maintainer
corpus, gemma3-judged, N=57 paired: Δ=+0.053, sign positive in 3/3 corpora.
Re-run on yours; the goal is the **sign**, not the magnitude. κ=0.47 cheap-
judge noise will widen your CI; multiple seeds or an opt-in Sonnet pass
tighten it.

```bash
# Pass A: shipped label weight (0.15)
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge

# Pass B: drop to 0.0 in weighted_compact/importance.py:WEIGHTS, save, rerun
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge
```

**Q3 — Add a signal in thirty lines.** Open `density_features.py`. Add a
regex for reversal markers (`r"\b(actually|wait|scratch that)\b"`). Rerun
bootstrap. The new column lands in `features_density.npz` automatically.
Wire a weight in `importance.py:WEIGHTS`. Run recon-QA. Did your new
signal change which pairs survive compaction at `k_drop=0.5`?

---

## Install

```bash
pipx install git+https://github.com/zzallirog/weighted-compact
```

```bash
weighted-compact compat       # read-only sanity check
weighted-compact bootstrap    # build substrate from ~/.claude/projects/
weighted-compact serve        # open labeler at http://127.0.0.1:18890/
```

For ambient operation:

```bash
weighted-compact install-units
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact
```

Requirements: Linux (Arch, Debian, Ubuntu in CI), Python 3.11-3.13,
`~/.claude/projects/` populated. Optional: `sentence-transformers` for
re-embedding; [Ollama](https://ollama.com) with `qwen2.5:7b` +
`gemma3:4b` for the default local recon-QA loop; an Anthropic API key
if you want the Sonnet-grade judge as an opt-in tier (the default binds
nothing to it).

Platform matrix: [`docs/install.md`](docs/install.md).

---

## Status

| Component | Status |
|---|---|
| Memory builder (read sessions, embed, score) | shipped |
| Importance ranker (7-signal mixture) | shipped |
| Labeling UI (CAPTCHA-style, anti-drift) | shipped |
| Fidelity check (cross-family judge, Sonnet baseline measured 2026-05-21) | shipped |
| Baseline comparison harness (6 rankers + mixture, incl. `/compact` sim) | harness shipped; measurement run pending |
| Cross-session memory (corrections accumulate across sessions) | `v0.3` direction |

Beta. Memory builder, ranker, labeler, and fidelity check work
end-to-end on a real corpus. Architectural invariants are locked; the
numbers around them are not. Schema may still shift between beta
releases; migration notes in `CHANGELOG.md`.

Contributor-grade full component table (17 rows): [`docs/status.md`](docs/status.md).

---

## Where to read further

| File | Topic |
|---|---|
| [`docs/01-substrate.md`](docs/01-substrate.md) | Your sessions as a self-distillation corpus |
| [`docs/02-pipeline.md`](docs/02-pipeline.md) | Eight modules as black boxes, box by box |
| [`docs/03-quality-driver.md`](docs/03-quality-driver.md) | Why fidelity, not compression ratio |
| [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md) | Two-tier signal economics: cheap regex vs LLM judge |
| [`docs/05-roadmap.md`](docs/05-roadmap.md) | Open items, honest forward look, 2026-05-21 baseline |
| [`docs/baselines.md`](docs/baselines.md) | Baseline rankers — methodology + how to run the comparison |
| [`docs/concept.md`](docs/concept.md) | Longer-form take on the problem |
| [`docs/invariants.md`](docs/invariants.md) | Three locked design invariants |
| [`docs/architecture.md`](docs/architecture.md) | Module map and substrate pipeline |
| [`docs/importance-mixture.md`](docs/importance-mixture.md) | Seven-signal mixture, weight by weight + ablation data |
| [`docs/reconstruction-qa.md`](docs/reconstruction-qa.md) | Compression-fidelity measurement loop |
| [`docs/span-annotation.md`](docs/span-annotation.md) | Sub-turn char-range tier design |
| [`docs/topic-decay.md`](docs/topic-decay.md) | Unsupervised topic segmentation |
| [`docs/claude-code-integration.md`](docs/claude-code-integration.md) | How the bootstrap reads `~/.claude/projects/` |
| [`docs/install.md`](docs/install.md) | Platform matrix, install footprint |
| [`docs/faq.md`](docs/faq.md) | Troubleshooting |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | What lands easily, what needs discussion |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

---

## License

MIT — see [LICENSE](LICENSE).
