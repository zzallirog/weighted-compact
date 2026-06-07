# Architecture

Three independent layers. Each layer disables cleanly via missing inputs
or configuration; the next layer downstream notices and falls back to a
sensible default.

```
                                ┌───────────────────────────────────┐
                                │  ~/.claude/projects/*/*.jsonl     │  ◀ source-of-truth
                                │  ~/.claude-work/projects/*/*.jsonl│     (read-only, never written)
                                └─────────────┬─────────────────────┘
                                              │
                          extract_pairs.py    │
                                              ▼
       ┌─────────────────────────────────────────────────────────────┐
       │                       LAYER 1 — Substrate                   │
       │                                                             │
       │  pairs.jsonl              one record per (premise, correction)
       │  features.npz             (N, 3, 384) e5 windows
       │  inline_annotations.jsonl span-level tier tags (tombstones)
       │  labels.jsonl             per-pair tier labels (k/m/s/x)
       └──────────────────────────┬──────────────────────────────────┘
                                  │
        ┌─────────────────────────┼────────────────────────┐
        │                         │                        │
        ▼                         ▼                        ▼
  density_features.py     span_features.py        topic_segments.py
        │                         │                        │
        ▼                         ▼                        ▼
  features_density.npz   features_spans.npz      topic_segments.npz
        │                         │                        │
        └─────────────────────────┼────────────────────────┘
                                  │
                                  ▼
       ┌─────────────────────────────────────────────────────────────┐
       │                  LAYER 2 — Importance Mixture               │
       │                                                             │
       │  importance.py composes six signals:                        │
       │    0.25 × density    + 0.15 × label                         │
       │  + 0.20 × span_keep  + 0.10 × span_maybe                    │
       │  − 0.15 × span_skip  + 0.05 × span_think                    │
       │                                                             │
       │  importance.npz       (N,)  ∈ [0, 1]                        │
       │  components           (N, 6)                                │
       └──────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
       ┌─────────────────────────────────────────────────────────────┐
       │                  LAYER 3 — Reconstruction-QA                │
       │                                                             │
       │  recon_qa.build_compacted_context(                          │
       │      budget_chars=8000,                                     │
       │      topic_decay=0.5,                                       │
       │  )                                                          │
       │                                                             │
       │  effective_score = importance × decay ^ |Δtopic|            │
       │  → top-K spans selected, verbatim KEEP, gist rest           │
       │                                                             │
       │  recon_qa.iter_chain_metrics — per-step drift labels        │
       │  recon_qa.suggest — Ollama-backed reconstruction sampler    │
       └─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                          compacted Markdown
                          (paste-delivery)
```

## Module map

| File | Responsibility | Required deps |
|---|---|---|
| `config.py` | Path resolution (XDG, env override) | stdlib |
| `extract_pairs.py` | Walk session JSONL, build (premise, correction) records | stdlib |
| `feature_extract.py` | e5 embeddings per pair (3-turn windows) | sentence-transformers |
| `density_features.py` | 16-feature density signal (names, numbers, code fences, etc.) | numpy |
| `span_features.py` | Char-fraction matrix from inline annotations | numpy |
| `topic_segments.py` | Unsupervised sliding-window cohesion segmentor | numpy |
| `misstep_score.py` | Logistic regression on stumble events (optional) | sklearn, duckdb |
| `importance.py` | Compose six signals into continuous score | numpy |
| `recon_qa/` | Reconstruction-QA package — 5 sub-modules (context / generator / judge / gate / fidelity) | requests (optional Ollama) |
| `tool.py` | FastAPI labeler at :18890 | fastapi, uvicorn |
| `cli.py` | `weighted-compact` entry point | click |
| `model.py` | Optional 3-tier classifier (attention-pool, deprecated) | torch |
| `train.py` | Bootstrap training loop for `model.py` | torch, sklearn |
| `eval.py` | Coverage-ratio reconstruction gate | torch (via `model.py`) |
| `label_pairs.py` | CLI fallback labeler (emergency, when web UI unreachable) | stdlib |
| `build_queue.py` | Disagreement + low-confidence + audit-anchor queue builder | stdlib |
| `auto_label.py` | Bootstrap labels from inline markers in transcripts | stdlib |

## Substrate contract

Everything under `$XDG_DATA_HOME/weighted-compact/` is **append-only or
atomically-replaced**. The `.bak.YYYYMMDD-HHMMSS` snapshots are produced
automatically by the feature extractors before overwriting, and are
gitignored.

| File | Shape | Frequency |
|---|---|---|
| `pairs.jsonl` | append-only, one pair per line | bootstrap + incremental |
| `labels.jsonl` | append-only, latest line wins | every label keystroke |
| `inline_annotations.jsonl` | append-only with `deleted: true` tombstones | every span drag |
| `fidelity_cache.jsonl` | append-only, latest line wins (replay) | per pair, on `build · 10` button |
| `queue.jsonl` | rewritten atomically | nightly + on-demand |
| `features.npz` | rewritten atomically with `.bak.*` snapshot | every re-embed |
| `features_*.npz` | rewritten atomically with `.bak.*` snapshot | every re-extract |
| `importance.npz` | rewritten atomically with `.bak.*` snapshot | every mixture recompose |

The `importance.npz.bak.*` snapshots — formerly just rollback insurance —
became a primary substrate consumer for the Drift Inspector starting in
the `v0.1.0-alpha.2` cut. The inspector inner-joins the last N snapshots
on `pair_idx` to compute per-pair trajectories. Keep them around;
deleting old snapshots truncates the drift window.

`fidelity_cache.jsonl` is the per-pair compression-quality cache filled
by the Fidelity mode. Each entry: pair_idx, fidelity ∈ [0, 1] (judge-yes
ratio over reconstruction-QA), per-question judge verdicts, the mixture
weights at eval time. Replay-newest-wins, so re-running fidelity on a
pair simply appends; consumers see the latest record.

Append-only journals are tombstone-replayed at load time, which means
deletions are non-destructive — the original line stays, the tombstone
overlays it.

## Privacy boundary

```
substrate/                                # under $XDG_DATA_HOME, gitignored
    pairs.jsonl                           # raw conversation text
    labels.jsonl                          # your tier decisions
    inline_annotations.jsonl              # your span tier tags
    *.npz                                 # embeddings + derived features
    classifier.model                      # (if trained)
                                          # ↑ everything above is personal
                                          # ↓ everything below is public

framework/                                # under repo checkout
    weighted_compact/*.py                 # code only
    tests/                                # synthetic fixtures only
    docs/                                 # narrative documentation
```

Nothing in the framework checkout ever reads from the substrate at import
time; it is read lazily inside functions. The framework can therefore be
audited end-to-end without ever booting the substrate.
