# Changelog

All notable changes to weighted-compact are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semver](https://semver.org/) with the explicit understanding that anything before `v0.1.0` may change schema between releases without warning.

---

## [Unreleased]

## [0.2.0-beta.2] — 2026-05-20

Security and correctness pass triggered by a paired audit (security review
+ code review). Architectural invariants unchanged.

### Security

- **Host-header allowlist middleware** (`tool.py`). Defends `/api/*` and `/`
  against DNS-rebinding CSRF — a hostile DNS that resolves an attacker
  domain to `127.0.0.1` can bypass loopback bind, but the browser still
  sets `Host: evil.example`. Middleware now rejects any request whose
  Host is not in `{127.0.0.1, localhost, ::1}`.
- **Bearer-token auth on `/api/*`** (`tool.py`). Token lives in
  `$XDG_RUNTIME_DIR/weighted-compact/token` (mode 0600). The HTML page
  receives it via server-side template substitution at GET `/`, and a
  fetch wrapper at the top of the bundled script auto-attaches
  `Authorization: Bearer <token>` to every same-origin request. Defeats
  trivial same-host `curl /api/next` exfil paths.
- **`leak-scan.sh` generalized**. The CI pre-commit script now catches
  any `/home/<user>/`, `/Users/<user>/`, or `/root/` path — not just the
  maintainer's own home. README's "leak-scan catches `/home/*/...`" claim
  is now accurate. `docs/` and `weighted_compact/auto_label.py` (which
  uses `/home/` as a regex prefix in its own detector) are explicitly
  excluded to avoid false positives.

### Fixed

- **`/api/recon/eval` returned `passed=0` / `accuracy=0.0` always**
  (`tool.py`). The handler read a `pass` key that `run_eval()` never
  produced; the browser UI hid the bug by recomputing locally. Now reads
  `judge.verdict` and also exposes `passed_substring` for completeness.
- **`importance.py` documented 6 signals but composed 7.** The actual
  `WEIGHTS` dict has been carrying `span_think: 0.05` since the alpha
  series; docstring + README + CLAUDE.md still said "six-signal mixture"
  and described `components` as `(N, 6)`. Brought docs to match the
  code (code is the source of truth — `span_think` keeps a small positive
  weight on "preserve + flag for re-examination" spans).
- **`importance.compose` crashed when `features_misstep.npz` was missing**
  even though the "vectors-first, classifier-secondary" invariant says
  it should degrade gracefully. Misstep column now defaults to zero
  when the predictor is not installed; the remaining six signals carry
  the load and `meta.misstep_present` records the status.
- **File-handle leaks in `recon_qa/context.py` and `recon_qa/fidelity.py`**
  (`open()` without `with`). Long-running labeler called these on every
  `/api/recon/*` request; fixed to use context managers.
- **Inconsistent JSON-decode tolerance across modules.** `extract_pairs.py`
  tolerated bad JSONL lines; `recon_qa/context.py`, `recon_qa/fidelity.py`
  and `density_features.py` crashed. Aligned all readers to skip bad
  lines without raising. The recon-QA set in particular is human-editable
  and routinely lands a partial line during a manual save.
- **`weighted-compact ablation` command in README did not exist.** The
  Quiz Q2 invitation referenced a CLI subcommand that was never wired.
  Replaced with a two-pass recipe using the existing `importance` +
  `qa-gate` commands; a proper `ablation` wrapper is filed for v0.3.
- **`weighted-compact compat --show-drift`** in CLAUDE.md likewise did
  not exist. Removed.

### Changed

- **CLI bootstrap re-evaluates config at command time** (`cli.py`). Env
  overrides like `$WEIGHTED_COMPACT_DATA` set after the
  `weighted_compact` package was imported now take effect.
- **`_constants._reload_paths()`** helper added for tests that monkeypatch
  `$WEIGHTED_COMPACT_DATA` mid-session.
- **`density_features.extract_density()`** sizing derived from
  `FEATURE_NAMES` list, not hardcoded `8`. The README "30 LOC for a new
  density feature" claim is now true (was 5 hardcoded sites previously).
- **Broad `except Exception`** in `recon_qa/generator.py` and
  `recon_qa/judge.py` now log a warning before swallowing — silent
  forever-fail was an anti-pattern.
- **`topic_segments.segment_session()`** parameter renamed
  `corr_vecs` → `vecs_by_pos`. The function accepts a dict-or-array
  keyed by session-local position; the old name promised an ndarray.
- **Lazy `from datetime import datetime` inside two handlers**
  consolidated to module-top import (`tool.py`).
- **`/api/recon/save`** now returns `{ok: True, total: N}` instead of
  `{status: 'ok', total: N}` — minor envelope alignment; full envelope
  standardization across all endpoints deferred to a separate PR.

## [0.2.0-beta.1] — 2026-05-20

First beta cut. The substrate, six-signal mixture, three-view labeler,
and reconstruction-QA gate all run end-to-end on a real session corpus.
Architectural invariants are locked; numbers around them are not.

### Added

- **`weighted-compact qa-gate` CLI command.** Segments the recon-QA set
  into trivial / impossible / informative / inverted buckets by running
  the eval at two `k_drop` levels. `--easy-k 0.0 --hard-k 0.9 --signal
  judge` is the recommended invocation. `--write` persists the
  informative subset to substrate for follow-up labeling.

### Changed

- **Status: alpha → beta.** `pyproject.toml` classifier
  `Pre-Alpha → Beta`; `__version__` and release badge bumped to
  `0.2.0b1`; README badge dedup (single beta badge replaces the prior
  release+status pair).
- **`recon_qa.py` split into a package** (`weighted_compact/recon_qa/`).
  The 600 LOC monolith is now five black-box modules — `context.py`
  (compacted-context assembly + signal loaders), `generator.py`
  (`suggest_qa`/`ask_ollama`), `judge.py` (`llm_judge`/`score`/
  `iter_chain_metrics`), `gate.py` (`classify_difficulty` difficulty
  buckets), `fidelity.py` (`run_eval` + qa_set journal helpers) — plus
  `_constants.py` for shared paths/model names. `__init__.py`
  re-exports every previously-public symbol; callers using
  `from weighted_compact import recon_qa; recon_qa.foo(...)` keep
  working unchanged. Each module starts with a `Black box:
  вход/выход/как открыт` contract docstring.
- **`recon_qa.score()` null-guard restored.** Empty `predicted` or
  `a_truth` now returns `False` instead of evaluating `"" in ""` as
  `True`, which had silently inflated fidelity counts on
  `<ollama_error: ...>` responses.

### Documented

- **vocab_canon (§5.3) ablation — DROP.** 5-corpus paired ablation
  (canon_off=0.0 vs canon_05=0.05) on the 62-entry v1 corpus. Sign
  agreement positive: 0/5; canon_05 yes-rate 0.000 vs canon_off 0.089.
  Adding a flat presence-based bonus DISPLACES pairs that previously
  ranked high on misstep/density/label without compensating with
  Q-relevance signal. CANON_TOKENS list and the harness stay in the
  maintainer's private substrate as reference for future ablations.
  Future direction: per-Q canon bonus (boost only when canon token
  appears in BOTH the pair and the Q), not a flat flag. Raw results in
  `~/work/weighted-compact/ablation_vocab_canon_{results.jsonl,summary.json}`.
- **README + `docs/01..05` direction-first refine.** Each chapter opens
  with the pipeline box / layer it covers, then the direction the user
  cares about, before mechanics. `docs/03-quality-driver.md` rewritten
  with the "What it grows into" section (vault framing, +4pp fidelity
  band, `direction not destination`). Stale `v0.1.0-alpha.2` / `v0.0.01`
  references swept; `Direction for v0.1` renamed `Future direction`
  across `invariants.md` and `faq.md`.
- **CLAUDE.md substrate framing section.** Added near top for
  cold-pickup by any LLM walking the repo.
- **Label-weight ablation result** (`docs/importance-mixture.md` §
  "Ablation"). `label_weight ∈ {0.0, 0.15}` × 5 seeds × 3 disjoint
  session corpora, N=57 paired pair-evaluations. Mean Δjudge-yes =
  **+0.053**, 95 % CI **[−0.004, +0.109]**. Direction positive in 3/3
  corpora; 13:6 on non-tied pairs. Marginal significance, consistent
  sign — `label` weight stays load-bearing at the current default
  pending more baseline. Raw runs in
  `~/work/weighted-compact/ablation_label_weight_{results.jsonl,summary.json}`.

### Removed

- **Orphan modules:** `weighted_compact/extract_pairs_incremental.py`
  and `weighted_compact/feature_extract_incremental.py` — never wired
  into the pipeline path or any test, only existed as historical
  early-experiment stubs.
- **Orphan docs assets:** `docs/img/SHOT-LIST.md` and
  `docs/img/_take_screenshots.py` — alpha.1 screenshot-capture rig,
  superseded; PNGs under `docs/img/` are kept since the docs link to
  them.

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
