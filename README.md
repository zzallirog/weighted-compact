<div align="center">

# weighted-compact

**Trainable context-compaction substrate for Claude Code.**
*Vector-first, classifier-secondary, human-in-the-loop. Replaces `/compact` with reconstruction-from-vectors, not LLM summary.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![v0.0.2](https://img.shields.io/badge/release-v0.0.2-orange)](CHANGELOG.md)
[![status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-red)](CHANGELOG.md)

<sub><i>Local web tool at <code>http://127.0.0.1:18890/</code> — labeler over your own Claude Code sessions, with a reconstruction-QA gate.</i></sub>

</div>

---

Every long Claude Code session eventually fills the context window.

When that happens, the auto-summarizer runs. It reads the whole
transcript fresh and writes a short paragraph that tries to capture
what mattered. Sometimes it works. Sometimes it loses a number you
set yesterday, a path you corrected an hour ago, an edge case a
colleague pointed out on day three. The next turn opens with the
model returning to a default you spent time overriding, because the
line where you overrode it didn't look important enough to keep
word-for-word.

That summarizer is a single LLM pass with no memory of you. Run it
twice on the same conversation and you get two different paragraphs.
The result is unstable, and it is not really yours.

weighted-compact replaces that step with a different one.

It keeps a substrate of your own sessions. Every turn becomes a
vector. An importance score sits over the substrate, composed from
six signals:

- your manual labels on past turns,
- your span-level highlights inside a turn,
- the density of names, numbers, and quotes,
- a per-user predictor for moments where you stopped pushing back,
- recency,
- and a topic-distance penalty so unrelated topics don't compete for space.

When the window fills, the compactor does not write a paragraph. It
selects the spans that score highest, keeps them word-for-word, and
gists the rest.

The score is tunable because only you should decide what to keep. The
labeler runs at `http://127.0.0.1:18890/` and shows you one pair at a
time — usually a pair you flagged with an inline marker like `(mark)`
during a live session, or a pair the classifier is unsure about. You
label twenty in twenty minutes and walk away. The substrate grows.
Future compactions reflect what *you* meant by "this part matters."

That last point is the goal of the project.

Today, when auto-compact runs on a Claude Code session, you have no say
in the decision. It runs when the harness decides, on criteria you
cannot see, and you have to live with the result. weighted-compact
flips that around. The person being compressed also designs the
compression. Your labels, your mixture weights, your reconstruction-QA
scores telling you whether the current settings preserve what you
wanted preserved.

The whole framework is small enough to read in an afternoon. Change
one weight, re-run the QA loop, see the score move. That feedback is
what turns *important* from a vague feeling into a concrete,
measurable thing for the way *you* work.

→ [`docs/concept.md`](docs/concept.md) · [`docs/invariants.md`](docs/invariants.md)

## 01 · The substrate carries the weight, the classifier refines

Every trained classifier eventually misses something. A new way of
saying "no" shows up, the marker regex does not catch it, the labeled
corpus turns out smaller than the variety of moments you actually want
to keep. The classifier slowly degrades. In most pipelines that means
the whole compactor produces worse output until someone notices and
retrains.

Here the classifier is one signal among several, not the deciding
vote. Every turn becomes an e5-multilingual-small embedding and is
stored as a flat substrate. An [importance score](docs/importance-mixture.md)
sits over the substrate, composed from six signals: content density,
your manual labels, your span-level highlights at four tier levels,
the per-user [misstep](https://github.com/zzallirog/misstep) predictor
for moments where you stopped pushing back, recency, and topic
distance. The classifier contributes weight to one of these. Take it
out and the compactor still produces useful top-K selections from the
other five.

This is why Phase 2 of the project did not kill the work. The marker
classifier was trained to F1 = 0.93 on gold labels and then collapsed
to F1 = 0.446 under cross-validation — a textbook case of fitting the
marker itself instead of the underlying signal it was supposed to
proxy. The substrate kept working through that failure. Phase 4
reframed the result as a Goodhart artifact (the marker became the
target the moment the regex defined "important") and moved on. Future
classifiers are swappable; they slot into the same one-of-six spot the
marker-trained one held.

→ [`docs/importance-mixture.md`](docs/importance-mixture.md) ·
[`docs/invariants.md`](docs/invariants.md) (vector-first invariant)

## 02 · Labeling waits for a reason to fire

When labeling becomes a throughput exercise, you stop thinking. Your
hand moves on autopilot; the labels become a function of whatever
regex surfaced the pair, not of what you actually think is worth
keeping. The model trained on those labels picks up on the regex bias
and the whole loop tightens around its initial assumptions every
iteration.

So the labeler waits. It shows one pair at a time, and only fires on
two triggers. The first is an [inline marker](docs/claude-code-integration.md)
you typed during a live session — you wrote `(mark)` or `(подумать)`
in an actual reply, the bootstrap saw the pattern in the JSONL and
queued the surrounding turn for review. Something happened at that
moment that you decided was worth flagging; the labeler asks you to
make the decision explicit. The second is a pair the classifier
disagrees on, or that sits at low confidence, or that was picked to
anchor a quick audit. In every case the pair is on the labeler because
*something specific* needs a human decision. You sit down, look at the
pair, label twenty in twenty minutes, walk away.

The five cosine-nearest prior labels sit in a sidebar to the right of
every pair, tier decisions visible. If you labeled a similar pair as
KEEP three months ago and you are about to label this one as SKIP,
the sidebar shows the contradiction before you commit. The
[principle](docs/invariants.md#2-captcha-labeling--gap-fill--ambiguity-merge-not-bulk)
built into the design is that you should match yourself over time.
The model can adjust to your decisions; your decisions should not be
chasing the model.

<p align="center">
  <img src="docs/img/labeler-help-open.png" alt="weighted-compact labeler with the cheat-sheet expanded — premise + correction visible with KEEP / MAYBE / SKIP / THINK underlines, anti-drift sidebar populated" width="100%">
</p>

<sub><i>Labeler at <code>:18890</code> with the cheat-sheet expanded. Premise on top, your correction below, four tier buttons mapped to <kbd>K</kbd> / <kbd>M</kbd> / <kbd>S</kbd> / <kbd>X</kbd> for the whole-pair verdict. Anti-drift sidebar on the right shows the cosine-nearest prior labeled pairs with their tier decisions. Language switcher top-right — UI ships in English, Russian, and Ukrainian.</i></sub>

→ [`docs/span-annotation.md`](docs/span-annotation.md) ·
[`docs/claude-code-integration.md`](docs/claude-code-integration.md) (marker regex set)

## 03 · Spans, because turns are too coarse

A pair-level keep/drop label decides for the whole turn. But replies
are not uniform — inside a single reply there is usually one paragraph
that carries the actual constraint (a path, a number, a quoted
command, a name) surrounded by reasoning that is worth summarising
but not keeping word-for-word. The pair-level decision either keeps
the filler with the constraint, or drops the constraint with the
filler. Neither is what you would pick if asked.

Drag-selecting a character range inside a turn opens a four-button
popup. <strong style="color:#9ece6a">KEEP</strong> marks a span that
has to survive word-for-word — the names, the numbers, the constraints
the rest of the conversation depends on. <strong style="color:#e0af68">MAYBE</strong>
is the middle tier: keep when budget allows, summarise when it does
not. <strong style="color:#6b7280">SKIP</strong> is the explicit
"drop this" — when you mark a span SKIP the compactor drops it
regardless of how the surrounding mixture scored.
<strong style="color:#b39df0">THINK</strong> is the interesting tier:
it keeps the span and flags it for review later. The future render
layer can show THINK spans with a visual cue so the next session sees
them immediately.

The four tiers feed back into the [importance mixture](docs/importance-mixture.md)
with their own weights. Sparse coverage is fine — most pairs have zero
annotations and the mixture works on the other five signals. Pairs
with annotations get an extra multiplier from whichever tiers are
present. On chatty assistant turns this becomes a token saving of
5–15× once the renderer keeps only KEEP spans word-for-word and
summarises the rest, which is the work scheduled for the W2 render
layer.

→ [`docs/span-annotation.md`](docs/span-annotation.md)

## 04 · A compaction without measurement is wishful thinking

You changed a mixture weight. Did the change help or hurt? Without a
measurement loop the answer is whatever you remember from the last
session — and memory of compression quality across sessions is
unreliable, because you are comparing one vague impression to another.

The reconstruction-QA loop turns weight changes into measurable
results. The mechanism is straightforward. Pick a labeled session.
Hide one of its pairs. Compact the rest under the current mixture.
Pass the compacted context to a local LLM ([Ollama](https://ollama.com)
running `qwen2.5:7b` by default) and ask it to reconstruct the hidden
pair. A second LLM (`gemma3:4b` — a different model family on purpose,
to limit shared bias) judges whether the reconstruction matches the
original. The harness runs across every Q&A in your reconstruction-QA
set and reports a judge-yes percentage plus a stricter substring-pass
percentage as a lower bound.

Raise the [misstep coefficient](docs/importance-mixture.md) by ten
points and re-run. If judge-yes improves on questions about specific
facts, the misstep signal was doing real work. If a previously-answered
question now misses, the weight change cost you that specific fact.
Multi-iteration drift labels — *complement* (new angles) / *refine*
(other phrasings) / *deepen* (consequences) — sit over the candidate
generation step, so you can spot an iteration that is paraphrasing
instead of adding new material.

Both LLMs run on your own Ollama instance; no cloud calls. The Q&A set
lives in `recon_qa_set.jsonl` and grows over time into a regression
suite — facts you have decided must survive any future compaction.

<p align="center">
  <img src="docs/img/reconstruction-tab.png" alt="reconstruction-QA tab with the cheat-sheet expanded and the three control knobs visible" width="100%">
</p>

<sub><i>The reconstruction-QA tab. Build a Q&A set against the source pair (top), then run the eval (bottom) with three knobs: <code>k_drop</code> (what fraction of pairs to hide before asking the question), <code>ranker</code> (importance mixture vs density legacy A/B), <code>topic_decay</code> (cross-topic distance penalty). The cheat-sheet at the top explains each control with the same text the tooltip surfaces on hover.</i></sub>

→ [`docs/reconstruction-qa.md`](docs/reconstruction-qa.md)

## 05 · Sessions hold more than one topic

A long session usually covers more than one topic. Half debugging an
auth flow, half on a database migration. A naive top-K by importance
pulls the highest-scoring spans from both topics into the same
compacted output. Five auth highlights and five migration highlights
end up side by side. The next turn sees both. The model has to guess
which topic you are returning to, and it usually guesses wrong or
hedges.

A topic segmenter runs over the correction embeddings using a
sliding-window cosine cohesion check — the same idea as
[TextTiling](https://aclanthology.org/J97-1003/) applied to e5
vectors instead of TF-IDF. It detects per-session topic boundaries
from the geometry alone, no classifier; each pair receives a
`topic_id` from the cohesion-drop pattern. Nothing to train, nothing
to label.

The compactor then multiplies each candidate's importance by
`topic_decay ^ |Δtopic|`, where `Δtopic` is the number of topic
boundaries between the candidate and the source pair. With the
default `topic_decay = 0.5`, each topic step halves the score. On a
verified multi-topic session that gives a 42% size reduction
(4597 → 2658 chars) at `topic_decay = 0.3` versus disabled, with no
[recon-QA](#04--a-compaction-without-measurement-is-wishful-thinking)
score loss on questions about the current topic. Set
`topic_decay = 1.0` and the compactor reverts to topic-blind
selection.

→ [`docs/topic-decay.md`](docs/topic-decay.md)

## 06 · Your conversations stay on your machine

Your conversation history with Claude Code maps cleanly onto your
life. It carries the names of the people you work with, the addresses
of the services you depend on, the configuration of your home network,
the patterns of how you debug at 2am when something is broken. A
compaction substrate trained on that history inherits the mapping. If
the substrate leaves your machine, those patterns go with it.

So nothing leaves your machine. The substrate is built from
`~/.claude/projects/` on the host where the labeler runs, and lives
under `$XDG_DATA_HOME/weighted-compact/`
([install paths](docs/install.md)). The bootstrap is read-only on the
Claude session files. The installer never asks for an API key. The
labeler binds to `127.0.0.1` by default. There is no telemetry
endpoint to disable because there is no telemetry. The optional
Ollama-backed [reconstruction-QA loop](#04--a-compaction-without-measurement-is-wishful-thinking)
calls `localhost:11434` — point it at a remote service and you have
opted out of the local-only guarantee yourself, but the default holds.

The classifier you train is yours. If you copy the substrate to
another machine it goes with the labels you produced, and only with
those. There is no shared baseline you inherit from a central project,
no community model you contribute back to without realising. Each
install is its own workbench.

→ [`docs/install.md`](docs/install.md) ·
[`docs/invariants.md`](docs/invariants.md) (locked invariants)

---

## Install

```bash
pipx install git+https://github.com/zzallirog/weighted-compact
```

The install puts a `weighted-compact` binary on your `PATH` and pulls in
five hard deps (`fastapi`, `uvicorn`, `pydantic`, `numpy`, `click`). It
does **not** start anything, write anywhere outside the pipx venv, or
register a service.

After install, four things are true:

1. **`weighted-compact compat` runs immediately** as a read-only
   diagnostic — safe to invoke anywhere, never touches state.
2. **No daemon is running.** Nothing listens on port 18890. The labeler
   only comes up when you explicitly run `weighted-compact serve`, or
   enable the systemd user unit (see below).
3. **No substrate exists yet.** `~/.local/share/weighted-compact/` is
   created lazily on first `weighted-compact bootstrap`.
4. **No classifier exists yet.** Once you have labeled twenty pairs,
   `weighted-compact train` fits a baseline. Until then, the importance
   mixture runs on the five non-classifier signals.

A typical first-run sequence is three explicit commands:

```bash
weighted-compact compat       # verify install
weighted-compact bootstrap    # build substrate from ~/.claude/projects/
weighted-compact serve        # launch labeler at http://127.0.0.1:18890/
```

Each command is user-initiated. Nothing in the install path starts a
server, opens a port, or schedules background work.

For **ambient operation** (the labeler auto-starts at user login), opt
into the systemd user unit:

```bash
weighted-compact install-units
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact
xdg-open http://127.0.0.1:18890/
```

This is the only autostart path, and it requires three explicit
commands. `install-units` writes one file under
`~/.config/systemd/user/`; `enable --now` is what actually starts the
labeler. Both are reversible with `systemctl --user disable --now
weighted-compact`.

### Requirements

- Linux. Tested on Arch and Debian-derivatives; CI runs Ubuntu, Arch, Debian.
- Python 3.11–3.13.
- `~/.claude/projects/` — i.e. you have used Claude Code on this host at least
  once. The tool needs sessions to bootstrap from.
- Optional: `sentence-transformers` for re-embedding (the bootstrap reuses
  cached embeddings when present).

### What runs, what doesn't

Right after install:

1. **`weighted-compact compat` works** — read-only diagnostic, prints what was
   detected and what is missing.
2. **No daemon is running.** Nothing listens on `:18890` until you run
   `serve` or enable the systemd unit.
3. **No files have been written under `~/.local/share/weighted-compact/`** —
   the substrate dir is created on first `bootstrap`.

---

## How it works

```
~/.claude/projects/                  → bootstrap reads sessions
   │
   ▼
extract_pairs       → pairs.jsonl    (premise + correction + marker)
feature_extract     → features.npz   (e5 embeddings, 3-vector windows)
density_features    → features_density.npz
misstep_score       → features_misstep.npz   (P(stumble) per pair)
span_features       → features_spans.npz     (annotation char-fraction matrix)
topic_segments      → topic_segments.npz     (per-session topic boundaries)
   │
   ▼
importance.compose  → importance.npz
   = 0.40 × misstep
   + 0.25 × density
   + 0.15 × label
   + 0.20 × span_keep
   + 0.10 × span_maybe
   − 0.15 × span_skip
   + 0.05 × span_think
   │
   ▼
recon_qa.build_compacted_context
   = top-K by importance × decay ^ |Δtopic|
```

The mixture weights are heuristic defaults, surfaced in the UI for tuning.

→ [`docs/architecture.md`](docs/architecture.md)

---

## Status

| Phase | Status |
|---|---|
| Phase 1 — pair extraction + e5 features | ✅ |
| Phase 2 — marker classifier (deprecated, kept for reference) | ✅ failed → reframed |
| Phase 4 — continuous importance mixture (6 signals) | ✅ |
| Phase 4e — span-level annotations + topic decay | ✅ |
| W1 — CAPTCHA labeler UI | ✅ |
| W3 — Reconstruction-QA loop | ✅ MVP (need 50+ baseline) |
| W2 — Ambient background render | ⚪ next |
| Federation patterns (peer-to-peer label exchange) | ⚪ v0.1 direction |

This is `v0.0.01`. Pre-alpha. Expect breaking schema changes until `v0.1.0`.
The architectural invariants are locked; the numbers around them are not.

---

## Where to read further

| File | Topic |
|---|---|
| [`docs/install.md`](docs/install.md) | Platform support, what gets installed, logging, exception matrix |
| [`docs/faq.md`](docs/faq.md) | Common questions, comparisons, troubleshooting |
| [`docs/concept.md`](docs/concept.md) | Why this exists, what it is not |
| [`docs/invariants.md`](docs/invariants.md) | Three locked design invariants |
| [`docs/architecture.md`](docs/architecture.md) | Module map and the substrate pipeline |
| [`docs/importance-mixture.md`](docs/importance-mixture.md) | The six-signal mixture |
| [`docs/span-annotation.md`](docs/span-annotation.md) | Sub-turn char-range tier design |
| [`docs/reconstruction-qa.md`](docs/reconstruction-qa.md) | Compression-fidelity measurement |
| [`docs/topic-decay.md`](docs/topic-decay.md) | Unsupervised topic segmentation + decay |
| [`docs/claude-code-integration.md`](docs/claude-code-integration.md) | How the bootstrap reads `~/.claude/projects/` |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | What is accepted, what needs discussion |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

---

## Help & support

- **Ideas, questions, show-and-tell** —
  [GitHub Discussions](https://github.com/zzallirog/weighted-compact/discussions).
- **Bug you can reproduce** —
  [open an issue](https://github.com/zzallirog/weighted-compact/issues/new).
  Include `weighted-compact compat --json`.
- **PR policy** — see [`CONTRIBUTING.md`](CONTRIBUTING.md). Short version:
  framework PRs welcome, substrate/data PRs no — each install grows its own.

No support SLA. Maintenance is bursty. The repo will go quiet for weeks and
then move in big bumps.

---

## License

MIT — see [LICENSE](LICENSE).
