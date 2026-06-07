# Pseudo-labels: compile → verify

**Status:** spec, pre-implementation. No code exists yet.

---

## Why this exists

`extract_pairs.py` finds correction-bearing turns by matching a small regex
set (`RE_NEG`, `RE_POS`, `RE_TAG`). The design was deliberate — explicit
user-typed markers were the cheapest reliable signal at project start. Two
years of running this in production have exposed the gap:

1. **Corrections without markers are silent.** A user who types "actually
   the flag is `--no-sandbox`, not `--sandbox`" does not fire any regex.
   The pair is never extracted, so the importance mixture never sees it,
   so compaction never prioritizes it.

2. **The marker requirement shifts cognitive burden onto the user.** Having
   to type `(mark)` or `stop` to signal a correction is a learned behavior
   that erodes over time. Users who do not train the habit produce thin
   substrates.

3. **No human can sit in the loop for every session.** The labeler at
   `:18890/` already handles the human-in-the-loop case for pair quality.
   What is missing is a path that produces usable ground truth from session
   structure alone, at scale, continuously.

The compile → verify pipeline replaces the marker requirement with detector-
derived evidence. It does not touch the existing `extract_pairs.py` path —
marker-detected pairs stay in `pairs.jsonl` as before. Pseudo-labels live
in a parallel file and feed an optional slot in the importance mixture.

---

## Architecture overview

```
~/.claude/projects/**/*.jsonl
         │
         ▼
  [compile]  structural detectors × 5
         │
         ▼
  candidate_pairs.jsonl    {pair_idx, session_id, detector, signal_excerpt}
         │
         ▼
  [verify]  gemma3:4b judge  (local, no outbound)
         │
         ▼
  pseudo_ground_truth.jsonl  {pair_idx, detector, judge_verdict, confidence}
         │
         ▼
  importance.py  slot 8 (weight 0.0 until ablated)
```

Both output files live under `$XDG_DATA_HOME/weighted-compact/`, alongside
the existing substrate files. They are append-only and gitignored.

---

## The compile half: detector set

Each detector is independent. They can be run individually or composed.
False positives are accepted at compile time — verification is the filter.

---

### D1 — Re-prompt delta

**Signal.** Consecutive user messages with edit distance > 0 and cosine
similarity > 0.80 (e5 embeddings). High similarity means the same intent;
non-zero edit distance means the user changed something. The change is the
correction.

**False-positive risk.** Auto-retry / multi-submit artifacts in the session
file look identical to this pattern. Mitigation: require the pair has an
intervening assistant turn of length ≥ 20 chars, and that the edit distance
touches at least one word boundary change (not just punctuation).

**Verification handle.** The verifier sees `(prior_assistant_turn,
user_turn_B)` where B is the edited re-prompt. The judge assesses whether
B corrects or clarifies something the assistant said, not whether B is just
a rephrasing of user_turn_A.

---

### D2 — Explicit negation (multilingual)

**Signal.** Regex over user turns for negation markers in the languages
present in the substrate. Not the same list as `RE_NEG` in `extract_pairs.py`
— this list is wider and includes RU/UA patterns that the existing EN-biased
regex does not cover.

Patterns (non-exhaustive, to be finalized in implementation):

```
EN:  \b(no|not that|not what|nope|wrong|incorrect|wait|stop|hold on|
         actually|revert|scratch that)\b
RU:  \b(нет|не так|не то|не правильно|стоп|подожди|нет-нет|
         не понял|отмена|верни|переделай)\b
UA:  \b(ні|не так|не те|стоп|зачекай|відміни|поверни)\b
```

**False-positive risk.** "No problem" or "не проблема" fire the negation
regex but are not corrections. Mitigation: require the negation token to
appear in the first 40 characters of the user turn, or to be followed by
an imperative clause within 15 tokens. Verification absorbs the residual.

**Verification handle.** Full `(prior_assistant_turn, user_turn)` context
to the judge.

---

### D3 — Tool-error → user fix

**Signal.** An assistant turn containing a tool_error result (the session
JSONL records tool call outcomes in the message content list) is followed
by a user turn whose edit distance from the tool invocation arguments is
> 0. The user is correcting a parameter, a path, or an assumption.

**False-positive risk.** Users sometimes acknowledge an error without
correcting it ("ok let me check that manually"). Mitigation: require the
user turn to contain at least one of: a path token, a quoted string, a
flag-like token (`--\w+`), or a numeric value that differs from the failed
call. Else skip.

**Verification handle.** The judge receives the tool_error text (first 300
chars), the failed call arguments (stripped to the relevant field), and the
user turn. Prompt: "Does the user turn correct or amend the failed tool
invocation?"

---

### D4 — Undo or edit-after-write

**Signal.** The assistant produced a file write or an edit block in a given
turn. Within the next two user turns (allowing one assistant turn
intervening), the user's turn contains one of: an explicit undo marker, a
request to revert a specific file, or a reference to the same filename with
a different content request.

Detection depends on reading the tool call result fields (`type: tool_result`,
`content[*].type: tool_use`, tool name `str_replace`, `write_file`, `edit`).

**False-positive risk.** "Can you also update that file with X" looks like
an edit-after-write but is an extension, not a correction. Mitigation:
require the user turn to reference the same file as the write, not a
different file.

**Verification handle.** The judge receives the written file path, the
assistant's stated intent for the write, and the user's follow-up.

---

### D5 — Embedding drift anomaly

**Signal.** For each consecutive `(user_i, user_{i+2})` pair (skipping the
assistant turn between them), compute cosine distance in the e5 embedding
space. Expected drift in normal conversation: roughly 0.05–0.25. Pairs
where drift exceeds threshold (provisional: > 0.40) after an assistant turn
are flagged — the user's intent shifted sharply, which correlates with
the assistant having pulled the conversation in an unwanted direction.

This is the only detector that operates on the latent space rather than the
surface text. It catches corrections that are framed as entirely new
requests ("actually, let's approach this differently") rather than negations.

**False-positive risk.** High drift is also produced by topic changes that
are *not* corrections — the user just moved on. Mitigation: require that
both user turns share at least one entity or path token (overlapping
vocabulary check, cheap BM25-style). Without shared tokens, a topic change
is more likely than a correction.

**Verification handle.** Both user turns and the intervening assistant turn
are passed to the judge. The prompt asks specifically whether user_{i+2}
is correcting or redirecting something from the assistant turn, as distinct
from simply starting a new topic.

---

## The verify half: gemma3:4b judge

The recon-QA harness already runs `gemma3:4b` as the default cheap judge
(see `weighted_compact/recon_qa/judge.py`). The pseudo-label verifier
reuses the same Ollama endpoint and the same family contract — Gemma
judges, Qwen generates.

For each candidate pair produced by compile, the verifier issues a fixed
prompt:

```
System: You are a precise binary classifier. Answer only YES or NO.

User: Given this prior assistant turn:
<prior_assistant_turn>
{premise_text[:800]}
</prior_assistant_turn>

And this subsequent user turn:
<user_turn>
{correction_text[:400]}
</user_turn>

Is the user turn a correction, negation, or amendment of something in the
prior assistant turn? Answer YES or NO. Do not explain.
```

Output per candidate:

```jsonl
{
  "pair_idx": "...",
  "session_id": "...",
  "detector": "D1",
  "judge_verdict": "YES",
  "confidence": 0.87,
  "ts": "2026-05-23T04:00:00Z"
}
```

`confidence` is the softmax probability of the YES token from the Ollama
logprobs field, if available; otherwise `null`. Downstream consumers can
gate on confidence; the default import threshold is `judge_verdict == YES`.

The judge is the only verification step. There is no human gate.

---

## Calibration: the κ-handshake

Calibration is a one-time prerequisite before `pseudo-label verify` outputs
are considered usable. The gate is enforced at runtime: if the calibration
report is absent or older than 30 days, `verify` prints an error and exits.

The calibration protocol:

1. Draw 100 candidate pairs (or all available, if fewer) from
   `candidate_pairs.jsonl`.
2. Run `gemma3:4b` judge on each — same fixed prompt as above.
3. Run `claude-sonnet-4-6` judge on the same 100 — same fixed prompt,
   via the Anthropic API (requires `ANTHROPIC_API_KEY` in env).
4. Compute Cohen's κ between the two verdict sequences.
5. Write the report to `$XDG_DATA_HOME/weighted-compact/calibration_pseudo.json`:

```json
{
  "ts": "2026-05-23T04:00:00Z",
  "n": 100,
  "kappa": 0.52,
  "precision_gemma": 0.71,
  "recall_gemma": 0.54,
  "judge_local": "gemma3:4b",
  "judge_reference": "claude-sonnet-4-6"
}
```

Every subsequent `weighted-compact pseudo-label verify` run prints to
stderr, unconditionally:

```
[pseudo-label] verifier last calibrated against claude-sonnet-4-6
               at κ=0.520 on 2026-05-23 (100 samples).
               Calibration expires in 14 days.
```

Refusing to print this disclaimer, or suppressing it, is not an option
exposed by any flag. The κ number is the noise envelope on every downstream
claim made from pseudo-label outputs.

### Why 30 days?

The local judge model is fixed (`gemma3:4b`), but the Ollama-pulled weights
may be updated. Thirty days is conservative enough to catch a model swap
and short enough that calibration does not quietly expire across a major
version change.

### The bootstrap problem

Calibration requires one Sonnet API call over a 100-sample batch. This is
a real external dependency. The spec owns it: there is no path to a
calibrated verifier that avoids the Sonnet call. The call is opt-in via
`--against sonnet` and requires an explicit API key in env; the default
path (compile + verify) works without it, but the output is marked
`calibration: null` and the verifier prints a prominent warning rather than
fabricating a κ. Users who never run calibrate are explicitly told their
verdicts are uncalibrated.

---

## CLI surface

Three subcommands under the `pseudo-label` group, added to `cli.py`.

```bash
# 1. Run detectors over session files; emit candidate pairs.
weighted-compact pseudo-label compile \
    [--detectors D1,D2,D3,D4,D5] \
    [--source-dirs ~/.claude/projects/]

# 2. Run gemma3:4b judge on candidates; emit pseudo ground truth.
weighted-compact pseudo-label verify \
    [--judge gemma3:4b] \
    [--limit 500]

# 3. Run the κ-calibration handshake against Sonnet (requires ANTHROPIC_API_KEY).
weighted-compact pseudo-label calibrate \
    [--against sonnet] \
    [--n 100]
```

**`compile`** outputs:
- `$XDG_DATA_HOME/weighted-compact/candidate_pairs.jsonl` — append-only,
  one record per detector hit. Duplicate detection: skip pairs already
  present in `pairs.jsonl` by `(session_id, correction_uuid)`.
- Prints: sessions scanned, hits per detector, total candidates.

**`verify`** behavior:
- Reads `candidate_pairs.jsonl`.
- Checks `calibration_pseudo.json` — exits with error if absent or > 30
  days old. Error message: "Run `weighted-compact pseudo-label calibrate`
  first (calibration is required; it is opt-in via `--against sonnet`)."
- Outputs `pseudo_ground_truth.jsonl`, append-only, latest verdict per
  `pair_idx` wins on load (same tombstone-replay convention as
  `labels.jsonl`).
- Prints: pairs verified, YES count, NO count, κ reminder.

**`calibrate`** behavior:
- Requires `ANTHROPIC_API_KEY` in env or exits with clear message.
- Calls Anthropic API — the only subcommand in the entire pipeline that
  makes an outbound network call.
- Writes `calibration_pseudo.json`.
- Prints the κ number and a human-readable Landis-Koch tier ("moderate",
  "fair", etc.) alongside a reminder that this is the noise envelope for
  all pseudo-label verdicts.

---

## Wire-in to the existing pipeline

`pseudo_ground_truth.jsonl` is a new input to `importance.py`, not a
replacement for any existing input.

```
labels.jsonl             →  label_keep (slot 7, weight 0.15)
pseudo_ground_truth.jsonl →  pseudo_label (slot 8, weight 0.00 default)
```

Slot 8 starts at weight 0.00. It ships wired but silent. The path to
activating it is the same as any other weight change: edit `WEIGHTS_BASE`
in `importance.py`, rerun `weighted-compact importance`, measure Δfidelity
via `weighted-compact qa-gate`. If the signal earns its slot, bump the
weight. If it does not, leave it at 0.00 — the column still accumulates
for future ablation.

The importance formula with the new pseudo-label slot explicit (note: the
`misstep` term shown in earlier drafts of this spec was removed from the
shipped mixture on 2026-06-07 — near-chance AUC; the current default mixture
is the six signals below):

```
importance(i) =
    0.25 × density_score(i)
  + 0.15 × label_keep(i)
  + 0.20 × span_keep_frac(i)
  + 0.10 × span_maybe_frac(i)
  − 0.15 × span_skip_frac(i)
  + 0.05 × span_think_frac(i)
  + 0.00 × pseudo_label(i)     ← new slot, disabled until ablated
```

`pseudo_label(i)` is `1` if `judge_verdict == YES` for the most recent
record for `pair_idx i` in `pseudo_ground_truth.jsonl`; `0` otherwise or
if the pair is absent from the file. Absent pseudo-label pairs are
penalized the same as absent human labels — neither is a zero penalty,
because an unlabeled pair is not a failed pair.

---

## Honest limitations

**Detector hit-rate is unknown before measurement.** The detectors were
designed to be precise rather than comprehensive. D2 (negation) will have
the highest raw recall but lowest precision. D5 (embedding drift) will have
the lowest recall but likely the most novel captures. No corpus-wide numbers
exist yet; they will be the first output of the ablation run that follows
implementation.

**Verifier κ floor.** The recon-QA harness has already measured
gemma3:4b-vs-Sonnet at κ=0.469 on the reconstruction verdict task. That
number does not transfer directly — the pseudo-label verdict task (is this
a correction?) is simpler in one sense (binary, well-defined) and harder
in another (shorter context, no embedding-level support). Expect κ to land
somewhere in the 0.45–0.65 range; treat anything below 0.40 as a signal
that the fixed prompt needs redesign.

**What the detector pool will miss.** Corrections that are:
- Stylistic only ("say it more concisely") — D1/D5 may not fire if the
  semantics are similar; the negation detectors will not fire if there is
  no negation token.
- Latent disagreement — the user was dissatisfied but moved on without
  an explicit correction signal. No detector in this set catches this.
- Corrections phrased as questions ("shouldn't the flag be `--no-sandbox`
  actually?") — negation does not fire; re-prompt does not fire; drift
  might, marginally.
- Corrections in language variants not covered by the RU/UA/EN lists —
  D2 will miss them.

**The bootstrap problem.** Calibration requires Sonnet. This is not
solvable within the constraint that everything runs locally. The spec does
not pretend otherwise. The calibration call is a 100-sample batch, not a
continuous dependency — it runs once and re-runs monthly, not per session.
Users running on air-gapped hardware can run `verify` without calibration;
the output will be clearly marked uncalibrated and the disclaimer will
say so. An uncalibrated verdict is still a detector verdict — it has
structural value (the detector fired); it lacks the noise-envelope
quantification that calibration adds.

**Pair deduplication edge case.** If `compile` detects a pair that is
already in `pairs.jsonl` (because the user also typed a marker), the
duplicate is skipped at compile time. This is correct behavior but means
that the pseudo-label slot for an already-extracted pair will be absent —
the human label from `labels.jsonl` takes over as the signal for that pair.
The two sources are intentionally kept separate.

---

## Privacy invariant

The entire compile → verify path reads `~/.claude/projects/` locally and
writes to `$XDG_DATA_HOME/weighted-compact/`. No session text leaves the
host on either step.

The sole exception is `pseudo-label calibrate --against sonnet`. This
subcommand:
- Sends 100 `(premise_text, correction_text)` pairs to the Anthropic API.
- Requires an explicit flag (`--against sonnet`) and an environment variable
  (`ANTHROPIC_API_KEY`) — both must be present, or the command exits
  without touching the network.
- Is never called by `compile` or `verify` automatically. It is a
  standalone action the user initiates consciously.

The calibration batch is kept to 100 samples, not the full candidate set,
to minimize transcript exposure on the single Sonnet call that is permitted.

---

## Open questions

- **Should pseudo-labels feed misstep retraining?** misstep is trained on
  stumble events extracted from the same session corpus. If a pseudo-label
  marks a pair as a correction that the regex extractor missed, should it
  also queue that pair as a stumble event in misstep's training corpus?
  The architectures are siblings, not peers — this needs a deliberate
  interface decision, not an implicit one.

- **Should compile cadence couple to the REM timer?** `rem-pass` fires
  nightly at 04:00. Compile is cheap enough to run on the same schedule,
  but tying two subsystems to one timer couples their failure modes.
  Alternatively, compile runs on a separate 24-hour timer with a different
  randomized offset.

- **What is the right weight for slot 8 after ablation shows a positive
  sign?** The label slot (slot 7) ships at 0.15, derived heuristically.
  Pseudo-label has lower precision (detector + judge vs. human + explicit
  marker), so 0.10 or 0.05 is a plausible start. The ablation process is
  defined (`weighted-compact eval --weights-a defaults --weights-b
  experimental`); the question is what the initial experimental weight
  should be before the first ablation run.

- **Multi-language negation completeness.** D2 ships with EN/RU/UA
  patterns. The substrate may contain DE, PL, ZH, or other user languages.
  Is the right approach a language-detect-then-branch strategy, or a
  universal multilingual negation model (e.g. a small XLM-R fine-tune)?
  The current design defaults to regex; expanding to a model adds a
  dependency the existing pipeline avoids.

- **Should the compile output be versioned per detector?** If D3 changes
  its FP mitigation heuristic between releases, old candidates from D3 in
  `candidate_pairs.jsonl` were produced under a different signal definition.
  Replay with the new detector is clean; retaining old candidates is
  ambiguous. A `detector_version` field in the candidate record would let
  consumers filter; the question is whether it is worth the schema
  complexity at this stage.
