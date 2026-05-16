# Changelog

All notable changes to weighted-compact are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semver](https://semver.org/) with the explicit understanding that anything before `v0.1.0` may change schema between releases without warning.

---

## [Unreleased]

## [0.0.2] — 2026-05-16

Docs-and-release polish on top of the v0.0.1 framework cut. No
behavioural change to the labeler, compactor, or substrate pipeline.

### Changed

- **README rewritten as a narrative.** The opening describes the
  problem (auto-summarizer is a black box you don't choose to invoke,
  on criteria you can't inspect) and what this substrate does
  instead, in continuous prose. Sections 01–06 each follow the same
  shape: the problem the layer addresses, the mechanism, the design
  consequence. No comparison tables, no "is/is not" framing, no
  feature lists.
- **Screenshots moved into context.** The three-screenshot block at
  the top is gone; each illustration now sits next to the section it
  illustrates. The duplicate annotation close-up was dropped — the
  hero screenshot under `§02` already shows the same pair with
  the same tier underlines, just with the cheat-sheet open.
- **Pre-commit hook is now explicitly contributor-optional.** Both
  `CLAUDE.md` and `CONTRIBUTING.md` now make it clear that
  `scripts/install-hooks.sh` is for contributors who want a local
  leak-check before pushing. The same scan runs in CI on every push,
  so the maintainer's flow doesn't require it.

### Why this is a separate release

`0.0.1` shipped with prose that read like a feature list and pre-commit
guidance that sounded mandatory. Neither was wrong, but both gave
visitors the wrong first read of what the project is. `0.0.2` is the
polish pass that closes that gap before the substrate work for `0.0.3`
starts (real recon-QA baseline numbers, the W2 render layer).

## [0.0.1] — 2026-05-16

First public cut. Pre-alpha. The architectural invariants are locked
(vector-first / classifier-secondary, labeling triggered by specific
events not bulk, independence from any agent-harness API); the numbers
around them are not.

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
- **i18n for the labeler** — UI bundles three languages (English,
  Russian, Ukrainian) with a switcher persisted to `localStorage`.
  Translations live inline in `tool.py:I18N`; adding a fourth language
  is two edits (extend the dictionary, add one `<option>`).

### Fixed

- **Annotation schema backward-compat** — annotations written through
  the POST `/api/annotation` handler include both `char_start`/`char_end`
  and a `char_range: [start, end]` array. The frontend reads only
  `char_range`. Hand-written or migrated fixtures carrying just
  `char_start`/`char_end` made the labeler crash silently with
  `Cannot read properties of undefined (reading '0')`. `reload_state`
  now synthesizes `char_range` from `char_start`/`char_end` when absent.
  Caught while producing the v0.0.1 README screenshots.
  See `tests/test_annotation_compat.py`.
- **`recon_qa` lazy-imports `requests`** — the labeler imports
  `recon_qa` at module load, which previously imported `requests`
  unconditionally. `requests` is only used to POST to a local Ollama
  instance for the optional reconstruction-QA evaluator, and is not in
  the hard dependency set. CI matrix on a clean install caught the
  resulting `ModuleNotFoundError` on every cell.
- **CI safe-directory in containers** — the Arch and Debian matrix
  cells run inside containers where the checkout dir is owned by a
  different UID than the container's root user. `git ls-files` refused
  to operate with `dubious ownership`. The workflow now runs
  `git config --global --add safe.directory "$GITHUB_WORKSPACE"` before
  the leak-scan step.

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
