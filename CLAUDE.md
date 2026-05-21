# CLAUDE.md — weighted-compact root

> Navigator for this repo. If you are Claude (or any LLM assistant) reading
> this checkout, read this file first and then jump to the relevant subdir.
> Do not read every file — use the map below.

**Repo version:** v0.2.0-beta.2 (cut 2026-05-20; honest baseline run 2026-05-21)
**Status:** beta. Architectural invariants locked. Numbers tunable.

---

## Substrate framing

weighted-compact is not a compression tool. It is a substrate for
self-distillation from your own Claude Code sessions.

The user's `~/.claude/projects/` already contains a record of every
correction they pushed back on, every number they had to restate, every
constraint the model lost track of. weighted-compact reads those files,
runs them through a pipeline of measurable modules (extract_pairs →
feature_extract → importance mixture → reconstruction-QA), and returns
a compact memory shaped by the user's vocabulary, corrections, and reasoning.

Each module is a defined black box: known input, known output, documented
in its own file. The boxes are replaceable independently. The quality metric
driving development is reconstruction fidelity (can the compacted context
answer questions about what was hidden from it?), not compression ratio.

If you are an LLM reading this repo to answer a question or make a change:
- The framing is "substrate" and "distillation", not "compressor" or "summarizer"
- The pipeline is a sequence of black boxes; treat them as independent
- The locked invariants (vectors-first, CAPTCHA labeling, no-harness-dep)
  are in the section below — do not propose changes that violate them

---

## TL;DR in 30 seconds

- **What this is:** a trainable substrate that compacts Claude Code conversation
  history using **vectors first, classifier as a refinement layer**, with a
  CAPTCHA-style labeler for human-in-the-loop tuning.
- **Architecture:** three independent layers — substrate (`extract_pairs` +
  `feature_extract` over `~/.claude/projects/`) → importance mixture (seven
  signals composed continuously, plus a topic-decay multiplier on top) →
  reconstruction-QA (compression-fidelity gate, default local gemma3 judge
  with Sonnet 4.6 ground-truth calibration runs reported in
  `docs/05-roadmap.md`). Each layer disables cleanly if its dependencies are
  missing.
- **Where it runs:** localhost only, FastAPI on `:18890`, no external services.
- **Privacy:** substrate carries raw conversation text. Stays under
  `$XDG_DATA_HOME/weighted-compact/`, gitignored, never uploaded.

---

## Repo map

```
weighted-compact/
│
├── CLAUDE.md                       ← you are here
│
├── weighted_compact/                package
│   ├── tool.py                      CAPTCHA labeler — FastAPI app + UI
│   ├── recon_qa/                    reconstruction-QA package (5 black boxes)
│   │   ├── __init__.py
│   │   ├── _constants.py            shared config (model names, paths, lazy imports)
│   │   ├── context.py               context assembly: pair scores + k_drop → markdown
│   │   ├── generator.py             Q&A generation: source pair → {q, a_truth} list
│   │   ├── judge.py                 semantic verdict: question + truth + predicted → yes/no/other
│   │   ├── gate.py                  difficulty classifier: QA entries → trivial/informative/impossible
│   │   └── fidelity.py              eval loop: run all QA entries, return per-entry results
│   ├── importance.py                seven-signal mixture
│   ├── extract_pairs.py             session walker (~/.claude/projects/)
│   ├── feature_extract.py           e5 embeddings → features.npz
│   ├── density_features.py          density signal extractor
│   ├── span_features.py             char-fraction matrix from annotations
│   ├── misstep_score.py             P(stumble) per pair (optional, needs misstep substrate)
│   ├── topic_segments.py            unsupervised sliding-window cohesion
│   ├── label_pairs.py               CLI labeler (emergency fallback)
│   ├── auto_label.py                bootstrap labels from inline markers
│   ├── build_queue.py               disagreement + low-conf queue builder
│   ├── train.py                     classifier trainer
│   ├── model.py                     classifier model wrapper
│   ├── eval.py                      eval harness — primary gate
│   ├── config.py                    path resolution (XDG, env override)
│   └── cli.py                       weighted-compact entry point
│
├── docs/                           narrative documentation
├── tests/                          synthetic fixtures only, no real data
├── scripts/                        install-hooks.sh, leak-scan.sh
├── systemd/                        user unit template
└── .github/workflows/              CI: matrix install + smoke
```

---

## Architectural invariants (locked)

These three rules are why the project looks the way it does. Do not change
them without opening an issue and getting explicit sign-off.

### 1. Vector-first, classifier-secondary

Vectors are the primary representation. A classifier sits on top as a
refinement layer for weighting, **not as a gatekeeper**. If the classifier
degrades or is missing, the pipeline degrades gracefully to a vector
baseline (top-K by misstep AUC, density, recency). It does not break.

Implication: multiple classifier candidates are swappable without
redesigning the pipeline. Marker-trained, misstep-derived, density+entropy
hybrid — all are optional improvements over the vector baseline.

### 2. CAPTCHA labeling = gap-fill + ambiguity-merge, NOT bulk

Labeling is targeted intervention, not throughput. Two legitimate triggers:

- **Gap** — an inline marker in a live session auto-queues the surrounding
  turn for canonicalization.
- **Ambiguity** — classifier disagreement or low confidence surfaces the
  pair for human resolution.

Stability principle: **you should match your own classifier over time**, not
optimize toward the model. The UI must show 5 cosine-nearest prior labels
next to the current pair — this is anti-drift scaffolding, not a feature.

### 3. Independent of any agent-harness API

The tool does not assume Anthropic-side delivery privileges (no system-message
slot requirements, no API hooks). Markdown output, paste-delivery, runs
standalone. If a future harness exposes more privileged delivery, that is a
bonus, not an assumption.

---

## Fast paths by question type

### "I want to add a new language to the marker regex"

1. → `weighted_compact/extract_pairs.py` (look for `MARKER_PATTERNS`)
2. → `tests/test_extract_pairs.py` (add fixture)
3. → `docs/claude-code-integration.md` (update language matrix)

### "Why does my classifier disagree with my older labels?"

1. → `docs/span-annotation.md` (anti-drift sidebar explanation)
2. → `weighted_compact/tool.py` (look for `get_anti_drift`)
3. live: open the labeler at `:18890/`, the "anti-drift" sidebar shows
   five cosine-nearest labeled pairs alongside each candidate

### "What signals feed the importance mixture?"

1. → `docs/importance-mixture.md` (seven signals + weights)
2. → `weighted_compact/importance.py` (the compose function)
3. live: open `:18890/` and toggle the ranker between `importance` and
   `density` for A/B comparison.

### "How does the bootstrap find my Claude sessions?"

1. → `docs/claude-code-integration.md`
2. → `weighted_compact/extract_pairs.py` (`SOURCE_DIRS` resolution)
3. CLI: `weighted-compact bootstrap --dry-run`

### "Something is wrong with the pipeline"

1. `weighted-compact compat` — what was detected, what is missing.
2. `journalctl --user -u weighted-compact -f` (if systemd unit enabled).
3. `curl http://127.0.0.1:18890/api/progress` — is the labeler alive?
4. `ls $XDG_DATA_HOME/weighted-compact/` — is the substrate present?

---

## Principles (stable)

- **KISS.** Three similar lines beats a premature abstraction.
- **Three layers, independently disable-able.** Substrate → Importance →
  Reconstruction-QA. Each disables cleanly via config.
- **Substrate is sacred and local.** No upload, no telemetry, no cloud
  sync. Raw conversation text never leaves the host.
- **Goodhart-aware.** If a signal becomes a target, it stops being a
  signal. The mixture is intentionally multi-source so no single metric
  can be gamed without the others noticing.
- **Wrap, don't reimplement.** Where Claude Code already has session
  files on disk, we read them where they are; we do not duplicate.

---

## What lives outside this repo

- **Your substrate** — `$XDG_DATA_HOME/weighted-compact/`. Built from your
  own sessions; never committed; cannot be shared without leaking
  conversation history.
- **The maintainer's internal mirrors with personal substrate** — not
  listed here on purpose. The public remote is an orphan-cut branch
  carrying only framework code.

---

## Self-update protocol

When the framework changes, bump:

- `pyproject.toml` version.
- `CHANGELOG.md` — add a section under `[Unreleased]` or cut a new release.
- This `CLAUDE.md` — if the repo map changes, update the map.

`scripts/leak-scan.sh` is what the CI workflow runs on every push to
catch substrate filename patterns (`*.jsonl`, `*.npz`, `*.model`) and
hardcoded user paths (`/home/*/...`) from sneaking into a commit.
Contributors who want the same check locally before a push can install
it as a git pre-commit hook with `scripts/install-hooks.sh`; for the
maintainer this is unnecessary because CI catches the same things on
arrival. The script and the hook are opt-in, not part of the install
path.
