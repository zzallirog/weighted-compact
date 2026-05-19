# Changelog

All notable changes to weighted-compact are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semver](https://semver.org/) with the explicit understanding that anything before `v0.1.0` may change schema between releases without warning.

---

## [Unreleased]

### Documented

- **Label-weight ablation result** (`docs/importance-mixture.md` §
  "Ablation"). `label_weight ∈ {0.0, 0.15}` × 5 seeds × 3 disjoint
  session corpora, N=57 paired pair-evaluations. Mean Δjudge-yes =
  **+0.053**, 95 % CI **[−0.004, +0.109]**. Direction positive in 3/3
  corpora; 13:6 on non-tied pairs. Marginal significance, consistent
  sign — `label` weight stays load-bearing at the current default
  pending more baseline. Raw runs in
  `~/work/weighted-compact/ablation_label_weight_{results.jsonl,summary.json}`.

## [0.1.0-alpha.2] — 2026-05-18

First alpha that ships publicly. Same shape as the never-published
alpha.1 draft, with screenshots regenerated against a synthetic demo
substrate (`~/work/weighted-compact-demo/` — twelve generic
dev-topic pairs in English) so the README imagery carries no
personal session content. Also includes the i18n overlay
(`?lang=en`) and the `WC_WORKDIR` env-var override that made the
demo path possible.

### Added

- `?lang=en` URL param + `STRINGS` dict (ru/en) + `t(key)` helper for
  the labeler UI. RU stays as the editor default; EN is an explicit
  opt-in. Iter narratives 2–4 use English prompts when `?lang=en`, so
  `qwen2.5:7b` returns English prose.
- `WC_WORKDIR` env override in `tool.py` and `recon_qa.py` so the
  labeler can run against an alternate substrate without touching the
  main one. Used to capture screenshots against the demo dataset.
- `window.deltasState` explicit export so external pollers (playwright,
  devtools) can read narrative-cache state. `let`-declared script vars
  don't bind to `window` and that mismatch silently broke screenshot
  automation.
- `docs/img/_take_screenshots.py` — headless playwright script that
  captures the nine README screens against a live labeler.

### Changed

- README badge `v0.0.2 → v0.1.0-alpha.2`, status `pre-alpha → alpha`.
  Phase 5 (drift inspector) and Phase 6 (per-pair fidelity) marked
  shipped in the status table.
- ∑ finale recommendation label compacted to `5` in the recommend
  hint above the tier-action row — saves pixels in the narrow
  Selected Pair cube.
- README screenshots regenerated under `?lang=en` and pointed at the
  synthetic demo substrate. No personal session content survives in
  imagery.

## [0.1.0-alpha.1] — 2026-05-17

First alpha cut. The substrate ships with three views over a shared
labels journal — Quiz (annotate), Drift Inspector (observe how
importance moves), Fidelity (verify compression survives). The same
`K / M / S / X` writes from any of the three feed the next pipeline
run.

### Added

- **Drift Inspector tab** (`§07`). Reads `importance.npz.bak.*`
  snapshots, computes per-pair trajectory across the last N runs,
  shows six drift metrics (`max_swing` / `total_var` / `slope` /
  `oscillation` / `|final|`). Sortable, threshold-filtered.
- **Iter narrative chain** in the Drift Inspector. Per-pair four-step
  reading via `qwen2.5:7b` (`stats → pattern → synthesis → recommend`),
  each iter cached and re-fireable. A fifth cell, **∑ finale**,
  fires automatically after iters 1–4 land — it mode-votes the
  tier extracted from each iter and reports the e5-measured semantic
  convergence as a confidence number.
- **Fidelity layer** (`§08`). For each pair: hide it, compact the
  rest under current mixture, run iter-chain reconstruction over
  targeted questions, judge survives-or-not via `gemma3:4b`.
  Fidelity score ∈ [0, 1] = judge-yes ratio. Conflict score combines
  with user tier: `KEEP + high fidelity = surplus`, `SKIP + low
  fidelity = loss`, etc. Append-only `fidelity_cache.jsonl` journal.
- **Conflict mode** in the inspector — sorts pairs by conflict
  descending, re-tier candidates rise to the top with `→ skip` or
  `→ keep` arrows next to the current tier chip.
- **Fidelity mode** in the inspector — sorts by raw fidelity
  ascending (worst reconstructions first), honest readout of where
  the current mixture breaks first.
- **Selected Pair redesign.** Meta block (trajectory / metrics /
  session / uuid) folded into `<details>` closed by default.
  Recommendation block sized like the main action area, color-tinted
  to the recommended tier, with a pulsing accent dot and a big
  `apply` button. A 4-tier mode strip below shows what compact does
  with each tier (`KEEP verbatim / MAYBE paraphrased gist / SKIP
  pointer-only / FALSE+ struck`) — equal-prominence, the recommended
  one highlighted.
- **Drag-select in the Drift Inspector**. Premise and correction
  blocks in the Selected Pair card are now annotatable in the same
  way as the Quiz tab — drag → popup → KEEP/MAYBE/SKIP/THINK,
  writes to the shared `inline_annotations.jsonl`.
- **Three-views framing** (`§09`). Labeler is now explicitly framed
  as three jobs on one substrate: Quiz (annotate), Drift (observe),
  Fidelity (verify). Each view recurses to the same `labels.jsonl`.

### Endpoints

- `GET /api/deltas/fidelity?mode=conflict|fidelity` — list rows
- `GET /api/deltas/fidelity/{pair_idx}` — detail + judges
- `GET /api/deltas/fidelity/status` — cache size + build progress
- `POST /api/deltas/fidelity/build` — kick threaded eval worker;
  strategies `missing` / `labelled_missing` / `reeval_low_fid`
- `POST /api/deltas/narr/finale` — aggregate prior iters into a
  mode-voted recommendation with e5 convergence drift

### Changed

- Compact buttons re-framed: not a strength scale, four render
  strategies. Tooltips and the manual-row labels now describe what
  compact does with the pair, not how "important" the pair is.
- `MEMORY.md` feedback: any inline-JS edit in a Python triple-string
  must run through `node --check` on the extracted `<script>` block.
  `ast.parse` is necessary but not sufficient — Python decodes JS
  escapes (`\s`, `\n`, single quotes) before they reach the browser,
  producing broken JS at runtime even when `ast.parse` is green.

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
