# Extension recipe: writing a new ranker

> **Goal.** Walk through adding a new ranker — a function that scores
> pairs by `len(correction_text) / len(premise_text)` — from a separate
> Python package. End-to-end: write it, install it, run the gate against
> it, compare to the built-ins.

This is the supported plugin surface. The eight rankers that ship with
weighted-compact (`importance`, `density`, `random`, `recency`, `cosine`,
`bm25`, `compact_qwen`, `compact_sonnet`) all register through the same
mechanism described here. Nothing about them is privileged.

For the formal stability contract on `weighted_compact.ranker`, see
[stability.md](stability.md).

---

## 1. The shape of a ranker

A ranker is registered as a **loader function** — a zero-arg callable
that returns one of three things:

| Returned shape | When to use it | Example built-in |
| --- | --- | --- |
| `dict[int, float]` — pair_idx → score | Static: scores precomputed once for the whole substrate. | `importance`, `density`, `random`, `recency` |
| `Callable[[str], dict[int, float]]` — query → scores | Query-aware: scores recomputed per question. | `cosine`, `bm25` |
| Object with `.is_compact_bypass = True` and `.summarize_excluding(source_pair_idx, pairs, query=...)` | `/compact`-style: skip pair selection, hand the assembled summary directly to the QA loop. | `compact_qwen`, `compact_sonnet` |

The first shape is the simplest and what we'll build below.

---

## 2. Create the plugin package

External package layout:

```
wc-length-ranker/
├── pyproject.toml
└── wc_length_ranker/
    ├── __init__.py
    └── length_ranker.py
```

`wc_length_ranker/length_ranker.py`:

```python
"""Length-ratio ranker — a worked example of the weighted-compact plugin surface.

Scores each pair by len(correction_text) / max(1, len(premise_text)).
Premise = the user message the model answered; correction = the model's
reply (or the user's correction of it). The ratio is a crude proxy for
"how much the model had to elaborate" — high values are usually long,
substantive responses, low values are short acknowledgements.
"""
from weighted_compact.ranker import register


@register(
    name="length",
    description="Pair score = len(correction_text) / len(premise_text).",
    requires_extras=(),       # pure stdlib + numpy, no extras needed
    query_aware=False,        # static dict — same scores for every Q
    since_version="0.1.0",    # of the plugin package, not weighted-compact
)
def load_length_ranker():
    """Loader: build the {pair_idx: score} dict from pairs.jsonl.

    Called once per `run_eval` invocation. If your ranker is expensive
    (a model load, an index build) cache the result inside the loader
    — `run_eval` does not memoise across calls.
    """
    from weighted_compact.recon_qa.context import load_pairs

    pairs = load_pairs()
    scores: dict[int, float] = {}
    for p in pairs:
        premise = p.get("premise_text", "") or ""
        correction = p.get("correction_text", "") or ""
        scores[p["pair_idx"]] = len(correction) / max(1, len(premise))
    return scores
```

`wc_length_ranker/__init__.py`:

```python
"""Side-effect import: pulls the @register decorator on the module."""
from . import length_ranker  # noqa: F401
```

`pyproject.toml`:

```toml
[project]
name = "wc-length-ranker"
version = "0.1.0"
dependencies = ["weighted-compact>=0.2.0"]

[project.entry-points."weighted_compact.rankers"]
length = "wc_length_ranker.length_ranker"

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"
```

The `entry-points` block isn't required for the registration to work —
the `@register` decorator runs on import either way — but it's a clean
hook for an autoloader if you want one in your `~/.claude/` boot.

---

## 3. Install it

From inside `wc-length-ranker/`:

```sh
pip install -e .
```

Then **import** the module once so the decorator fires. Two ways:

```sh
# Option A — explicit import in a one-shot Python invocation.
python -c "import wc_length_ranker; \
           from weighted_compact.cli import main; \
           main(['rankers'])"

# Option B — a wrapper script you keep in ~/.local/bin/ that imports
# the plugin before delegating to the real CLI.
cat > ~/.local/bin/wc-with-plugins <<'EOF'
#!/usr/bin/env python3
import wc_length_ranker  # noqa: F401  — registers length ranker
from weighted_compact.cli import main
main()
EOF
chmod +x ~/.local/bin/wc-with-plugins
```

After either, `weighted-compact rankers` (or `wc-with-plugins rankers`)
prints the new entry alongside the eight built-ins:

```
name             query_aware  since    extras / description
-----------------------------------------------------------
bm25             True         0.1.0    [baselines] Phase 2 baseline: BM25 lexical relevance to the query.
compact_qwen     True         0.1.0    [-] /compact-style: local Ollama qwen2.5:7b summary replaces selection.
compact_sonnet   True         0.1.0    [baselines-cloud] /compact-style: Anthropic API Sonnet summary (requires API key).
cosine           True         0.1.0    [baselines] Phase 2 baseline: e5 dense cosine similarity to the query.
density          False        0.1.0    [-] Legacy fallback — mean of 16 density features only.
importance       False        0.1.0    [-] Seven-signal mixture (misstep+density+labels+spans). Default.
length           False        0.1.0    [-] Pair score = len(correction_text) / len(premise_text).
random           False        0.1.0    [-] Phase 1 baseline: uniform random scores per pair_idx (seeded).
recency          False        0.1.0    [-] Phase 1 baseline: rank by within-session position (most recent wins).
```

---

## 4. Use it

```sh
weighted-compact qa-gate --ranker length --signal judge --easy-k 0.0 --hard-k 0.9
```

`qa-gate` validates `--ranker` against `RANKER_REGISTRY` at runtime, so
plugin names work the same as built-ins. The same name flows through to
`weighted-compact baseline run-all --include length,importance,density`
for a side-by-side fidelity comparison.

---

## 5. Variant: a `Signal`-shaped contribution

If you want your length-ratio to be a *signal in the mixture* rather
than a standalone ranker, implement the
[`Signal` Protocol](../weighted_compact/importance.py) instead. The
Protocol is small:

```python
from weighted_compact.recon_qa import Signal  # re-export
import numpy as np


class LengthRatioSignal:
    """Conforms to weighted_compact.recon_qa.Signal."""
    name = "length_ratio"

    def __init__(self, pairs):
        self._pairs = {p["pair_idx"]: p for p in pairs}

    def compute(self, pair_indices) -> np.ndarray:
        out = np.zeros(len(pair_indices), dtype=np.float32)
        for i, pid in enumerate(pair_indices):
            p = self._pairs.get(int(pid))
            if p is None:
                continue
            premise = p.get("premise_text", "") or ""
            correction = p.get("correction_text", "") or ""
            ratio = len(correction) / max(1, len(premise))
            # Clip to [0, 1] for mixture composition.
            out[i] = min(1.0, ratio / 10.0)
        return out


assert isinstance(LengthRatioSignal([]), Signal)  # runtime_checkable
```

The current `importance.py` mixture composes its seven signals as raw
numpy arrays for performance — it doesn't iterate `Signal` instances at
runtime. The Protocol documents the shape *external* contributors
should adopt when they fork the mixture or build their own. Use the
ranker registry above (Step 2-4) when you want a self-contained plugin
that's selectable from the CLI; use `Signal` when you want to publish a
reusable component that downstream mixtures can compose.

---

## 6. Why the surface exists — comparison to claude-mem

In a plugin-aware design like weighted-compact, the four steps above
are all you need. `RANKER_REGISTRY` is documented (this file +
[stability.md](stability.md) + the dataclass docstring in
`weighted_compact/ranker.py`), the decorator is one import, and the
CLI verb picks up your name without modification.

[claude-mem](https://github.com/claude-mem/claude-mem) is the closest
adjacent project. It has no equivalent public surface for plugging in
a custom ranker — the closest you can get is its hook system, which
operates on the assembled output, not on the ranking step that *built*
the output. Concretely, to add a length-ratio ranker to claude-mem you
would need to:

1. Fork the repository.
2. Locate the internal scoring function (it isn't exposed in the
   public API; it lives inside a private module).
3. Patch the scoring callsite to dispatch on a name.
4. Maintain the fork against upstream releases.

Or alternatively, register a hook that *post-processes* the output —
but the output is already a summarised compaction, so by the time the
hook runs the ranking decisions have been baked in. You can't undo a
ranking from the outside.

The weighted-compact registry sidesteps this entirely: the eight
built-in rankers are registered through the same `@register` decorator
your plugin uses (see `weighted_compact/recon_qa/fidelity.py` at the
bottom for the eight calls). Nothing about them is privileged. Adding a
ninth costs you four lines of decorator-and-loader, not a fork.

---

## 7. Where to read next

- [stability.md](stability.md) — the formal contract on
  `weighted_compact.ranker`, `RankerSpec`, `Signal`, and the CLI verb
  names.
- [importance-mixture.md](importance-mixture.md) — what the seven
  built-in signals are and how they're weighted.
- [reconstruction-qa.md](reconstruction-qa.md) — the gate your new
  ranker will be measured against (`weighted-compact qa-gate
  --signal judge`).
- `weighted_compact/ranker.py` — the source. ~150 lines including
  docstrings; readable in a single sitting.
