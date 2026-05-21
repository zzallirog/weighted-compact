# FAQ

## What is this, in one sentence?

A personal compaction substrate that learns from your Claude Code
sessions to weight context spans, so you can rebuild a working context
from selection-over-vectors instead of an LLM-generated summary.

## How is this different from mem0 / letta / zep / TencentDB-Agent-Memory?

Different problem.

| | They optimize for | weighted-compact optimizes for |
|---|---|---|
| **Goal** | long-term agent memory across sessions | rebuilding *one* session that hit context limit |
| **Operator model** | "the agent" | "the user co-designing how the agent gets compressed" |
| **Distillation** | LLM-generated summaries / Mermaid graphs | top-K weighted selection of *original* spans |
| **Tuning** | hyperparameters, zero-config defaults | continuous mixture of seven signals + human labels |
| **Privacy** | local-first claimed; cloud-friendly | local-only by default; optional opt-in cloud judge for ground-truth calibration runs (see [privacy angle](../README.md#angle-privacy)) |
| **Maturity** | 1.9k★, polished, multi-user | beta, personal workbench |

If you want "agent memory" → use one of the others. If you want "I'm
hitting context limit, summarize feels lossy, give me a tool that lets me
participate" → weighted-compact.

## Is the seven-signal mixture actually better than picking random pairs?

Honest answer: at the present scale and judge, the data does not show
it. The 2026-05-21 baseline run (N=62, k_drop=0.5, `gemma3:4b` judge,
maintainer corpus) put the mixture at **11.3 %** per-Q fidelity and
random selection at **12.9 %** — within one question of each other,
inside the κ=0.47 cheap-judge noise envelope. Recency, cosine retrieval
(e5), density-only and BM25 all land in the same ±1-question band.

What the data **does** show is an ~8-percentage-point gap between any
structured selection method (mixture, random, recency, cosine, density,
BM25) and a one-pass LLM summary analog (qwen-summarized `/compact` =
3.2 %). That gap is the strongest signal in the baseline table.

So: at this N under this judge, the *architecture* (selecting pairs over
summarising the dialogue) is shown to be the right call; the *specific
weighting* of the seven signals is not yet shown to beat a uniform
random ranker. The pre-registered narrative bar (mixture beats cheap
baselines by ≥0.05 absolute) is not met by this measurement.

The open paths to resolve are filed under `v0.3` — Sonnet re-judge on
the same 62-entry set, a larger QA set (200–500), and a coefficient
grid ablation across all seven weights. Methodology and harness in
[`docs/baselines.md`](baselines.md).

## Why doesn't it just call an LLM to summarize?

Because LLM summaries on the same conversation, run twice, return
different summaries. The compactor's job is to be **predictable** — same
session, same weights, same compaction. A vector-weighted top-K
selection has that property. An LLM forward pass does not.

(There is an optional Ollama-backed recon-QA evaluator that *does* call
an LLM, but only to score the compaction, never to produce it. The
compaction itself is deterministic.)

## Why human-in-the-loop? Can't this be automated?

It can be partially automated. The Phase 4 mixture weights already are —
seven independent signals compose continuously, no hand-labels needed for
the basic case.

But: the *direction* of the weighting is a personal choice. What you
consider "load-bearing" in a debugging session is different from what
you consider load-bearing in a design session. Your colleague's
priorities differ from yours. A fully automated compactor either picks a
default that fits no one, or asks for your preferences — which is
exactly what the labeler does.

See [`docs/invariants.md`](invariants.md) for the locked design rule.

## How long does the first labeling session take?

About 30 minutes to label 50 pairs, which is enough for the recon-QA
loop to start producing stable scores. After that you can label in
five-pair bursts whenever you have a moment.

Walking away with 50 labels is normal. The tool is designed for that —
labels are saved per-keystroke, you can resume any time.

## Does it work with non-Claude-Code transcripts?

The pair extractor (`extract_pairs.py`) is specific to Claude Code's
JSONL format, but the substrate downstream is format-agnostic. To ingest
a different transcript format, write a small shim that emits the same
pair shape:

```jsonl
{"session_id": "...", "correction_uuid": "...", "premise_uuid": "...", "correction_text": "...", "premise_text": "...", "marker_type": "...", "marker_match": "...", "tier_hint": "keep|maybe|skip|null"}
```

Then `weighted_compact.feature_extract.main()` will pick up the new
pairs. PRs for other transcript shapes (Cursor sessions, GitHub Copilot
chat logs, etc.) welcome.

## Will my labels leak if I push my fork?

The `.gitignore` blocks `*.jsonl`, `*.npz`, `*.model`, and `*.bak.*`
patterns at the repo root. The pre-commit hook (`scripts/install-hooks.sh`)
runs a leak-scan over staged diffs that also catches the same patterns
plus a configurable list of personal identifiers in
`scripts/leak-scan.sh:PERSONAL_PATTERNS`.

Both layers are defense in depth. As long as you don't override them,
the substrate cannot enter a commit. To verify a fork:

```bash
bash scripts/leak-scan.sh
```

If you find a leak path that the defaults miss, file an issue.

## Can multiple users share a substrate?

No, and this is intentional. Substrate is built from one person's
session corpus, with one person's labels. Sharing it would either:

1. Pollute one user's classifier with another's preferences (violates the
   "consistency with self over time" invariant), or
2. Require a labeler that can mark which user labeled what, which adds
   complexity nobody asked for.

Federation patterns for **opt-in label exchange between users** are
the direction past beta — see [`docs/invariants.md`](invariants.md)
"Future direction". The shortlist is:

- **Anki model** (framework shared, substrate private) — already how it
  works today.
- **Disagreement-as-feature** (see how three other users labeled this
  pair, without merging their labels into your model) — planned, opt-in
  per pair, peer-to-peer.

What is explicitly NOT planned: a central server that pools labels into
a shared baseline. That breaks the invariants.

## Does it need a GPU?

No. The labeler and compactor are CPU-only. The classifier trainer
(`weighted-compact train`) is faster on GPU but works fine on CPU —
training on a 500-pair substrate takes ~3 minutes on a modern laptop
CPU.

The e5 embedding extraction (`weighted-compact bootstrap` first run)
is the most CPU-heavy step. On a corpus of 3000 session files it takes
~10 minutes on an 8-core laptop, ~2 minutes with a CUDA GPU.

## What does `compat` actually check?

Output of `weighted-compact compat`:

- weighted-compact version + Python version + distro
- Whether each optional dependency is importable
- Substrate dir existence + file sizes (pairs/labels/features/classifier)
- Claude Code session count per source root
- Labeler port (18890 by default) — free or in use

`compat --json` returns the same as machine-readable JSON. Useful when
filing bug reports — the JSON output is enough to triage most
configuration issues.

## Can I run this on a remote server (not localhost)?

Yes, but the labeler binds to `127.0.0.1` by default. To listen on all
interfaces:

```bash
weighted-compact serve --host 0.0.0.0
```

The labeler has **no authentication**. Anyone who can reach the bind
address can label your pairs and read your conversation excerpts. Use
SSH port forwarding instead:

```bash
ssh -L 18890:127.0.0.1:18890 user@host
# locally: open http://127.0.0.1:18890/
```

This keeps the labeler localhost-only on the server and gives you
encrypted access via SSH.

## Why not use `platformdirs` for XDG paths?

`platformdirs` is a fine library, but we'd add a dep for ~50 lines of
stdlib XDG resolution. The current `config.py` implementation is
deliberately small and stdlib-only. If a contributor wants
`platformdirs` for Windows/macOS support someday, that's a reasonable
PR.

## Does the recon-QA loop need internet access?

No. It defaults to a local Ollama instance at
`http://localhost:11434/api/generate`. Override the URL via
`WEIGHTED_COMPACT_OLLAMA_URL` if you have Ollama on a different host or
port.

The cross-model anti-bias requires *two* models (default `qwen2.5:7b`
for reconstruction, `gemma3:4b` for judging). Pull both:

```bash
ollama pull qwen2.5:7b
ollama pull gemma3:4b
```

About 6 GB combined. If you only have one, set both env vars to the
same model — anti-bias degrades but the loop still runs.

## What happens if a copied file or new file contains hardcoded `/home/something/...` paths?

The pre-commit hook blocks the commit. `scripts/leak-scan.sh` flags
hardcoded paths into specific user homes. The fix is to route the path
through `weighted_compact.config` — every path the package needs has a
resolver function there.

The CI workflow also runs the leak-scan on every push, so even if the
pre-commit hook is bypassed (`--no-verify`), the CI catches it before
merge.

## Will you take a PR for X?

See [`CONTRIBUTING.md`](../CONTRIBUTING.md). Short version:

- **Yes**: bug fixes, docs, tests, distro support, new languages in the
  marker regex.
- **Discuss first**: new top-level config keys, substrate schema changes,
  classifier architecture changes.
- **No**: PRs with labeled data, conversation excerpts, or substrate
  artifacts. Multi-user / server-mode features. Telemetry. Anything
  requiring an external API key.

## Can I see what others ask?

Filing issues and discussions on the public repo is the place. There is
no analytics, no usage metrics, no aggregated questions database. If
you ask a question that gets asked twice, the second-asker gets a
pointer to the first thread.

Discussions: <https://github.com/zzallirog/weighted-compact/discussions>.
Issues: <https://github.com/zzallirog/weighted-compact/issues>.
