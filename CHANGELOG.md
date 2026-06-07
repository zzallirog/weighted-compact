# Changelog

All notable changes to weighted-compact are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semver](https://semver.org/) with the explicit understanding that anything before `v0.1.0` may change schema between releases without warning.

---

## [0.3.0a1] — 2026-06-07

Honest re-grounding. The project carried a `beta` badge it had not earned;
this release relabels it **alpha** and re-centers it on the one consumer with
a positive, re-checkable result — recap — while stating plainly that the
importance mixture has no measured fidelity edge.

### Added

- **Recap reader** (`weighted-compact recap [SESSION] [--audit] [--all]`) — a
  task-segmented, lossy navigation map of a session: per task, the files
  touched (`+adds/−rems` diffstat), commands run, and the verbatim outcome
  line. Deliberately not reconstructable (use `gzip`/`zstd` for that), but
  **provably faithful**: four invariants (coverage · conservation · provenance
  · determinism) re-checked by an independent pass, holding on **986/986** of
  the maintainer's sessions. Stdlib-only, ~5 ms/session. See
  [`docs/recap.md`](docs/recap.md); synthetic tests in `tests/test_recap.py`.
- **Manifesto hard-constraint** — `keep`/`skip` labels are now honored as a
  deterministic *selection* constraint, not just a soft score signal:
  `build_compacted_context(manifesto=…)` pins keep-labeled pairs (guaranteed to
  survive, up to budget) and banishes skip-labeled pairs (dropped first); the
  rest fill the budget by importance score. Exposed default-on via the
  `compact_session` MCP tool (`honor_manifesto=true`), with `meta.manifesto`
  reporting how many keeps survived / skips were dropped. This is a *control*
  guarantee, **not** a fidelity gain — recon-QA fidelity stays null for both the
  mixture and hand-curation; the manifesto only controls *what survives* (see
  [`docs/baselines.md`](docs/baselines.md), proven by construction in
  `tests/test_manifesto.py`). The soft `label` boost alone only tied recency on
  manifesto-honor (the density backbone overruled it); the hard constraint
  reaches 100 % honor at k_drop ≤ 0.7 on the maintainer's labeled session.

### Changed

- Pair selection unified into a single `_select_kept` helper shared by
  `build_compacted_context` and its `_with_meta` variant — markdown and meta can
  no longer disagree on what survived.
- Importance mixture is now **six signals** — `density` (backbone, 0.25),
  `label` (0.15), `span_keep` (0.20), `span_maybe` (0.10), `span_skip` (−0.15),
  `span_think` (0.05). `importance.npz` schema → v2 (components `(N, 6)`,
  weights `(6,)`).
- `bootstrap --full` builds the whole substrate in one shot
  (`feature_extract → density → spans → topic → importance`). e5 embeddings are
  the `[baselines]` tier: `[mcp]` builds a working compaction substrate;
  `[baselines]` adds semantic search.
- Documentation reconciled against the live code throughout.

### Fixed

- **(high) recon_qa source-pair lookup** — `build_compacted_context*` and
  `run_eval` treated `source_pair_idx` as a list index, but it is a `pair_idx`
  field value; when `load_pairs` skipped a blank/corrupt line the index
  diverged and the **wrong source pair** was fetched. Now resolved via a
  `{pair_idx: pair}` map. (Found by an Opus-verified sonnet bug-hunt swarm.)
- **recap I1 invariant was vacuous** — `n_covered == n_messages` held by
  construction and could never fail; replaced with `sum(seg.n_msgs) ==
  n_messages`, a real check. Re-verified 986/986.
- `json.loads` on `pairs.jsonl` / `labels.jsonl` lines now tolerates a single
  partial-write in `span_features`, `topic_segments`, and
  `recon_qa.context.load_manifesto` (try/except continue), matching
  `load_pairs`.
- Schema extraction `NO_RULE` early-exit no longer missed on trailing
  punctuation; `mcp_server` substrate `session_count` no longer counts a
  `None` bucket; `config.labeler_port` errors cleanly on a non-integer
  `$WEIGHTED_COMPACT_PORT`.

### Changed

- **Status relabeled `beta` → `alpha`** (README badge, `CLAUDE.md`,
  `pyproject` classifier). The mixture-vs-baseline result is null and is now
  marked as such everywhere; recap is the documented flagship.

### Removed

- `misstep` signal dropped from the default mixture (earlier); this release
  removes the now-dead `misstep_score.py` trainer and its `config` paths —
  the shipped pipeline no longer reads `features_misstep.npz`.
- Mooted research modules (`beta_schedule`, `beta_search`, `cv_harness`,
  `com_shift`, `replay_eval`, `sandbox_probe`, `ablation_axes`) are now
  gitignored — they served the importance-mixture-beats-baseline hypothesis,
  which came back null. `com-shift` CLI command removed.

## [0.2.0-beta.3] — 2026-05-26

Substantive release: third retrieval tier (schema-extraction) ships as
sub-package, REM-decay + MCP server + Docker wrap land, baselines harness
(random / recency / cosine / BM25 / `/compact` simulator) goes end-to-end,
public ranker registry + Signal Protocol formalise the plugin surface,
README undergoes a cold-reader rewrite. Honest baseline measurement
(2026-05-21) replaces earlier headline claims: structured selection beats
`/compact` by ~8pp on the maintainer's corpus; mixture vs cheap baselines
remains null at N=62 under the cheap judge (this is surfaced, not hidden).

Also: GitHub issue/PR templates + FUNDING + CI workflows; lint and
leak-scan fixes; mechanistic-audit methodology doc (arXiv 2602.19159
applied to own importance mixture).

### Added — 2026-05-23 Public ranker registry + Signal Protocol + extension recipe

Three coordinated additions that turn the eight built-in rankers into one
particular *instance* of a documented plugin surface:

- **`weighted_compact.ranker`** — new module exposing `RANKER_REGISTRY`
  (a dict-like store), `RankerSpec` (dataclass: name, loader,
  description, requires_extras, query_aware, since_version),
  `@register(...)` decorator, `list_rankers()` and `get_ranker()`. The
  eight shipped rankers (importance, density, random, recency, cosine,
  bm25, compact_qwen, compact_sonnet) now register through this same
  surface at `weighted_compact.recon_qa.fidelity` import time. The
  pre-existing `_RANKER_LOADERS` name is preserved as a live read-only
  view over the registry, so existing call sites and tests keep working
  unchanged.
- **`Signal` Protocol** — added in `weighted_compact.importance`,
  re-exported from `weighted_compact.recon_qa`. Documents the shape
  third-party signal contributors should adopt (`name: str`,
  `compute(pair_indices) -> np.ndarray`). The default seven-signal
  mixture is unchanged — `Signal` is documentation, not enforcement.
- **`weighted-compact rankers`** — new CLI verb prints every registered
  ranker (name, query-aware, since-version, extras, description). Use
  `--json` for machine-parse. The `qa-gate` verb's `--ranker` argument
  is now validated against the registry at runtime (rather than a
  hardcoded `click.Choice` list), so plugin rankers are selectable too.
- **`docs/extension-recipe.md`** — worked example: build a `length`
  ranker in an external package, install it, and consume it via
  `weighted-compact qa-gate --ranker length`. Includes a Signal-shaped
  variant and a comparison to claude-mem (which has no equivalent
  surface).

### Stability promise (2026-05-23)

The following surfaces will not change shape through v1.0. Additions
allowed; renames or removals constitute a major version bump.

- `weighted_compact.recon_qa.__all__` — every name listed is stable
  through v1.0.
- `weighted_compact.ranker` — `RANKER_REGISTRY`, `RankerSpec`,
  `register`, `list_rankers`, `get_ranker`, and `Signal` (re-exported
  from `weighted_compact.recon_qa`) are stable through v1.0.
- `weighted_compact.recon_qa.context.build_compacted_context_with_meta`
  — function signature (positional + keyword parameters) and the
  returned `(markdown, meta)` tuple shape stable through v1.0. New
  optional keyword args may be added; existing ones won't change.
- CLI verb names listed in `weighted-compact --help` are stable from
  v0.2.0 forward. Additions allowed; renames are a major version bump.
- MCP tool names (`search_pairs`, `compact_session`, `substrate_info`)
  exposed by `weighted-compact mcp-serve` are stable from v0.2.0 forward
  under the same rule.

Narrative restatement of the same promise lives in `docs/stability.md`.

### Fixed — 2026-05-23 Ollama pre-flight in eval / qa-gate

`recon_qa.fidelity.run_eval` now probes `GET <OLLAMA_URL>/api/tags` with
a 2 s timeout before any per-entry loop, and verifies the configured
`MODEL` + `JUDGE_MODEL` are present in the installed list. If ollama is
unreachable or a required model is missing, the run aborts with a
`click.ClickException` and a fix directive (`ollama serve` /
`ollama pull <model>`). Previously the judge silently returned `other`
verdicts when ollama was down and `judge_yes_fraction` was inflated
against a bogus denominator. Bypass with `--no-preflight` on
`weighted-compact qa-gate` only to deliberately reproduce the silent-
failure mode. `classify_difficulty` runs the probe once across its two
eval passes.

### Added — 2026-05-23 Bootstrap completion summary

`weighted-compact bootstrap` now prints a structured summary block after
`extract_pairs.main()` — pair count, unique session count, scanned
roots, output path, and the next two pipeline commands
(`weighted-compact importance` / `weighted-compact rem-pass`). Previous
behaviour was a single `Wrote pairs to <path>` line that left new users
with no signal that the scan found anything useful.

### Added — 2026-05-23 npz schema fingerprint (forward-compat machinery)

`importance.py`, `rem_decay.py`, `baselines/random_ranker.py`, and
`baselines/recency_ranker.py` each now define a `SCHEMA_VER = 1`
constant and write `schema_ver=np.array([SCHEMA_VER])` into their npz
output. Corresponding loaders in `recon_qa/context.py`
(`load_importance`, `load_baseline_random`, `load_baseline_recency`,
`load_rem_decay`) check the field on load: absent → accept silently as
version 0 (the existing on-disk era); mismatch → raise `RuntimeError`
with a `Rebuild with: weighted-compact <command>` directive. `SCHEMA_VER`
stays at 1 for this release — the machinery installs the upgrade path
for the next time the npz layout changes.

### Added — 2026-05-23 `weighted-compact metrics` CLI

New read-only subcommand prints the local substrate's footprint
(total + per-file size), `*.bak.*` cleanup overhead, pair + session
counts, REM-pass freshness (`ref_iso` from `rem_decay.npz` meta), and a
warm-cache micro-timing of `load_pairs` + `load_importance`. Plain text
by default; `--json` for machine-parse. Helper logic lives in
`weighted_compact/metrics.py` so it's testable in isolation. Closes the
gap where the operating-guide footprint numbers were only measurable on
the maintainer's substrate.

### Added — 2026-05-23 Docker packaging

`Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, and
`docs/docker-install.md` — a self-contained Docker stack for users who
prefer not to manage a Python toolchain by hand (primary audience: Windows).

- Multi-stage `Dockerfile`: builder stage compiles deps with `gcc`; runtime
  stage is `python:3.11-slim` with a non-root `wc` user. The leak-scan
  hygiene check runs as a build step. Final image target size ~200 MB.
- `docker-compose.yml` with three services:
  `weighted-compact` (labeler, `127.0.0.1:18890`), `ollama` sidecar
  (gemma3:4b + qwen2.5:7b, GPU passthrough commented-in with a note), and
  `weighted-compact-rem` (nightly sleep-loop, commented-out opt-in).
  Claude sessions are mounted read-only; the substrate lives in a named
  volume (`wc-substrate`) so it survives `docker compose restart`.
- `docker-entrypoint.sh`: guards `serve` against a missing substrate
  (prints a "run bootstrap first" message and exits 1); implements the
  `rem-loop` special command for nightly REM-decay.
- `docs/docker-install.md`: step-by-step for Linux / macOS / Windows,
  including the PowerShell bind-mount syntax, both REM options (sleep-loop
  vs host cron/Task Scheduler), ollama sidecar disable path, and common
  gotchas (SELinux `:z` flag, Docker Desktop file-sharing prompts, GPU
  passthrough).

### Added — 2026-05-23 MCP stdio server: local-only query surface over the substrate

A local-only Model Context Protocol server exposing three read-only
substrate operations to any MCP-speaking client (Claude Desktop,
mcp-cli, IDE plugins). Stdio transport only — no network listener, no
auto-injection, no labeling. The client polls; the server answers.

- New module `weighted_compact/mcp_server.py` — three tools registered
  on a `FastMCP("weighted-compact")` instance:
  - `search_pairs(query, top_k=10)` — cosine-ranks pairs against the
    query using the existing CosineRanker (e5 dense over `features.npz`),
    returns previews truncated to 200 chars.
  - `compact_session(source_pair_idx, k_drop=0.5, ranker="importance",
    rem_decay=False)` — wraps `build_compacted_context_with_meta` and
    returns `{markdown, meta}` with the full budget-transparency dict.
  - `substrate_info()` — cheap diagnostic: pair_count, session_count,
    `has_importance` / `has_rem_decay` flags, `rem_decay_ref_iso`,
    `signals_present`.
- New CLI command `weighted-compact mcp-serve`. Lazy-imports the SDK and
  raises a `click.ClickException` with an `install` instruction if the
  optional extra is missing — `import weighted_compact` keeps working
  without the SDK.
- New optional extra in `pyproject.toml`: `mcp = ["mcp>=1.0.0"]`.
  Install with `pipx install 'weighted-compact[mcp]'`.
- Substrate-disable-clean: missing `pairs.jsonl` / `features.npz` /
  `importance.npz` / `rem_decay.npz` produces structured error payloads
  with `hint` fields rather than crashing the stdio loop.
- Docs: `docs/mcp-integration.md` — what it is and isn't (local-only,
  stdio-only, read-only), install + run, all three tool docstrings
  verbatim, Claude Desktop `claude_desktop_config.json` snippet, and the
  open question on whether `search_pairs` should accept a date-range
  filter (currently no).

No write tools, no server-side LLM calls, no HTTP/SSE/WebSocket. If
someone wants a remote endpoint, they fork — the local-only framing is
why the substrate (raw conversation text) can ship this surface safely.

### Added — 2026-05-23 REM-decay: daily wall-clock importance refresh

A nightly multiplier that ages the substrate by wall-clock time,
modelled (semantically) on the REM phase that re-weights yesterday's
experience overnight. Independent of the seven-signal mixture —
importance encodes content properties (stable), REM encodes time
(refreshed every day at 04:00).

- New module `weighted_compact/rem_decay.py` — `compute()` (pure) and
  `build()` (writes `rem_decay.npz`). Default half-life 7 days
  (yesterday ≈ 0.91, week ≈ 0.50, month ≈ 0.05). Session timestamps
  derived from the mtime of the matching transcript at
  `~/.claude/projects/*/<session_id>.jsonl`.
- New CLI command `weighted-compact rem-pass [--half-life-days 7]`.
- Drop-in baseline-shape registration:
  `weighted-compact baseline build --ranker rem`.
- `recon_qa.context.build_compacted_context(..., rem_decay_map=)` —
  composes the multiplier orthogonally with the existing topic-decay term.
- `recon_qa.fidelity.run_eval(..., rem_decay=False)` and
  `recon_qa.gate.classify_difficulty(..., rem_decay=False)` accept the
  flag end-to-end.
- `weighted-compact qa-gate --rem-decay` runs the gate with the
  nightly multiplier composed.
- Systemd timer template installed by `install-units`:
  `weighted-compact-rem-pass.{service,timer}`, fires daily at 04:00
  with a 15-minute randomized delay.
- Docs: `docs/rem-decay.md` — decay curve, operational steps, honest
  limits (session-level resolution, mtime drift, heuristic half-life).

The output `rem_decay.npz` follows the same schema as the other baseline
npz files (`pair_indices`, `importance`, `meta`) so existing loaders
treat it as a drop-in. Atomic publish via `.tmp` rename, previous
version rotated to `rem_decay.npz.bak.<UTC-ts>`.

### Added — 2026-05-22 schema-extraction sub-package (`weighted_compact/schema_extraction/`)

Third retrieval tier proof-of-concept: extract reusable rules from your
own memory dir as `(trigger, rule, anti-pattern, stable_since)` schemas,
sitting above existing chunk/episode retrieval as the cheap top-tier.

- New CLI subgroup: `weighted-compact schema {build-bank, run, all, paths}`
- `bank_builder` — heuristic scan of `~/.claude/projects/*/memory/` +
  `~/.claude/work/` for files with stability markers (DONE/SHIPPED/RESOLVED
  + dates); each candidate passed to local gemma3:4b to extract structured
  TRIGGER/RULE/ANTI block, dropped if `NO_RULE`. Self-creating bank: a
  full scan of the maintainer's 290 memory + HANDOFF files produced 246
  extractable cases unattended.
- `synthesizer` + `judge` — query-conditioned extraction (model receives
  the case's trigger phrase as target context), then MATCH/NEAR/MISMATCH
  verdict via configurable judge model.
- `pipeline.run_pipeline()` — orchestrate full validation; writes per-case
  JSON + summary markdown to `$XDG_DATA_HOME/weighted-compact/schema-runs/`.
- Bank file (`schema-bank.yaml`) lives under XDG data dir, gitignored.
  Real banks carry user-specific content and are never committed.
- Added `pyyaml>=6.0` to core deps (bank format).
- Version bump 0.2.0b2 → 0.2.0b3.

Design notes: `docs/schema-extraction.md`. Architectural alignment with
the locked invariant (vectors-first, classifier-secondary): schemas are a
**refinement tier** atop existing retrieval, not a gatekeeper. If
extraction degrades, chunk retrieval keeps working unchanged.

#### Proof run — honest chronology of three numbers

The first proof took three runs to settle. They are recorded here because
the path from one number to the next is exactly the method-level finding
this sub-package surfaces.

1. **Pre-fix: claimed 18/20 = 90% strict — withdrawn.** The verdict parser
   in `judge.py` originally iterated `("MATCH", "NEAR", "MISMATCH")` and
   returned the first token found via substring match. `"MATCH" in
   "MISMATCH"` is `True`, so every MISMATCH the judge emitted was silently
   parsed as MATCH. The smoke test caught this on a synthetic input; the
   fix (MISMATCH-first order) was committed in the same patch as the
   90% claim, but the proof report cited as evidence had been generated
   before the fix landed. Re-parsing the same `judge_raw` strings with
   the corrected parser yields **5/20 strict = 25%** — the bug was
   contributing all 13 of the inflated MATCH counts. The 90% is an
   artifact, not a result. It was caught by an independent code review,
   not by the maintainer.
2. **Post-fix re-run with original prompts: 10/20 strict = 50%.** Honest
   first-run number with the verdict parser fixed and no other changes.
   Below the 60% ship-gate by 10pp. Diagnosis: the EXTRACT_PROMPT asks
   the model for "one rule" from up-to-16k chars of source content but
   never tells it _which_ rule. In multi-rule project notes (one file
   often documents several fixes), the model picks the first observable
   rule, not the one the case bank expects.
3. **Pass 1, query-conditioned extraction: 14/20 strict = 70%.** Threaded
   the case's `trigger_phrase` into the extraction prompt so the model is
   asked to find the rule that addresses _this specific_ trigger, not an
   arbitrary one. This is the production semantics of schema retrieval —
   real queries are query-conditioned — so it is a methodological
   correction, not tuning. Gate PASS by 10pp. Extract latency also
   dropped from ~6s to ~2.7s per call because the model converges
   faster with a target.
4. **Pass 2, cross-model judge stress test: 1/20 strict = 5%.** Swapped
   judge from `gemma3:4b` (extractor's own family) to `qwen2.5:7b`.
   Reading the judge's verdicts: it correctly identifies that the
   generated rule says `QSG_RHI_BACKEND=gl` (matching the expected) but
   marks MISMATCH because the generated text adds a related env var and
   the formatting differs. Same model on both sides over-agrees on
   wording; a different model under-agrees on wording. Neither is
   judging substance. **Judge calibration is its own black box that
   needs its own validation set** — assuming a same-model judge is
   "viable cheap proxy" because κ=0.47 was measured upstream is not
   equivalent to assuming any cross-model judge will work without
   prompt tuning.

What ships: Pass-1 default (query-conditioned extract + same-model
gemma3:4b judge, 70% PASS). The cross-model 5% number is documented
as the next problem on the roadmap, not as a number to lead with.

Adjacent code review by an independent model also surfaced four
non-blocker findings (multiline value truncation in `_parse_case_block`,
non-atomic bank file writes, no path-boundary check in `_resolve_ref`,
prompt-injection surface via `{generated}` interpolation in the judge
prompt). These are filed in `docs/schema-extraction.md` under Honest
limitations and roadmap, not silent.

### Added — 2026-05-22 "The substrate is structurally personal" section

Mini-section inserted between consumer table and Headline. Four
structural properties (local persistence / anti-drift labeling /
per-user predictor / multi-consumer substrate) explain why this
substrate is a different *category of object* from a vendor-shipped
memory feature — descriptive claim, not moat claim. Frames the
compaction-headline numbers that follow in a substrate-not-feature
register.

### Repositioning — 2026-05-22 substrate-first README

The README headline now leads with **the substrate as artifact**;
compaction is documented as the first published consumer rather than
the project's primary identity.

- New top section "**The substrate is the artifact**" — explains that
  `~/.claude/projects/` is parsed once into per-pair objects decorated
  with seven signals, and that file lives at
  `$XDG_DATA_HOME/weighted-compact/`.
- New table "**Consumers reading this substrate today**" — lists five
  readers with honest per-row status:
  - Compaction layer (`build_compacted_context()` library + `qa-gate`
    harness) — shipped, this repo. Standalone session-start CLI is the
    next-targeted feature (W2 ambient render).
  - misstep — stumble predictor, AUC 0.665 on maintainer corpus, **not
    yet public**.
  - session-narrative — Layer 1-5 long-form recall, **in development,
    private**.
  - FKMF — methodology + skill, no shipped binary.
  - misstep-foreign-models — design phase, pre-implementation.
  Only compaction is published; the other four are listed because they
  prove the substrate has more than one reader, not as available
  tooling.
- Compaction-specific headline (8-pp gap vs `/compact` simulator, null
  vs cheap structured baselines) moved under `## Headline (compaction
  consumer)` — same data, narrower scope.
- "The case" rewritten as **"The case for a substrate, not a
  feature"** — the substrate's value is multi-reader infrastructure;
  compaction is the most tractable proof point because it has a
  fidelity loop.
- Honest-limitations addition: **`/compact` comparator is a local-LLM
  simulation**, not actual Claude Code `/compact`. Capturing real
  `/compact` output is the single v0.3 change that would harden the
  headline most.
- Honest-limitations addition: **four of five consumers are not shipped
  here.** Substrate format is the contribution; the other readers
  support the architectural claim but are not available tools.
- Status table updated: rows reflect substrate-builder vs compaction
  reader split; new row for "Substrate consumed by external readers"
  with format-stable / readers-private status.
- Daily-user "Pick your door" angle reframed: substrate parses every
  correction; compaction reader is one use; v0.3 cross-session
  correlation is where substrate compounds.
- No code changes. Pipeline, harness, install path unchanged.

### Measured — 2026-05-21 baseline comparison

First end-to-end comparison run against the seven-signal mixture under
the cheap-judge proxy (gemma3:4b, N=62, k_drop=0.5):

| Method | Per-Q fidelity (judge-yes) |
|---|---:|
| Random selection | 12.9 % (8/62) |
| 7-signal mixture | 11.3 % (7/62) |
| Recency-only | 11.3 % (7/62) |
| Cosine retrieval (e5) | 11.3 % (7/62) |
| Density (single signal) | 9.7 % (6/62) |
| BM25 retrieval | 9.7 % (6/62) |
| qwen-summarized `/compact` analog | 3.2 % (2/62) |

Headline findings:

- **Structured selection of any kind beats LLM-summary `/compact` by
  ~8 pp.** This is the strongest signal in the table and survives the
  κ=0.47 cheap-judge envelope easily.
- **Mixture vs cheap structured baselines: not measurable at N=62.**
  Random, recency, cosine all match the mixture within ±1 question.
  The pre-registered "broad highlight" target (Δ ≥ +0.05 vs cheap
  baseline) is not met. Narrative shifts to **tight register** per
  the project's pre-registered decision matrix.
- The 8-pp `/compact` gap is the value-prop the mixture's architecture
  earns at present. The within-structured ranker edge remains an open
  v0.3 question pending Sonnet re-judge and larger N.

Results JSON: `<substrate>/baseline_results.json`.

### Added — baselines harness

- **`weighted_compact/baselines/` package** with six baseline rankers
  for fidelity comparison against the seven-signal mixture:
  - `random_ranker`, `recency_ranker` — static drop-in npz (Phase 1)
  - `cosine_ranker`, `bm25_ranker` — query-aware, per-Q context (Phase 2)
  - `compact_simulator` — full-history LLM summary bypass:
    `compact_qwen` (Ollama, default) + `compact_sonnet` (Anthropic API,
    opt-in via ANTHROPIC_API_KEY) (Phase 3)
- **`build_compacted_context` refactored** to accept either a static
  scoring dict OR a callable `scoring(query) -> dict[pair_idx, float]`
  for query-aware rankers. Backward-compatible.
- **CLI**:
  - `weighted-compact baseline build --ranker {random|recency}`
  - `weighted-compact baseline run-all` — sequential evaluation of all
    rankers against the same qa_set, emits
    `<substrate>/baseline_results.json`
  - `weighted-compact qa-gate --ranker` choices extended to
    `{importance|density|random|recency|cosine|bm25|compact_qwen|compact_sonnet}`
- **Optional extras**: `[baselines]` (sentence-transformers + rank-bm25),
  `[baselines-cloud]` (anthropic). Lazy imports keep static-baseline
  cold-start cost unchanged.
- **Tests**: `tests/test_baselines.py` — 15 tests covering build, load,
  reproducibility, query-aware contract, BM25 lexical match,
  `/compact`-bypass dispatch via `is_compact_bypass` marker. 40 tests
  pass total.
- **Documentation**: `docs/baselines.md` — methodology, fairness
  disclosures, honest revert commitment.

### Tests

- **CI regression-guard for v0.2.0-beta.2 batch.** Added `tests/test_security.py`
  (V1 Host-header allowlist + V2 bearer-token on `/api/*`, token-file 0600,
  token persistence across reload), `tests/test_signals.py` (M3
  `extract_density` ↔ `FEATURE_NAMES` sizing; C2 7-signal composition;
  graceful degradation when `features_misstep.npz` absent vs. present),
  `tests/test_recon_eval.py` (C1 `judge.verdict` accounting +
  `passed_substring` exposure; empty-corpus zero-division). 12 → 25 tests.

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
  input/output/entry` contract docstring.
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
