# Span-level annotation

Beyond binary keep/drop on whole turns, you can drag-select a character
range inside a turn and tag it with one of four tiers. This gives the
compactor **sub-turn granularity** — preserve only the load-bearing spans
verbatim, gist the rest.

## The four tiers

| Tier | Meaning | Mixture weight | Render behavior |
|---|---|---|---|
| `keep` | Verbatim. Don't paraphrase. A path, a number, a name, a quote. | `+0.20` | Preserved char-by-char |
| `maybe` | Keep if budget permits. Mid-tier signal. | `+0.10` | Preserved when budget allows |
| `skip` | Drop with high confidence. Filler. | `−0.15` | First to go under pressure |
| `think` | Preserve and flag for re-examination later. Open thread. | `+0.05` | Marked visibly in render |

## UI interaction

Inside the labeler at `:18890/`:

1. Click a turn to focus it.
2. Drag-select a character range.
3. A four-button popup appears: KEEP / MAYBE / SKIP / THINK.
4. Click → the range gets a colored underline and is appended to
   `inline_annotations.jsonl`.
5. Click the underline to remove (soft-delete via tombstone).

Keyboard shortcuts for the **whole pair** stay on `k / m / s / x`:

| Key | Action |
|---|---|
| `k` | Mark whole pair `keep` |
| `m` | Mark whole pair `maybe` |
| `s` | Mark whole pair `skip` |
| `x` | Mark whole pair `false_positive` (= bug, not signal) |

Pair-level shortcuts and span-level annotations coexist. A pair can have
both a pair label (`keep`) *and* explicit spans that say "but this part is
really `skip`." The mixture handles both.

## On-disk format

`inline_annotations.jsonl` is append-only with tombstone soft-delete:

```jsonl
{"id": 1, "pair_idx": 17, "side": "correction", "char_start": 24, "char_end": 89, "marker": "keep", "note": "", "ts": 1747500000}
{"id": 2, "pair_idx": 17, "side": "premise",    "char_start": 0,  "char_end": 12, "marker": "skip", "note": "", "ts": 1747500030}
{"id": 1, "pair_idx": 17, "deleted": true, "ts": 1747500120}
```

`tool.py` replays the journal at startup, applying tombstones to mark
entries `deleted`. Filter-out happens after the replay so deletion is
non-destructive — the original ranges stay in the file for forensic
inspection.

## Inline-syntax bootstrapping

If you type `(маркер)`, `(подумать)`, or `(mark)` inside a live Claude
Code session, the bootstrap auto-queues the surrounding turn for
canonicalization. The map between inline syntax and canonical tier lives
in `tool.py:INLINE_SYNTAX_MAP`:

```python
INLINE_SYNTAX_MAP = {
    '(маркер)':                 'keep',
    '(маркер - нейтральный)':   'maybe',
    '(mark)':                   'maybe',
    '(подумать)':               'think',
    '(пропос)':                 'think',
}
```

Other languages: add patterns to `extract_pairs.MARKER_PATTERNS` and mirror
canonical tiers here. This is a deliberately small map — labels are user
decisions, not autopilot.

## Why character-fraction, not character-count

Two pairs can have identical absolute keep-coverage but very different
relative coverage. A 200-character correction with 100 KEEP chars
(`frac = 0.5`) is mostly load-bearing. A 4000-character correction with
the same 100 KEEP chars (`frac = 0.025`) has only a small load-bearing
slice. The mixture should weight the *first* more heavily — and `_frac`
does that automatically.

The mixture math:

```
span_keep_corr_frac = sum(keep span char ranges on correction)
                      / len(correction_text)
```

clipped to `[0, 1]` (a single span can't exceed the turn it's on).

## Downstream impact on render

This is the part that is most underutilized in v0.0.01.

Today, `recon_qa.build_compacted_context` picks top-K pairs by importance
and inlines them verbatim. The next iteration (W2 ambient render, planned
v0.1) will:

- Preserve KEEP spans verbatim.
- Gist non-annotated regions into 30–80% length.
- Drop SKIP spans entirely.
- Wrap THINK spans in `<!-- think: ... -->` so future sessions surface
  them.

Estimated token saving at typical span coverage: **5–15× on chatty
assistant turns**. This is the lever the project is leaning on.

## Forensic notes

`inline_annotations.jsonl` is the highest-fidelity record of *what the
user found important inside their own session*. Treat it as personal
data of the highest sensitivity — it tells someone reading it exactly
which parts of which conversations the user thought were load-bearing.

The framework `.gitignore` blocks the file from public repos. The
contributor policy in `CONTRIBUTING.md` refuses PRs containing this file
on sight.
