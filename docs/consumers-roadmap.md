# Consumers roadmap

Three consumers ship in the weighted-compact repository today: the
compaction reader (`build_compacted_context_with_meta`), schema
extraction (`weighted-compact schema`), and recap
(`weighted-compact recap`). The first two are exercised against the
reconstruction-fidelity harness; recap is validated by a different bar —
four faithfulness invariants re-checked per session (`recap --audit`),
holding on 985/985 of the maintainer's corpus (see [`recap.md`](recap.md)).
All three are available as soon as you `pipx install` the package.

Recap is a consumer of the raw session source rather than of the computed
`importance.npz` substrate — it proves the *source* has more than one kind
of reader, the same way the four below prove the *scored substrate* does.

This file lists the **additional readers** of the same substrate that
are in development in adjacent projects. They are listed here, not in
the main README, because nothing about this repo's install path or
runtime depends on them — they prove the substrate has more than two
consumers, but they are not part of the v0.2.0 ship surface.

## In flight

| Consumer | Surface | Status |
|---|---|---|
| **misstep** — stumble prediction | per-user `P(stumble)` from correction embeddings; external optional signal | separate project, currently private; held-out AUC 0.665 on the maintainer corpus. Removed from the default six-signal mixture on 2026-06-07 (AUC ~0.66–0.70, near chance; absent on fresh installs). `importance.py` no longer reads `features_misstep.npz`. The trainer remains the unshipped piece; misstep may re-enter as an optional overlay if AUC improves. |
| **session-narrative** — Layer 1-5 long-form recall | concept extraction → semantic grep → importance → narrative; reads the same per-pair substrate to build per-session retrospectives | in development, private |
| **FKMF** — knowledge-gap retrieval | two-layer active + background lookup for *fundamental missing fragments* — pairs the user keeps re-explaining across sessions | methodology + skill spec exists; no shipped binary |
| **misstep-foreign-models** — refusal-drift lens | uses the substrate as a baseline to detect when 3rd-party LLM sessions exhibit refusal patterns the maintainer's local model does not | design phase, postulates frozen, pre-implementation |

## What this list is for

It is not a feature promise. It is an existence proof that the
substrate format (`pairs.jsonl` + `features_*.npz` +
`importance.npz` + `rem_decay.npz`) is being read by multiple
independent codebases. That is the architectural claim — the
substrate is the interface, and the interface has multiple
consumers. Whether or not you ever run any of the four listed here,
the same substrate is the thing the two shipped readers compute on.

If you intend to *write a fifth consumer*, the canonical entry points
are:

```python
from weighted_compact.recon_qa.context import (
    load_pairs, load_importance, load_topic_map, load_rem_decay,
    build_compacted_context_with_meta,
)
```

The npz schemas are documented in
[`docs/importance-mixture.md`](importance-mixture.md) and
[`docs/rem-decay.md`](rem-decay.md). Schema-version fingerprints
(`schema_ver` field) shipped in v0.3 so consumers can refuse to read
files written by a newer mixture.

## Want one of the four shipped publicly?

Open an issue. The repo's `community-invitation` label tracks
maintainer-drafted scope: see issues #4–#18 for the first wave and
#19–#52 for the lens-driven second wave.
