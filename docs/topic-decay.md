# Topic-aware compaction

A multi-topic session compresses badly under naive top-K importance. If
you spent half the session on topic A and half on topic B, the top-K
slice will mix spans from both topics together — which is what the model
will see, and which is almost never what the user wanted.

weighted-compact addresses this with an **unsupervised topic segmentor**
plus an exponential decay over cross-topic distance.

## The segmentor

`topic_segments.py` implements a TextTiling-style sliding-window cohesion
scorer over the e5 correction embeddings.

For each pair position `i` within a session-ordered sequence:

```
left   = mean(embed[i-W : i])
right  = mean(embed[i : i+W])
cohesion(i) = cos(left, right)
```

Locations where cohesion drops sharply below the local rolling baseline
are marked as topic boundaries. Each pair gets a `topic_id` by counting
how many boundaries precede it within its session.

Default hyperparameters (in `topic_segments.py`):

```python
WINDOW        = 2     # turns on each side of position i
DROP_QUANTILE = 0.20  # cohesion ≤ this quantile fires a boundary
```

Output: `topic_segments.npz` with `pair_indices`, `topic_id`,
`session_pos`, `cohesion`, `is_boundary`, plus a `meta` dict capturing
the hyperparameters used.

**No classifier**. Pure geometry. Disabling the segmentor (e.g. when
`features.npz` is small) collapses everything to `topic_id=0` and the
decay becomes a no-op.

## The decay

`recon_qa.build_compacted_context` weights each pair by an exponential
decay over topic distance:

```
effective_score(pair_i, current_topic) =
    importance(pair_i) × topic_decay ** |Δtopic|
```

where `Δtopic = pair_topic_id - current_topic_id`, and `topic_decay` is a
slider in the UI (default `0.5`).

| `topic_decay` | Effect |
|---|---|
| `1.0` | No decay — all topics weighted equally (legacy behavior) |
| `0.5` | Each topic step halves the score |
| `0.3` | Aggressive — three steps drops to ~3% |
| `0.0` | Drop everything outside the current topic entirely |

The intuition: when you're working on topic B, spans from topic A are
context, not core. They get a quieter weight. When you return to topic A
later, the decay reverses (`|Δtopic|` is small again).

## Verified compression ratio

On a verified multi-topic session in the target corpus:

| Setting | Compacted size |
|---|---|
| `topic_decay = 1.0` (off) | 4597 chars |
| `topic_decay = 0.3` | 2658 chars |

~42% compression at `decay=0.3` versus disabled, with no loss in
reconstruction quality (verified via `recon_qa.eval` on the same
session).

## When the segmentor fails

The segmentor is unsupervised — it can miss boundaries you would have
called or fire boundaries you wouldn't. Two known failure modes:

1. **Monotopic sessions** — the segmentor finds spurious boundaries when
   the whole session is one topic. The drop-quantile filter catches most
   of these (`DROP_QUANTILE=0.20` means only the bottom 20% of cohesion
   scores can fire boundaries), but tight homogeneous sessions can still
   produce 2–3 fake topics. In the target corpus, 9 / 198 sessions had
   detected boundaries; the rest collapsed cleanly to one topic.

2. **Tool-output flooding** — a long sequence of bash output between two
   conversational turns can look like a topic boundary because the
   embedding of tool output differs from prose. Mitigation: the bootstrap
   filters `<bash-stdout>`, `<bash-stderr>`, `<command>`, `<task-notification>`,
   `<system-reminder>` and similar prefixes before embedding. See
   `extract_pairs.SKIP_PREFIXES`.

If you find a failure mode the segmentor consistently mishandles, file an
issue with the cohesion plot from `weighted-compact compat --topic-debug`
(planned for v0.1).

## Tuning

```bash
# Recompute with non-default hyperparameters
WEIGHTED_COMPACT_TOPIC_WINDOW=3 \
WEIGHTED_COMPACT_TOPIC_DROP_QUANTILE=0.15 \
    python -m weighted_compact.topic_segments
```

The UI surfaces the cohesion plot for the current session under the
labeler's "topic" tab. Boundaries appear as vertical bars; the
drop-quantile threshold is the horizontal line.

Default `WINDOW=2` works well for short conversational turns. For
sessions dominated by long technical explanations, raise to `WINDOW=3`
or `4` to smooth out single-turn variance.
