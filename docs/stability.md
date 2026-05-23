# Stability promise

> **TL;DR.** From `v0.2.0` forward, the surfaces listed below will not change
> shape through `v1.0`. Additions are allowed; renames or removals constitute
> a major version bump.

weighted-compact is in `0.2.x` beta. Internal arithmetic
(signal weights, decay constants, judge prompts) is still being tuned —
expect those numbers to move release-to-release. What follows is the set
of surfaces an external consumer or plugin author can pin against
without re-reading the changelog every week.

## What is stable

- **`weighted_compact.recon_qa.__all__`** — every name re-exported from
  the `recon_qa` package is stable through `v1.0`. That covers
  `build_compacted_context`, `build_compacted_context_with_meta`,
  `run_eval`, `classify_difficulty`, `load_pairs`, `load_importance`,
  the QA-set helpers, the constants (`OLLAMA_URL`, `MODEL`,
  `JUDGE_MODEL`, `SUGGEST_MODEL`, the path constants), and the `Signal`
  Protocol.
- **`weighted_compact.ranker`** — `RANKER_REGISTRY`, `RankerSpec`,
  `register`, `list_rankers`, `get_ranker` and `Signal` (re-exported
  from `weighted_compact.recon_qa`) are the documented plugin surface
  and stable through `v1.0`. Third-party packages that register a new
  ranker via `@register("name", ...)` or `RANKER_REGISTRY.add(...)`
  can rely on those entry points not moving.
- **`weighted_compact.recon_qa.context.build_compacted_context_with_meta`**
  — function signature (positional + keyword parameters) and the
  returned `(markdown, meta)` tuple shape are stable through `v1.0`.
  New optional keyword arguments may be added; existing ones will not
  change name or default value. The `meta` dict gets new keys over
  time; existing keys keep their semantics.
- **CLI verb names** — every subcommand listed in
  `weighted-compact --help` is stable from `v0.2.0` forward. New verbs
  may be added (e.g. `weighted-compact rankers` was added in `v0.2.0`),
  but `bootstrap`, `serve`, `mcp-serve`, `compat`, `metrics`,
  `install-units`, `train`, `eval`, `qa-gate`, `importance`, `paths`,
  `rem-pass`, `baseline build`, `baseline run-all` and `rankers` will
  not be renamed without a major version bump.
- **MCP tool names** — `search_pairs`, `compact_session`,
  `substrate_info` exposed by `weighted-compact mcp-serve` are stable
  under the same rule.

## What is *not* covered

- Default weights in `WEIGHTS` in `weighted_compact/importance.py`.
  These are being tuned against the reconstruction-fidelity gate; expect
  movement between minor versions until `v1.0`.
- Judge prompts and `JUDGE_MODEL` / `SUGGEST_MODEL` defaults. The model
  identifiers are subject to local-availability churn.
- Internal modules under `weighted_compact._*` or any name starting
  with an underscore. Those are the substrate's own scaffolding and may
  change without notice.
- The on-disk format of `pairs.jsonl`, `features.npz`, `importance.npz`
  and friends. There is a `SCHEMA_VER` fingerprint mechanism for these —
  see the `Added — 2026-05-23 npz schema fingerprint` entry in
  `CHANGELOG.md`. The fingerprint is the stability contract for the
  files; the field layout itself is not pinned.

## Reading the changelog

Every breaking change to any of the above surfaces will be flagged in
`CHANGELOG.md` under a `### Changed` heading and prefixed with
`BREAKING:`. If you are pinning against a stable surface, grep the
changelog for that prefix between your installed version and the
candidate upgrade.
