# 01 — Your sessions are the training corpus

This chapter covers **Layer 1 — Substrate** (boxes 1–2 in the pipeline
schema: `extract_pairs` → `feature_extract`). What it reads, where it
writes, why nothing leaves your machine.

`~/.claude/projects/` already contains everything.

Every reply you ever pushed back on. Every number you had to correct twice.
Every path the model got wrong on the first turn and right on the second.
Every constraint you stated once and then had to restate because auto-compact
erased it. It is all there, in JSONL, on your machine, timestamped and
indexed by project.

weighted-compact reads those files where they live. It does not copy them
to a server, a cloud database, or any location outside your machine. The
bootstrap is read-only on the source files. The substrate it builds lives
under `$XDG_DATA_HOME/weighted-compact/` — local, gitignored, yours.

---

## The substrate is a distillation corpus, not a log

Most tools treat session history as ephemeral: the model reads it once,
produces a summary, and the session files are never consulted again.

weighted-compact treats session history as a corpus. Each
(premise, correction) pair is a training example: the premise is what
you were working with, the correction is what you decided mattered.
The corpus grows with every session. The importance weights you assign
through labeling become part of the substrate. Future compactions draw
from the same substrate.

This means the substrate improves over time — not because a model is being
retrained in the background, but because you are accumulating more data
about your own priorities.

---

## What lives in the substrate

After `weighted-compact bootstrap`:

```
$XDG_DATA_HOME/weighted-compact/
    pairs.jsonl                 (premise, correction) pairs from all sessions
    features.npz                e5-multilingual-small embeddings, shape (N, 3, 384)
    features_density.npz        content-bearing signal per pair
    features_misstep.npz        P(stumble) per pair, if misstep is installed
    features_spans.npz          char-fraction matrix from inline annotations
    topic_segments.npz          per-session topic boundary map
    importance.npz              the composed importance score per pair
    labels.jsonl                your tier decisions: K / M / S / X
    inline_annotations.jsonl    sub-turn char-range highlights
    recon_qa_set.jsonl          Q&A entries for the fidelity gate
```

None of these files leave the host under default operation. The labeler
binds to `127.0.0.1`. The reconstruction-QA loop calls a local Ollama
instance at `localhost:11434`. Point either at a remote service and you
have opted out of the local-only guarantee — the tool will not stop you,
but the privacy commitment no longer holds.

---

## Why local matters here

Your conversation history with Claude Code is not generic text. It
maps onto your projects, your vocabulary, the names of the people you
work with, the internal addresses and service names you use, the patterns
of how you debug and when you push back. A compaction substrate trained
on that history inherits the mapping.

If the substrate leaves your machine, those patterns go with it.

Each weighted-compact install grows its own substrate from its own
sessions. There is no shared baseline. No central model. No community
weights you silently inherit. The classifier you train on your labels
is yours; copy it to another machine and it carries your decisions and
only your decisions.

---

## The substrate is not a backup

The substrate is derived from your session files, but it is not a copy
of them. `pairs.jsonl` contains extracted (premise, correction) turns,
not the full conversation. If you delete the source files under
`~/.claude/projects/`, the substrate cannot regenerate from itself;
you would need to re-run `bootstrap` from whatever sessions remain.

For the same reason: do not commit the substrate directory to a public
repository. `scripts/leak-scan.sh` catches common patterns
(`*.jsonl`, `*.npz`, `*.model`, `/home/your-name/...`) before they
reach a commit. The project `.gitignore` excludes the substrate data
directory by default.

---

## See also

- [`docs/02-pipeline.md`](02-pipeline.md) — how the bootstrap turns sessions into substrate
- [`docs/claude-code-integration.md`](claude-code-integration.md) — source path resolution, JSONL format details
- [`docs/invariants.md`](invariants.md) — the locked rules: vectors first, local only, no harness dependency
