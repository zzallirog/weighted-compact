<div align="center">

# weighted-compact

**A substrate for self-distillation from your own Claude Code sessions.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![v0.2.0-beta.1](https://img.shields.io/badge/release-v0.2.0--beta.1-yellow)](CHANGELOG.md)

</div>

---

This is not a compressor. It is a substrate.

Your Claude Code sessions — the corrections you pushed back on, the numbers
you made the model get right, the paths you typed twice because the first
answer missed — are already sitting in `~/.claude/projects/`. They contain a
record of how you think and what you care about. weighted-compact reads them,
runs them through a small pipeline of measurable modules, and returns a
compact memory shaped by your vocabulary, your corrections, your reasoning.

The model that reads that memory next session is not guessing what you meant.
It is reading a distillation of what you said you meant.

---

## What the pipeline does

Your session files flow through a sequence of modules. Each one is a
defined black box: known input, known output, documented in its own file so
you can open it, inspect it, and replace it independently:

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
        = 0.40 x misstep + 0.25 x density + 0.15 x label
          + 0.20 x span_keep - 0.15 x span_skip + ...
        |
    recon_qa            → judge-yes fraction
        (fidelity gate: can the compacted context answer questions
         about the pair that was hidden from it?)
```

The quality metric driving development is reconstruction fidelity, not
compression ratio. Ratio is easy to game; fidelity is harder.
See [`docs/03-quality-driver.md`](docs/03-quality-driver.md) for why.

---

## Who this is for

You use Claude Code daily. Your sessions are long. Auto-compact occasionally
drops a constraint you set an hour ago — a hostname, an edge case, a flag
you corrected. You would rather have that constraint survive than have a
cleaner-looking summary.

You are also willing to spend twenty minutes labeling pairs. Not because
labeling is fun, but because you want the substrate to reflect your
judgment, not the model's guess about your judgment.

If you want a fully automated compactor that requires no input from you,
weighted-compact is not that.

---

## Substrate, not summary

When auto-compact fires on a Claude Code session, you have no say in the
decision. The model reads your conversation and produces a paragraph. Run it
again and you get a different paragraph.

weighted-compact inverts that. Your sessions become the training corpus.
The substrate stays on your machine. The output is a ranked selection from
your own turns, weighted by signals derived from your own behavior.

The three architectural commitments behind this:

1. **Vectors first.** Every turn becomes an e5-multilingual-small embedding.
   The importance mixture runs on those vectors. If the classifier degrades
   or is missing, the pipeline falls back to the vector baseline — it does
   not break.

2. **Labeling by trigger, not throughput.** The labeler waits for a reason
   to show you a pair: either you flagged it inline during a live session,
   or the classifier is uncertain about it. You label twenty pairs in twenty
   minutes. The substrate grows.

3. **Fidelity as the gate.** Before a weight change ships, run the
   reconstruction-QA loop. Ask whether the compacted context can still
   answer questions about what was hidden from it. If not, the weight change
   lost something.

Full invariants in [`docs/invariants.md`](docs/invariants.md).

---

## The modules, briefly

Each module is a file. Open the file to see the black-box contract
(input / output / how it opens). They are in `weighted_compact/`:

| Module | What it does |
|---|---|
| `extract_pairs.py` | Walk `~/.claude/projects/`, extract (premise, correction) pairs |
| `feature_extract.py` | e5 embeddings over each pair; 3-vector sliding windows |
| `density_features.py` | Content-bearing signal: names, numbers, quoted strings |
| `misstep_score.py` | P(stumble) per pair from the misstep predictor (optional) |
| `span_features.py` | Span-level annotation fractions from inline highlights |
| `topic_segments.py` | Unsupervised topic boundaries via sliding-window cosine cohesion |
| `importance.py` | Compose six signals into a continuous importance score per pair |
| `recon_qa/` | Reconstruction-QA loop — five sub-modules, each its own black box |

The `recon_qa/` package breaks down as:

| Sub-module | Black box |
|---|---|
| `judge.py` | Semantic verdict: question, truth, prediction → yes/no/other |
| `generator.py` | Q&A generation: source pair → list of {q, a_truth} candidates |
| `gate.py` | Difficulty classifier: sort QA entries by informativeness |
| `context.py` | Context assembly: pair scores + k_drop → compacted markdown |
| `fidelity.py` | Eval loop: run all QA entries, return per-entry result dicts |

Full pipeline walkthrough in [`docs/02-pipeline.md`](docs/02-pipeline.md).

An optional inspection tool runs at `http://127.0.0.1:18890/` (`weighted-compact serve`) — a labeler with three views (Quiz / Drift Inspector / Fidelity) for labeling pairs, watching importance drift, and running per-pair fidelity tests; see [`docs/architecture.md`](docs/architecture.md) for the full view breakdown.

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
| Importance mixture (6 signals) | shipped |
| Span-level annotations + topic decay | shipped |
| Drift inspector + iter chain | shipped (`v0.2.0-beta.1`) |
| Per-pair fidelity (conflict / fidelity modes) | shipped (`v0.2.0-beta.1`) |
| Reconstruction-QA loop (W3) | shipped — 50+ baseline accumulating per install |
| `recon_qa/` package split (5 black boxes) | shipped (`v0.2.0-beta.1`) |
| `weighted-compact qa-gate` CLI | shipped (`v0.2.0-beta.1`) |
| W2 — ambient background render | next |
| Cross-session correlation | v0.3 direction |

Beta. Substrate, six-signal mixture, labeler, three inspector views, and
the reconstruction-QA gate are all working end-to-end on a real corpus.
Architectural invariants are locked; the numbers around them are not.
Schema may still shift between beta releases — migration notes ship in
`CHANGELOG.md` when they do.

---

## Results

The numbers below come from a paired ablation on the maintainer's own
substrate. They are honest, not knockout — fidelity is a 4-valued discrete
score on 3 questions per pair, and ties dominate at the current sample size.

**Label-weight ablation, 3 disjoint session corpora, N=57 paired pairs:**

| Metric | Value |
|---|---|
| Mean Δfidelity, `label_weight=0.15` vs `0.0` | **+0.053** |
| 95% paired CI | [−0.004, +0.109] |
| Sign breakdown | 13 positive · 6 negative · 38 ties |
| Per-corpus direction | positive in all three (A +0.100 · B +0.028 · C +0.021) |

Read: keeping the label signal in the importance mixture helps modestly
and consistently. CI just barely crosses zero on the lower bound, so this
is directionally consistent at marginal significance for N=57 — not
noise, not a knockout. Full table and per-corpus rows in
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

- `recon_qa/gate.py` is scaffold — difficulty bucketing computes correctly
  but nothing downstream consumes the buckets (W3 work)
- Per-install ~50-sample baseline accumulation: scores below that
  threshold should be read as illustrative, not calibrated — see
  [`docs/03-quality-driver.md`](docs/03-quality-driver.md#the-50-sample-baseline-problem)
- Misstep predictor AUC 0.665 on the maintainer's corpus — useful as a
  backbone signal, not yet calibrated across users
- No shared community weights file; every install starts from scratch
  and accumulates its own baseline against its own corpus

---

## Where to read further

| File | Topic |
|---|---|
| [`docs/01-substrate.md`](docs/01-substrate.md) | Your sessions as a self-distillation corpus |
| [`docs/02-pipeline.md`](docs/02-pipeline.md) | The modules as black boxes, box by box |
| [`docs/03-quality-driver.md`](docs/03-quality-driver.md) | Why fidelity, not compression ratio |
| [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md) | Two-tier signal economics: cheap regex vs LLM judge |
| [`docs/05-roadmap.md`](docs/05-roadmap.md) | Open items and honest forward look |
| [`docs/concept.md`](docs/concept.md) | Longer-form take on the problem and the bet behind it |
| [`docs/invariants.md`](docs/invariants.md) | The three locked design invariants |
| [`docs/architecture.md`](docs/architecture.md) | Module map and substrate pipeline |
| [`docs/importance-mixture.md`](docs/importance-mixture.md) | Six-signal mixture, weight by weight |
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
