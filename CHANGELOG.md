# Changelog

All notable changes to weighted-compact are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semver](https://semver.org/) with the explicit understanding that anything before `v0.1.0` may change schema between releases without warning.

---

## [Unreleased]

## [0.0.01] — 2026-05-16

First public cut. Pre-alpha. The architectural invariants are locked
(vector-first / classifier-secondary, CAPTCHA gap-fill not bulk, independence
from harness API); the numbers around them are not.

### Added

- **CAPTCHA labeler UI** — local FastAPI app on `:18890` with keyboard
  shortcuts `k/m/s/x` for KEEP/MAYBE/SKIP/FALSE-POSITIVE, drag-select
  popup for span-level annotation, anti-drift sidebar showing the five
  cosine-nearest prior labels.
- **Span-level annotation** — four-tier char-range tagging
  (`keep`/`maybe`/`skip`/`think`) with soft-delete tombstones in an
  append-only journal.
- **Phase 4 continuous importance mixture** — six signals composed:
  misstep AUC (0.40), density (0.25), label (0.15), span_keep (0.20),
  span_maybe (0.10), span_skip (−0.15), span_think (+0.05).
- **Topic-aware compaction** — unsupervised sliding-window cosine
  cohesion segmentor (`topic_segments.py`) plus a UI slider for
  exponential decay across topic boundaries.
- **Reconstruction-QA loop** — sample → save → eval → suggest workflow
  with per-iter drift labels for multi-step chains.
- **`weighted-compact bootstrap`** — read `~/.claude/projects/`, extract
  pairs, seed substrate under `$XDG_DATA_HOME/weighted-compact/`.
- **`weighted-compact compat`** — read-only diagnostic listing detected
  Claude Code sessions, substrate state, missing optional dependencies.
- **`weighted-compact install-units`** — drop systemd user unit for
  ambient operation.

### Known limitations

- Single-user by design. Federation patterns are filed as `v0.1`
  direction in [`docs/invariants.md`](docs/invariants.md).
- Reconstruction-QA needs ~50 baseline samples before its scores
  stabilize. First labeling session is exploratory.
- The bootstrap heuristic for marker extraction matches Russian, English,
  and Ukrainian patterns. Other languages need contributed regexes in
  `weighted_compact/extract_pairs.py`.
- Substrate carries raw conversation text. `.gitignore` is aggressive,
  but if you fork and add CI artifacts, audit them before pushing.
