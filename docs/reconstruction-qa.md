# Reconstruction-QA

Compression without measurement is wishful thinking. weighted-compact
ships with a reconstruction-QA loop that takes a compacted context,
attempts to reconstruct the original meaning, and scores the fidelity.

This is the part most other tools skip entirely. They assert traceability
and hope the compression is faithful.

## The loop

```
1. SAMPLE       Pick a session, compact it with the current importance
                weights at a target budget (e.g. 8000 chars).
2. SAVE         Persist the compacted context to recon_qa_set.jsonl
                with provenance: weight vector, budget, session id.
3. EVAL         Ask a local LLM (Ollama qwen2.5:7b by default) to
                reconstruct the original meaning from the compacted
                context alone. Score reconstruction against the original
                via a separate judge model (gemma3:4b by default —
                cross-model anti-bias).
4. SUGGEST      For low-fidelity reconstructions, propose alternative
                spans to keep / drop based on which entities were missed.
```

All four steps run locally. There is no cloud dependency. The default
models are local Ollama defaults; override via environment variables:

```bash
WEIGHTED_COMPACT_OLLAMA_URL=http://localhost:11434/api/generate
WEIGHTED_COMPACT_RECON_MODEL=qwen2.5:7b
WEIGHTED_COMPACT_JUDGE_MODEL=gemma3:4b
WEIGHTED_COMPACT_SUGGEST_MODEL=qwen2.5:7b
```

## Cross-model anti-bias

Reconstruction and judging use different models on purpose. If the same
model generated both the reconstruction and the score, the score would
correlate with how the model thinks the reconstruction *should* look —
not with how it actually does. Using two different models breaks that
loop.

In practice this means: if you have a strong opinion about which model
to use for reconstruction, set `WEIGHTED_COMPACT_JUDGE_MODEL` to a
different family. qwen × gemma is the default because they have very
different training distributions; llama3 × qwen is another good pair.

## Iter-chain QC layer 1

For multi-iteration reconstruction (where you ask the model to "refine"
or "deepen" a previous attempt), `recon_qa.iter_chain_metrics` computes
the semantic drift between iterations:

```python
ITER_MODE_RANGES = {
    'complement': (0.45, 0.78),  # new aspects → moderate cos-sim
    'refine':     (0.78, 0.93),  # paraphrase → high sim, same intent
    'deepen':     (0.60, 0.85),  # continuation → mid-high sim
}
```

If the cos-similarity between iter[N] and iter[N-1] falls outside the
expected range for the declared mode, the UI surfaces a drift warning.
This catches the failure mode where the model starts paraphrasing instead
of refining (cos-sim shoots above 0.93) or wanders off topic
(cos-sim drops below the lower bound).

The expected ranges are heuristic; calibrate on your own model pair after
50+ baseline samples.

## The baseline accumulation problem

The recon-QA loop needs ~50 baseline samples before its scores stabilize.
The first labeling session is exploratory — you're producing data the
loop will use, not consuming verified output.

This is fine, but it does mean: **do not trust recon-QA scores on the
first day**. After your first 50 samples, the scores become informative.
Before that, they're collecting signal.

The UI is honest about this: the recon-QA tile shows a `baseline:
N / 50` counter and dims confidence indicators below the threshold.

## How recon-QA feeds back into the mixture

It doesn't, directly. Recon-QA is the **gate**, not the optimizer. If a
weight change improves recon-QA scores, the user manually updates the
mixture in `importance.py:WEIGHTS`. There is no automated gradient
descent on the mixture weights.

This is deliberate. Automated optimization of the mixture against the
recon-QA scores would close the Goodhart loop — the mixture would start
optimizing for whatever the recon-QA loop happens to measure, instead of
preserving content. Manual updates keep the human in the loop and
preserve the multi-source independence that the mixture was designed
for.

A future grid-search tool (`weighted-compact eval --search`) is planned
post-beta, but it will surface candidates for human review, not commit
weight changes automatically.

## Failure modes

| Symptom | Likely cause | Remedy |
|---|---|---|
| Scores flat at 0.5 ± 0.05 | Judge model unavailable or returning canned text | Check `WEIGHTED_COMPACT_JUDGE_MODEL` is pulled in Ollama |
| Scores high but reconstructions miss key entities | density signal under-weighted | Raise density coefficient, re-run recon-QA |
| Iter-chain drift warnings on every refine | ITER_MODE_RANGES miscalibrated for your model pair | Adjust ranges based on observed sims |
| Suggest always returns "no changes" | Coverage too sparse — model can't identify missing entities | Run more bootstrap labeling, ensure density signal active |

## Privacy

The recon-QA loop calls a local Ollama instance. Nothing leaves the host.
The compacted contexts in `recon_qa_set.jsonl` contain conversation
excerpts and are treated as substrate (gitignored, never published).

If you point `WEIGHTED_COMPACT_OLLAMA_URL` at a remote LLM service, you
opt out of the local-only invariant. This is your decision; the tool
will not stop you, but the privacy guarantees of [`invariants.md`](invariants.md)
no longer apply.
