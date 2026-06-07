<div align="center">

# weighted-compact

**A local, inspectable substrate over your own Claude Code sessions — with a
provably faithful recap on top.**

It reads `~/.claude/projects/` and turns it into an artifact you own: each
correction-bearing turn scored as plain `numpy` columns, and a task-segmented
**recap** of every session whose faithfulness is re-checkable, not asserted.
Local-first, zero outbound network, no daemon, no auto-injection.

> **Honest scope (alpha).** This carried a `beta` badge before it had earned
> one; it does not anymore. Two claims, kept apart so neither borrows the
> other's credibility:
>
> - **recap** — a lossy navigation map of a session — is *provably faithful*:
>   four invariants (coverage · conservation · provenance · determinism)
>   re-checked on **986/986** of the maintainer's sessions
>   (`weighted-compact recap --all`). This is the consumer with a positive,
>   checkable result.
> - **compaction** — selecting turns so a judge can still answer questions
>   about what was hidden — has **no measured edge** over cheap baselines
>   (recency, bm25). We say so, with the numbers, in
>   [How it compares](#how-it-compares).
>
> Reach for this if you want a local substrate you can *audit*; reach for a
> drop-in like claude-mem if you want set-and-forget recall.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![status: alpha](https://img.shields.io/badge/status-alpha-orange)](#status)
[![outbound-zero](https://github.com/zzallirog/weighted-compact/actions/workflows/outbound-zero.yml/badge.svg)](https://github.com/zzallirog/weighted-compact/actions/workflows/outbound-zero.yml)

</div>

```
  ~/.claude/projects/          ┌─ recap ─────────────────────────────────┐
  ┌──────────────────┐         │ task-segmented map: per-task files +     │  ⭐ provably faithful
  │ session_1.jsonl  │────┬───▶│ diffstat, commands, verbatim outcome     │     4 invariants · 986/986
  │ session_2.jsonl  │    │    │ + `--audit` (stdlib-only, ~5 ms/session) │     (lossy navigation map)
  │     ...          │    │    └──────────────────────────────────────────┘
  │ session_N.jsonl  │    │
  └──────────────────┘    │    ┌─ substrate ───────────┐   ┌─ compaction ─────┐
                          └───▶│ 5 auto signals + opt.  │──▶│ top-K markdown    │  honest-null:
                               │ label → importance.npz │   │ + budget meta     │  no fidelity edge
                               │ × topic-decay / REM    │   │ (MCP / CLI)       │  over recency/bm25
                               └────────────────────────┘   └──────────────────┘
```

```bash
# 30-second install
pipx install 'weighted-compact[mcp]'

# recap — the provably-faithful consumer; stdlib-only, runs on a bare install
weighted-compact recap --all            # task-segmented map of every session + invariant audit

# compaction substrate (honest-null on fidelity; kept for the substrate-vs-summary result)
weighted-compact bootstrap --full       # extract pairs + build the full signal substrate
weighted-compact mcp-serve              # local stdio MCP for Claude Desktop / IDE clients
```

→ [Docker / Windows install](docs/docker-install.md) ·
[Operating guide](docs/operating-guide.md) ·
[Bench vs claude-mem](docs/bench-vs-claude-mem.md) ·
[Stability promise](docs/stability.md) ·
[Extension recipe](docs/extension-recipe.md) ·
[Pick your door](#pick-your-door)

---

## By the numbers

Every figure here is re-checkable on your own corpus, and each carries its
own asterisk in plain sight — the project's stance is that an honest number
beats a flattering one.

- **985 / 985** sessions pass all four recap faithfulness invariants —
  coverage · conservation · provenance · determinism
  (`weighted-compact recap --all`). This proves the map does not *lie*
  about the session — not that it is the optimal summary.
- **~5 ms / session** — 646 MB of transcripts mapped in 5.0 s, standard
  library only (no numpy, no model, no judge in the recap path).
- **0** outbound network calls · **0 MB** idle RAM — the first is enforced
  by the [`outbound-zero`](#) CI workflow, the second because nothing runs
  between invocations.
- Querying the substrate beats a one-pass LLM summary by **~3.5×** on
  reconstruction fidelity (11.3 % vs 3.2 %, N=62, gemma3 judge). That is
  the one axis with a measured edge; the importance **mixture** does *not*
  beat cheap baselines at this N, and the [comparison
  table](#the-methodology-is-inspectable) says so.
- recap shrinks a session **~180×** — as a **lossy** navigation map, not a
  reconstructable archive. For lossless archival, `zstd -19` (~3×) wins and
  this repo points you to it rather than shipping a weaker custom fold.

---

## How it compares

A 30-second product map vs the dominant adjacent tool:

| | weighted-compact | claude-mem (77 k ★) |
|---|---|---|
| **Capture** | reads `~/.claude/projects/` on demand | 5 always-on lifecycle hooks |
| **Importance ranking** | 6 inspectable signals + REM-decay | `ORDER BY recency DESC LIMIT k` |
| **Manifesto control** | keep/skip labels honored as a hard constraint (pin / drop) | none |
| **Compaction** | top-K vector selection → markdown | LLM-summary, opaque |
| **Auto-injection** | none — client polls | every session start |
| **Outbound network** | zero (default) | configurable LLM provider per turn |
| **Substrate inspection** | `numpy` columns on disk | SQLite + Chroma |
| **Idle RAM** | 0 MB (nothing runs) | ~80–150 MB worker |
| **Reconstruction fidelity** | no measured edge — ties recency/bm25 | not measured by them |

The honest trade: the structural rows above (local, zero-outbound,
inspectable, 0 idle RAM, manifesto control) are real and verifiable. The
*quality* row is not a win — on reconstruction-fidelity the six-signal mixture
has not been shown to beat cheap baselines like recency or bm25, and neither
does hand-curation (see [`docs/baselines.md`](docs/baselines.md)). What *is* a
real, exclusive property is **manifesto control**: your keep/skip labels are
honored as a hard selection constraint — a keep-labeled pair is guaranteed to
survive compaction (up to budget), a skip-labeled pair is dropped first. That is
a deterministic control guarantee, not a compression-quality claim (proven by
construction in `tests/test_manifesto.py`; default-on in the `compact_session`
MCP tool, `meta.manifesto` reports what it honored). claude-mem is
hook-installed in seconds and feels magic; weighted-compact is a transparent
substrate you own, steer with a manifesto, and query with intent. Pick on
transparency / locality / control, not on compression quality — see
[`docs/bench-vs-claude-mem.md`](docs/bench-vs-claude-mem.md).

---

## The substrate is the artifact

`~/.claude/projects/` already contains the record of every correction
you pushed back on, every flag you restated, every constraint the model
lost track of. weighted-compact reads those files **once**, parses them
into per-pair objects (correction text, premise text, span tiers,
session anchors), and decorates each pair with six signals: density
features, span coverage (four tiers: keep / maybe / skip / think),
and one optional human label.

The decorated substrate lives at `$XDG_DATA_HOME/weighted-compact/` —
gitignored, never uploaded. It is the artifact. Compaction is the
first reader; other consumers read the same files.

**Five of the six signals run without any human input.** The sixth
— `label` — is an optional power-tier, not a requirement: the published
ablation puts its 95 % paired CI [−0.004, +0.109] crossing zero on the
lower bound, with 67 % of paired runs showing zero difference. The
substrate stands on the five automatic signals (density + four span tiers);
the labeler at `:18890/` is opt-in for users who want to add an explicit
human judgement track.

A nightly **REM pass** (`weighted-compact rem-pass`, default 04:00 via
the bundled systemd-user timer) lays a wall-clock half-life multiplier
on top: yesterday × 0.91, week ago × 0.50, month ago × 0.05. Independent
of the six-signal mixture — content signals stay stable, time refreshes
every day. See [`docs/rem-decay.md`](docs/rem-decay.md).

### Consumers reading this substrate today

| Consumer | What it does with the substrate | Status |
|---|---|---|
| **Compaction layer** — `build_compacted_context_with_meta()` | top-K importance selection → markdown context + budget meta (chars, tokens, top-3 signals). Exercised via the `qa-gate` evaluation harness; standalone session-start delivery is the next-targeted feature. | **shipped — library + harness + MCP tool** |
| **Schema extraction** — third retrieval tier | extracts reusable `(trigger, rule, anti-pattern, stable_since)` rules from your memory dir; sits above chunk/episode retrieval as the cheap top-tier — when a recurring pattern fires, you get the rule, not raw chunks | **shipped — v0.2.0b3, `weighted-compact schema {build-bank,run,all}`; honest first proof: 14/20 strict MATCH = 70 % (see [`docs/schema-extraction.md`](docs/schema-extraction.md))** |
| **Recap** — task-segmented navigation map | reads the same session source and renders, per task, the files touched (with a `+adds/−rems` diffstat), the commands run, and the verbatim outcome line. A deliberately **lossy** map — not reconstructable — but the one consumer whose quality claim is *positive and provable*: four faithfulness invariants re-checked on every session. | **shipped — `weighted-compact recap [SESSION] [--audit] [--all]`; audit holds on 985/985 of the maintainer's sessions (see [`docs/recap.md`](docs/recap.md))** |

Three consumers ship in this repo today. Four additional readers are in
flight in adjacent projects (misstep, session-narrative, FKMF,
misstep-foreign-models) — see
[`docs/consumers-roadmap.md`](docs/consumers-roadmap.md) for their
status. They are listed there, not here, because nothing about
*this repo*'s install path depends on them.

Recap earns a note the other two do not. Compaction's honest result is a
*null* — it ties cheap baselines on reconstruction fidelity (the table in
[The methodology is inspectable](#the-methodology-is-inspectable) states
this plainly). Recap is the inverse case: it makes no fidelity claim at
all — for lossless archival you would `gzip`/`zstd` the raw `.jsonl` and
get ~3× — but for the *navigation* job it does claim, the claim is
checkable and it checks. See [Recap: faithful, not
lossless](#recap-faithful-not-lossless).

---

## The substrate is structurally personal

The artifact described above is a record of one person's corrections,
stumbles, span decisions, and labels. That shape has four properties
that make it a different *category of object* from a vendor-shipped
memory feature — not better, different.

**Local persistence.** Conversation text lives on disk under
`$XDG_DATA_HOME/weighted-compact/`, in a path no remote service writes
to. A vendor whose revenue model is cloud uplink does not put a
writable user-controlled persistent store on your machine. Comparable
"local" vendor patterns (Apple Intelligence, Microsoft Recall) still
route memory through their sync infrastructure.

**Anti-drift labeling.** The labeler's anti-drift sidebar shows the
five cosine-nearest prior labels alongside each candidate. This
optimizes for **you converging to yourself over time**, not for you
converging to the model's policy. A vendor's incentive runs the other
direction — the more predictable a user is to the model, the better
the model serves that user inside the vendor's product. The mechanism
is structurally adversarial to vendor goals.

**Per-user predictor.** The substrate structure supports per-user
predictors trained on **your** stumble events from **your** correction
embeddings (AUC numbers are corpus-dependent and the default mixture
currently uses density as backbone — see the pluggable table for the
misstep slot). A vendor's foundation model is one model serving
millions; per-user trained auxiliary predictors at that scale are not
economic. Any cloud-side approximation collapses to an averaged stumble
pattern — which is exactly the loss of per-user shape that makes the
substrate yours.

**Multi-consumer substrate.** misstep / session-narrative / FKMF /
misstep-foreign-models all read the same per-pair files. A vendor
ships memory as a feature embedded in one product. Substrate-as-
substrate, queried by multiple independently developed readers, is a
different shipping unit — and it requires open, scriptable, user-owned
substrate.

These four properties compose into one statement: the substrate
**carries you**, not a generalized inference about you. A vendor's
memory feature can be more polished, better integrated, faster to
adopt — and still be a categorically different object from this one.
That difference is not a moat claim; it is a description of the
shape, and the shape is what defines the project.

---

## The methodology is inspectable

Adjacent memory tools capture every tool call, ship the stream to an
LLM, store the summary, and at session start inject "relevant" snippets
back. The capture is automatic, the summary is opaque, and the relevance
function is a `ORDER BY recency DESC LIMIT k` against a vector index.
There is no way to ask *why this snippet was kept and that one was not*
except by reading the LLM's mind.

This project takes the inverse stance. The same correction-pair
substrate that the runtime consumes is also queryable by an evaluation
harness: hide one pair, reconstruct the answer from the rest, ask two
independently-trained model families (Qwen generator, Gemma judge) to
agree that the answer still holds. The cross-family choice is a
methodology contract, not a runtime dependency — when both families
agree the pair was recoverable, the *signal weighting that recovered
it* is the part being tested, not any single model's verdict. Cohen's κ
between cheap-local and paid-cloud judge is published (κ=0.469); the
noise envelope around every claim is named in the same table as the
claim.

The runtime stores no opaque summaries; the per-pair scores are
columns in a numpy array on disk. The evaluation harness is reproducible
on any user corpus. There is no black box between "this pair was
recovered" and "this is why."

The published consumer is compaction. Its proof is on the
reconstruction-fidelity loop: hide a pair, ask whether the compacted
context still answers questions about it.

| Method | Per-Q fidelity (gemma3:4b judge, N=62, k_drop=0.5) |
|---|---:|
| Random selection (seed 42) | **12.9 %** (8/62) |
| 6-signal mixture (this project) | **11.3 %** (7/62) |
| Recency-only | 11.3 % (7/62) |
| Cosine retrieval (e5) | 11.3 % (7/62) |
| Density (single signal) | 9.7 % (6/62) |
| BM25 retrieval | 9.7 % (6/62) |
| Naive `/compact` analog (qwen summarize) | **3.2 %** (2/62) |

Reading. The **8 pp gap between any structured selection and the
summary-bypass** is the strongest signal in the table: querying the
substrate beats discarding it for a one-pass LLM summary by 5 questions
out of 62. **Within structured selection**, the mixture does not yet
outperform a uniform random ranker at this N under the gemma3 judge
(κ=0.47 agreement vs Sonnet). The pre-registered narrative target —
mixture beats cheap baselines by ≥0.05 absolute — is **not met**.

What this proves: the **substrate-vs-summary axis** (parsing into pairs
and querying beats one-pass summary). What it does not yet prove: the
**mixture-vs-naive-ranker axis** (which weighting on the substrate is
best). Both axes matter. The first is the architectural bet; the
second is open work for v0.3.

**Honest scope of the measurement.** `/compact` in the harness is a
qwen2.5:7b-driven summariser, not Claude Code's actual `/compact`
prompt (closed, not in the loop). Replacing the simulator with captured
real-`/compact` traces is filed for v0.3 — this is the single change
that would harden the headline most.

**Sonnet calibration sidebar** (different harness, 2026-05-21). The
earlier Sonnet 4.6 calibration on the larger 1718-triple set reported
**3.8 %** per-question fidelity under strict vector-and-anchor policy
when the source pair was hidden. The cheap-judge agreement against that
Sonnet pass came in at **Cohen κ = 0.469** (precision 0.70, recall 0.51,
1433 paired predictions) — the noise envelope around the table above.
An earlier label-weight ablation under the same cheap judge gave
**Δfidelity = +0.053** (95 % paired CI [−0.004, +0.109], 3/3 corpora
positive); under the strict-judge view that signal needs to re-test.
The 3.8 % number sits on a different N, different judge, and different
test condition (k_drop=0 hide-source-only vs k_drop=0.5 here); apples-
to-apples comparison is filed under v0.3.

Numbers are this corpus; the methodology reproduces on any user's
substrate.

---

## Recap: faithful, not lossless

Compaction tries to *select* which turns to keep so the rest can still
answer questions — a fidelity problem, and the table above is honest that
the mixture has no measured edge there. Recap does not play that game. It
asks a different question — *what happened across this session, task by
task* — and answers it as a **lossy navigation map**: per task, the goal,
the files touched with a `+adds/−rems` diffstat, the commands run, and the
verbatim final outcome line.

```text
## 8. on sharp new loads it needs 5 ticks to settle, then it's near-instant…
`11×Bash, 10×Edit, 7×Read, 5×TaskCreate, 2×Write`   net `+557/−8`

  🟩🟩🟩🟩🟩 `+198 −0  ` ~/coolstep/coolstep/core/spike_detector.py        (write)
  🟩🟩🟩🟩🟩 `+148 −4  ` ~/coolstep/tests/test_spike_detector.py           (edit+write)
  🟩🟩🟩🟩🟩 `+94  −0  ` ~/coolstep/coolstep/daemon.py                     (edit)
  cmd: `pytest tests/test_spike_detector.py -v` · `rg -n "WorkloadProfile"` …
  → Done, commit 599cfcd. spike_detector.py — state machine enters at |res|≥5°C ×2 ticks…
```

A lossy map cannot be checked by reconstruction. It **can** be checked for
faithfulness, and that is the whole point of shipping it here rather than
as a one-off script. `recap --audit` re-derives, from an independent pass,
four invariants:

| Invariant | What it rules out |
|---|---|
| **I1 coverage** — every message record lands in exactly one task segment | silent drops |
| **I2 conservation** — per-tool counts over segments equal the raw transcript | a tool call lost or double-counted |
| **I3 provenance** — every path / command shown is a verbatim transcript member | fabrication |
| **I4 determinism** — a second pass recomputes every diffstat to the same integers | guessed numbers |

Extraction is fully deterministic — no LLM, no judge. The outcome line is
a quoted excerpt of the assistant's own final message, not a summary.
Across the maintainer's corpus the audit holds on **985/985** sessions
(`weighted-compact recap --all`).

For lossless archival of the raw logs, recap is the wrong tool — a
general compressor wins: `zstd -19` gives ~3× and round-trips exactly,
while a hand-built structural fold measured **1.8×** (it loses to the
compressor because the redundancy a content-dedup catches is ~1.1× and
the cross-session redundancy is better caught by zstd's large window).
Recap's ~180× shrink is *lossy* — it is a map, not the territory, and the
audit guarantees the map does not lie about the territory.

---

## The case for a substrate, not a feature

Today your session log is parsed once by a summariser and tossed.
Whatever the summariser misses is gone — the hostname you corrected an
hour ago, the flag you restated three turns up, the edge case you
described slowly. The summariser is one consumer with one task; its
output is throwaway.

The bet behind this project is that **the parsed substrate is more
valuable than any single output computed from it**. Once a session
becomes structured per-pair objects with six signals attached, the
same artifact can be queried for compaction *and* stumble prediction
*and* narrative recall *and* knowledge-gap detection *and* foreign-model
observability. Same data, different readers. The substrate becomes
infrastructure.

Compaction is the first published reader because it is the most
tractable proof point — a fidelity loop with a quantifiable answer.
The numbers above are about that reader. The wider claim — that the
substrate is the right primary object — is supported by the other
consumers listed above existing as separate projects at all, not by a
benchmark on this README.

Six signals compose into one importance score: density features as
backbone (sixteen regex signals, rank-normalised), four span tiers (keep /
maybe / skip / think), one sparse human label — modulated by an unsupervised
topic-decay multiplier applied on top of the mixture.
Vectors first; the importance mixture is a refinement layer, not a gatekeeper.
Reconstruction fidelity — can the compacted context still answer
questions about what was hidden from it — is the metric for the
compaction reader. Not compression ratio.

The v0.3 direction is **cross-session correlation** — corrections from
one session inform ranking in the next, so recurring constraints
accumulate weight instead of resetting at each compact. This is where
substrate-as-substrate starts paying compound interest that a one-shot
`/compact` cannot: information from session 17 lifting ranking in
session 84. The v0.4+ direction is the same signals running in
reverse — predict the corrections you are about to make, the
constraints you are about to set, the paths you typically reject.
Substrate on disk; an IDE-side assistant reads it as lookahead; nothing
leaves the host. The substrate becomes a memory you can interrogate,
then a forecaster you can override.

---

## Numbers and their meaning

Eight tests, all on the compaction reader (the published consumer).
Four shipped with numbers; the rest with the gap named. Each result
cell has the number on line one and the reading on line two.

| # | Test | Status | Result |
|---|---|---|---|
| 1 | **Ground-truth fidelity** under cross-family judge | shipped | Sonnet 4.6, 573 pairs → 3.8 % per-Q fidelity floor; failure split: ~40 % IDK / ~24 % paraphrase / ~6 % ranking error.<br>*≈96 % of pair-specific detail vanishes when that pair is hidden from context — the absolute starting point, before the mixture does any work.* |
| 2 | **Coefficient ablation** — `label_weight ∈ {0, 0.15}` | shipped, partial sweep | Δ=+0.053, 95 % paired CI [−0.004, +0.109]; per-corpus signs 3 / 3 positive; 38 / 57 paired runs (67 %) are ties.<br>*Turning the human-label term on shifts per-Q fidelity by ≈5 percentage points but the CI crosses zero on the lower bound, and two-thirds of paired runs are unaffected either way. Read as: the five automatic signals (density + four span tiers) carry the substrate by themselves; label is an optional power-tier, not a precondition.* |
| 3 | **Cross-corpus consistency** — 3 disjoint session corpora | shipped | A +0.100 / B +0.028 / C +0.021; sign breakdown 13 pos · 6 neg · 38 ties.<br>*Three independent maintainer corpora all show positive Δ — the row-2 effect is not an artefact of one session window.* |
| 4 | **Cheap-judge calibration** — gemma3:4b vs Sonnet 4.6 | shipped | κ = 0.469, precision 0.70, recall 0.51, zero "other" verdicts.<br>*The free local judge agrees with the paid cloud judge at "moderate" Landis-Koch level — cheap enough for continuous monitoring, not strict enough for definitive scoring.* |
| 5 | **Anti-baseline** — mixture vs naive `/compact` summary + cheap structured rankers | shipped | qwen-summarized `/compact` analog: **3.2 %** (2/62). Mixture: 11.3 % (7/62) — **8 pp gap**. Within structured (random / recency / cosine / mixture / density / bm25): all within ±1 question. Same harness, gemma3:4b judge, k_drop=0.5.<br>*Structured selection of any kind beats one-pass summarisation by a substantial margin. The mixture's edge over cheap structured baselines is not yet measurable at this N under the cheap-judge proxy — that's the open question for v0.3.* |
| 6 | **Full coefficient grid** — all 6 signal weights | filed | `weighted-compact ablation --weights` one-shot wrapper, v0.3.<br>*Only one of the six mixture weights has been swept so far; the other five contribute under their heuristic defaults.* |
| 7 | **Compositional / long-run** — fidelity across rolling 48-pair windows | scaffold | `recon_qa/gate.py` computes buckets; downstream routing partial.<br>*Fidelity is scored per pair, not as a function of accumulated history — cannot yet answer "did the last 30 sessions improve or degrade older recall."* |
| 8 | **Multi-user scaling** — reproduction on second corpus | open invitation | Methodology is the contribution; magnitudes are not portable.<br>*If you run on your corpus, the absolute numbers will not match — but the direction of the label-weight effect should reproduce.* |
| 9 | **REM-decay multiplier** — wall-clock half-life ageing | shipped 2026-05-23 | `weighted-compact rem-pass [--half-life-days 7]`; nightly timer template; `--rem-decay` flag end-to-end through `qa-gate` and `run_eval`.<br>*Independent of the six-signal mixture. Content signals are stable; time refreshes every day. Half-life sweep on the fidelity gate is filed for v0.3 — for now, 7 days is heuristic.* |
| 10 | **MCP stdio server** — local-only client surface | shipped 2026-05-23 | `weighted-compact mcp-serve`; three tools (`search_pairs`, `compact_session`, `substrate_info`); optional extra `pipx install 'weighted-compact[mcp]'`.<br>*Lets MCP-speaking clients (Claude Desktop, mcp-cli, IDE plugins) query the substrate without re-parsing it. Stdio only; no network, no auto-inject, no write tools. See [`docs/mcp-integration.md`](docs/mcp-integration.md).* |
| 11 | **Docker / Windows install path** | shipped 2026-05-23 | `Dockerfile` + `docker-compose.yml`; non-root `wc` user; substrate on named volume; `~/.claude/projects` bind-mounted read-only; labeler at `127.0.0.1:18890`; optional ollama sidecar.<br>*Path of least resistance for users without a Python toolchain — Windows in particular. The REM pass runs as an in-container sleep-loop or host cron / Task Scheduler. See [`docs/docker-install.md`](docs/docker-install.md).* |
| 12 | **Cross-tool bench harness vs claude-mem** | shipped 2026-05-23, script + spec; partial-run numbers pending | `scripts/bench_vs_claude_mem.sh` + `docs/bench-vs-claude-mem.md`; deterministic 30-pair sample (seed 42); same `gemma3:4b` judge for every method.<br>*Methodology is honest about the asymmetry — claude-mem normally runs hook-driven; the bench drives it via its worker HTTP API on a fixed corpus. Reproduction invited via the `bench:` issue label.* |

The label-weight ablation gives a directional read: paired mean
Δ=+0.053, per-corpus signs 3/3 positive (+0.100 / +0.028 / +0.021).
But the 95 % paired CI [−0.004, +0.109] crosses zero on the lower bound,
and 38 of 57 paired runs (67 %) are exact ties — flipping the human-label
weight on or off changes nothing for two-thirds of evaluations under the
cheap-judge κ=0.47 noise envelope. The published default treats label as
**optional**: the five automatic signals (density + four span tiers)
carry the substrate on their own, and `bootstrap` ships with no labeling
step. Users who want
to add the human-judgement track open the labeler at `:18890/` as a
deliberate power-tier action, not as a precondition for installation.
This is the adoption-wall removal that distinguishes the substrate from
any approach requiring per-pair human labeling at install time.

---

## Pick your door

Same substrate, five readers. The one that names you is yours.

<a id="angle-daily-user"></a>

### 🌱 &nbsp; If you use Claude Code daily

You correct the model. You restate flags. You watch summaries lose the
hostname you typed thirty turns ago. The pain is concrete.

*Would make this irrelevant to you:* your sessions never run long enough
to hit compact, or you reset between threads instead of compacting. The
substrate's whole job kicks in at that boundary.

*The claim:* the substrate parses every correction into a queryable
object. Today the compaction reader uses that to build a refill context
shaped by what *you* marked. Tomorrow (v0.3) a cross-session reader
will spot when this session's correction was the third time you made
the same one across three sessions and weight it accordingly.

*Action:* `pipx install` → `weighted-compact compat` → `bootstrap --full`. Done.
No labeler, no twenty-minute sitting — the five automatic signals derive
from your session files alone. The labeler at `:18890/` is opt-in if you
want to add the sixth (sparse human-judgement) signal; the published
ablation says you don't have to.

→ [Install](#install) · [Q1 — find your own stumble](#quiz--quest)

---

<a id="angle-researcher"></a>

### 🔬 &nbsp; If you read papers on memory, distillation, compaction

The framing is *substrate, not policy*: the user's own corrections are the
training signal, extracted from `~/.claude/projects/` rather than from
preference data or RL rollouts. Cross-family judge by contract
(`gemma3:4b` Gemma judges `qwen2.5:7b` Qwen reconstructions), cheap-judge
calibrated against Sonnet 4.6 on identical predictions.

*Would make this irrelevant to you:* you want SOTA on a public benchmark.
This is one corpus, one user, 573 pairs. No CIMemories-style scaling
table; no cross-method shoot-out. Reproduction is invited, not packaged.

*The number:* 3.8 % per-Q fidelity floor (Sonnet) defines the open
question — what raises it. The +0.053 Δ label ablation has its 95 % CI
crossing zero — direction holds, magnitude not statistically
distinguishable from the six-automatic-signal baseline at this N. Six
remaining weights are uncharted; that is the open ablation grid.

*Action:* read [`docs/importance-mixture.md`](docs/importance-mixture.md)
for the full ablation table, reproduce on your own corpus, file an issue
with the sign agreement (or disagreement) across your sessions.

→ [Results](#headline-compaction-consumer) · [`docs/05-roadmap.md`](docs/05-roadmap.md)

---

<a id="angle-builder"></a>

### 🔧 &nbsp; If you write code and want a substrate you can extend

Eight modules, eight black-box contracts (input, output, entry point,
dependencies). Each contract is at the top of its own file. Replace any
single box without touching the rest, as long as the I/O shape holds.

*Would make this irrelevant to you:* you want a finished tool with a
config UI. This is a workbench. The contract surface is named and
documented; the framework around it is light on purpose.

*The number:* ~30 LOC to add a new density feature; ~60 LOC to add a
whole new signal with its own `features_X.npz` producer plus a weight
entry in `importance.py:WEIGHTS`.

*Action:* open `weighted_compact/density_features.py`, append a regex
feature, rerun `bootstrap --full` + `qa-gate`. The Δfidelity vs the previous
run tells you whether the feature earned its column.

→ [What is pluggable](#what-is-pluggable) · [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

<a id="angle-reconstructor"></a>

### 🕵️ &nbsp; If you think a dialog can be reverse-engineered from signals

Structurally, this is an inverse problem. Hide one pair, hand the rest
to a model, ask it the questions whose answers lived in the hidden pair.
If the model answers, the importance mixture chose the right context. If
not, you are missing a feature.

*Would make this irrelevant to you:* you want compaction that works
out-of-the-box. The reconstructor angle is for people who want to add
a signal and prove it earns its slot.

*The number:* the cross-family judge keeps the loop honest at κ=0.47
against ground truth — high enough to be a useful fitness gate, low
enough that magnitudes don't survive without a sign-agreement check.

*Action:* write a regex or a classifier for a pattern the mixture isn't
catching (hesitation markers, intent-shifts, rhetorical reversals).
Re-run the loop. The numbers tell you whether your hypothesis holds
up under paired evaluation.

→ [Q3 — add a signal in thirty lines](#quiz--quest) · [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md)

---

<a id="angle-privacy"></a>

### 🔒 &nbsp; If you care about local-first and privacy

Substrate lives in `$XDG_DATA_HOME/weighted-compact/`. Gitignored. The
**runtime** is the substrate plus markdown render — no LLM in the loop.
The Ollama models (`qwen2.5:7b` generator + `gemma3:4b` cheap judge) are
**evaluation harness**, not runtime: they exist so anyone can re-run the
reconstruction-fidelity test (hide a pair, ask if the compacted context
still answers questions about it) on their own corpus with two
independently-trained model families cross-checking each other. Zero
outbound calls on either path.

*Would make this irrelevant to you:* you noticed Sonnet 4.6 in the
results table. Yes — the calibration in [Headline](#headline-compaction-consumer) is a
maintainer-side one-time cloud-judge run, explicitly disclosed. Users
who want a Sonnet-grade verdict opt in to their own API key; the
default binds nothing.

*The number:* zero outbound network calls on the default path; one CI
job (`scripts/leak-scan.sh`) scans every commit for substrate filename
patterns and hardcoded personal-home paths. The remote repo is an
orphan-cut branch carrying only framework code; the maintainer's
substrate, with personal session history, lives on a private mirror
and never touches GitHub.

*Action:* run `weighted-compact bootstrap` on an air-gapped host. Read
`docs/invariants.md` for the architectural commitments behind the
guarantee.

→ [Architectural invariants](#architectural-invariants) · [`docs/invariants.md`](docs/invariants.md)

---

<a id="angle-ops"></a>

### ⚙️ &nbsp; If you want this to run nightly without thinking about it

Three commands plus a timer, and the substrate stays current on its own.
Recent sessions outweigh distant ones every morning; five automatic
signals refresh content importance whenever bootstrap is re-run; nothing
talks to the cloud.

*Would make this irrelevant to you:* you don't want a long-lived
substrate at all — you reset state between sessions or use the model as
a stateless chat tool. The whole point of nightly automation is that the
substrate is the artifact you keep around.

*The number:* one timer, fires at 04:00 local with a 15-minute
randomized delay; one oneshot service writes `rem_decay.npz` and rotates
the previous version to `rem_decay.npz.bak.<UTC-ts>`. Hardcoded path —
no `~/.bashrc` injection, no `crontab -e`, no shell hook.

*Action:*
```
weighted-compact install-units --force
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact-rem-pass.timer
systemctl --user list-timers weighted-compact-rem-pass.timer
```

→ [REM-decay docs](docs/rem-decay.md) · [`systemd/weighted-compact-rem-pass.timer`](systemd/weighted-compact-rem-pass.timer) · [Operating guide — how / what / how much / why](docs/operating-guide.md)

---

## What we crossed

Concepts the project ran into on the way. Each one forced a design
decision — named, so you can see what the choice was.

**Goodhart's law.** Optimize a metric long enough and the metric stops
being a metric. We do not gradient-descent the mixture weights against
the recon-QA fidelity score — the loop is held out as a fitness gate,
not used as a training loss. Mixture weights are heuristic and fixed
before recon-QA runs. The price is that the weights are not optimal;
the price of the alternative is that the score becomes meaningless.

**Cohen's κ and the Landis-Koch scale.** A free local judge is cheap to
run but suspect; a paid cloud judge is the reference but cannot be the
default. Cohen's κ between `gemma3:4b` and Sonnet 4.6 on identical
predictions came in at **0.469** — "moderate" agreement per the
Landis-Koch convention. Usable as a routine cheap proxy; not a
substitute for definitive scoring. We publish κ instead of raw
accuracy so the dispersion is legible.

**Same-family judge agreement.** When the judge model and the generator
model share a backbone or training corpus, they tend to concur unfairly.
The pipeline avoids this by contract: Gemma judges Qwen reconstructions;
no Qwen judging Qwen. The cross-family choice is the architecture, not
a robustness ablation. The cheap-judge κ above measures how much this
default already costs you.

**Sign agreement under a noisy magnitude.** The label-weight ablation
produced Δ=+0.053 with 95 % paired CI [−0.004, +0.109] — the magnitude
crosses zero on the lower bound. The per-corpus signs, separately, were
3 / 3 positive (+0.100 / +0.028 / +0.021). Direction reproduces;
magnitude wobbles. We report both and call the CI a qualifier on the
magnitude, not a retraction of the direction.

**Graceful degradation as contract.** A pipeline that breaks when one
piece fails is brittle. Each signal in the mixture is optional — missing
labels, their weight drops out; missing spans, the four tier-terms
collapse to zero. The system degrades to a density baseline. A
single-classifier gatekeeper design has no analog for this; we picked
the weighted-sum mixture in part for exactly this property.

---

## Honest limitations

- **One corpus, one user.** 573 pairs from the maintainer's Claude Code
  sessions. Magnitudes are not portable; the methodology is what
  reproduces. A scaling story across users does not exist yet — it
  requires others running on their own substrate and reporting back.
  *What this means for you:* your absolute numbers will be different;
  the direction of effects should reproduce, the magnitudes likely will
  not.

- **Four of five substrate consumers are not shipped here.** misstep,
  session-narrative, FKMF, misstep-foreign-models are listed in the
  consumer table because they exist and they read this substrate format.
  They are not packaged in this repo and they are not publicly
  available. They support the architectural claim ("the substrate has
  more than one reader"); they do not give you running tools today.
  *What this means for you:* if you install weighted-compact, you get
  the compaction reader and the substrate. You do not get the other
  four. The substrate format itself is what you can build on.

- **The `/compact` comparator is a local-LLM simulation, not the real
  `/compact`.** The 8-pp gap in the headline is against a
  `qwen2.5:7b`-driven summariser, because Anthropic's actual `/compact`
  prompt is closed and not in the harness. Replacing this with captured
  real-`/compact` traces is filed for v0.3 and is the single change
  that would harden the headline most.
  *What this means for you:* read the 8-pp result as "structured
  selection beats one-pass local-LLM summarisation on this corpus",
  not "weighted-compact beats Claude Code `/compact`". The second
  claim has not been measured.

- **Per-question fidelity floor is 3.8 %.** Most pair-specific detail is
  genuinely lost on compaction; what survives is anchor-rich content
  (entities, paths, numbers, short verbatim). This is the absolute
  starting position, not a regression.
  *What this means for you:* expect that most fine detail vanishes at
  the compact boundary without intervention. The substrate's job is to
  make what survives match what you marked — not to restore everything.

- **Misstep predictor removed (2026-06-07).** Held-out AUC ~0.66–0.70
  — barely above chance — was not sufficient to honestly identify which
  corrections matter, and the predictor required a separate substrate
  absent on fresh installs. It is available as an extension point (see
  the pluggable table) but is no longer part of the default mixture.
  Density now carries the backbone weight.
  *What this means for you:* the six-signal mixture ships and works
  without any misstep substrate. If you have your own stumble predictor
  with higher AUC, wire it in via the pluggable slot.

- **Classifier-as-fidelity-proxy is parked.** A first attempt at training a
  Sonnet-fidelity predictor from 411-dim engineered features landed at
  AUC ≈ 0.5. Either the sample is too small for the imbalance, the
  features are optimised for ranking rather than fidelity prediction, or
  fidelity is emergent from retrieval+generator interaction. Not a
  current dev target.
  *What this means for you:* the substrate runs on the six-signal
  mixture; the parked classifier you may see in logs is not weighted
  into the score. Nothing user-facing depends on it shipping.

- **Iter-chain mode-distinction QC is parked.** All three modes
  (complement / refine / deepen) cluster in cosine drift `[0.95, 1.00]`
  under the current generator+prompt; calibrated bands would be too
  tight (σ ≈ 0.005-0.012) to be useful.
  *What this means for you:* the iter-chain modes in the inspector look
  usable but their quality signal doesn't differentiate yet. Treat those
  rows as illustrative until the redesign ships.

- **50-sample baseline is the threshold** for individual scores to read
  as calibrated rather than illustrative. Below that, you have an
  importance ranking; you do not yet have a stable fidelity measurement.
  *What this means for you:* if you just installed and the fidelity
  number looks weird, that's expected — keep using Claude Code, let your
  corpus accumulate, re-bootstrap, then trust the number.

- **Mixture's edge over cheap structured baselines is not yet
  measurable.** At N=62 under gemma3:4b judge, random / recency /
  cosine all match the mixture within ±1 question (12.9 % / 11.3 %
  / 11.3 % / 11.3 %). The 8-pp gap is between any structured ranker
  and the summary-bypass — that survives. The pre-registered narrative
  bar (mixture beats cheap baselines by ≥0.05 absolute) is not met by
  this measurement.
  *What this means for you:* if you're picking weighted-compact over
  a uniform random ranker, the case currently rests on (a) the
  substantial gap over LLM-summary compaction, and (b) the architecture
  being designed for Sonnet-grade re-judge and larger corpora where the
  mixture's signal can express — not on a present measured advantage
  over cheap baselines.

---

## What the pipeline does

Session files in. Eight modules score each turn against six signals.
The most important content rebuilds the compacted context. A judge from
a different model family checks whether the result still answers
questions about what got cut.

The composer formula:

```
importance = 0.25 × density + 0.15 × label
           + 0.20 × span_keep + 0.10 × span_maybe
           − 0.15 × span_skip + 0.05 × span_think
```

The eight modules are independent black boxes — each documented at the
top of its own file, replaceable individually. The quality metric
driving development is *reconstruction fidelity*, not compression
ratio: ratio is easy to game, fidelity is harder. See
[`docs/03-quality-driver.md`](docs/03-quality-driver.md) for the
argument, [`docs/architecture.md`](docs/architecture.md) for the
module map.

---

## Architectural invariants

Three commitments — full text in [`docs/invariants.md`](docs/invariants.md).

1. **The system won't break when something's missing.** Every turn becomes
   an e5-multilingual-small embedding. The importance mixture runs on
   those vectors. The classifier is a *weighting* layer on top, not a
   gatekeeper. If it degrades or is missing, the pipeline degrades to a
   vector baseline. (Vectors first, classifier as refinement.)

2. **You label only when there's a real reason to.** Two triggers: an
   inline marker in a live session, or classifier disagreement. Twenty
   pairs in one sitting when there is a reason. The UI shows five
   cosine-nearest prior labels alongside the current pair — anti-drift
   scaffolding so you match your own past judgment, not the model's.
   (CAPTCHA labeling: gap-fill + ambiguity-merge, not bulk.)

3. **No Anthropic-side dependencies.** A *harness* is the side that hosts
   an assistant — Claude Code itself, ChatGPT's app, Cursor's IDE plugin.
   Each one decides what system message goes in, what tools are exposed,
   how output gets delivered. weighted-compact assumes none of those
   privileges: it writes Markdown, you paste it, it runs standalone. If a
   future harness exposes more privileged delivery, that is a bonus, not
   a dependency.

---

<a id="what-is-pluggable"></a>

## What is pluggable

Every replacement point is named. Swap a component, rerun the recon-QA
loop, watch Δfidelity — the loop tells you whether your version helped.

| Replacement point | Default | What you can replace with |
|---|---|---|
| Pair extractor | `extract_pairs.py` walks `~/.claude/projects/` | Any source producing `pairs.jsonl` with the documented schema |
| Embedder | `intfloat/multilingual-e5-small` (384-dim) | bge-m3, qwen3-emb, gte-multilingual, any sentence-transformer |
| Density features | 16 regex signals | Your own regex bag, LM-derived features, custom entropy variants |
| Misstep predictor | logistic regression on stumble events (per-user) | Any model returning `P(stumble)` per pair |
| Span tier set | KEEP / MAYBE / SKIP / THINK | Locked at 4 in current schema |
| Topic segmenter | sliding-window cosine on e5 vectors | BERTopic, supervised classifier, your own boundary detector |
| Importance composer | weighted sum of 6 signals | Custom mixture, additional signals, GBM ensemble |
| Reconstruction model | `qwen2.5:7b` via Ollama | Anything behind an Ollama `/api/generate` endpoint |
| Judge model | `gemma3:4b` (Gemma family) | Any other family — distinct-family constraint is the only rule |
| Difficulty filter | EvoEnv-style two-`k_drop` bucketing | Your own bucketer returning the four-bucket dict |

→ Module-by-module contracts: [`docs/02-pipeline.md`](docs/02-pipeline.md)

---

## Quiz / Quest

Three concrete invitations. The fastest way to understand the system is to
run it against your own corpus and watch the numbers move.

**Q1 — Find your own stumble.** Bootstrap. Open the labeler. Sort by
`misstep_score` descending. Top five pairs should be moments where you
corrected the model sharply and the conversation stabilised after. Were
they? If yes, the predictor caught your stumbles. If not, your corpus is
below the training threshold — keep using Claude Code and re-bootstrap
in a week.

**Q2 — Reproduce the label-weight ablation on your own corpus.** Maintainer
corpus, gemma3-judged, N=57 paired: Δ=+0.053, sign positive in 3/3 corpora.
Re-run on yours; the goal is the **sign**, not the magnitude. κ=0.47 cheap-
judge noise will widen your CI; multiple seeds or an opt-in Sonnet pass
tighten it.

```bash
# Pass A: shipped label weight (0.15)
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge

# Pass B: drop to 0.0 in weighted_compact/importance.py:WEIGHTS, save, rerun
weighted-compact importance && weighted-compact qa-gate --easy-k 0.0 --hard-k 0.9 --signal judge
```

**Q3 — Add a signal in thirty lines.** Open `density_features.py`. Add a
regex for reversal markers (`r"\b(actually|wait|scratch that)\b"`). Rerun
`bootstrap --full`. The new column lands in `features_density.npz` automatically.
Wire a weight in `importance.py:WEIGHTS`. Run recon-QA. Did your new
signal change which pairs survive compaction at `k_drop=0.5`?

---

## Install

```bash
pipx install git+https://github.com/zzallirog/weighted-compact
```

```bash
weighted-compact compat        # read-only sanity check
weighted-compact bootstrap --full  # build the full substrate from ~/.claude/projects/
weighted-compact serve         # open labeler at http://127.0.0.1:18890/
```

For ambient operation (nightly REM-decay pass):

```bash
weighted-compact install-units
systemctl --user daemon-reload
systemctl --user enable --now weighted-compact-rem-pass.timer
```

Requirements: Linux (Arch, Debian, Ubuntu in CI), Python 3.11-3.13,
`~/.claude/projects/` populated. Optional: `sentence-transformers` for
re-embedding; [Ollama](https://ollama.com) with `qwen2.5:7b` +
`gemma3:4b` for the default local recon-QA loop; an Anthropic API key
if you want the Sonnet-grade judge as an opt-in tier (the default binds
nothing to it).

Platform matrix: [`docs/install.md`](docs/install.md).

---

## Status

| Component | Status |
|---|---|
| **Recap reader** (`weighted-compact recap`) | **shipped — provably faithful: 4 invariants, 986/986 sessions; stdlib-only; ~5 ms/session** |
| Substrate builder (parse sessions, embed, decorate with 5 automatic signals + optional label) | shipped |
| Importance ranker (signal mixture — used by compaction reader) | shipped — **but no measured fidelity edge over recency/bm25; do not read it as a quality win** |
| Compaction reader (`build_compacted_context()` library + `qa-gate` harness) | shipped — proves substrate-vs-summary (~3.5×), not mixture-vs-baseline |
| Schema extraction (`weighted-compact schema`) | shipped — 14/20 strict MATCH = 70% (same-model judge); cross-model judge drops to 1/20 → judge-calibration is the open problem |
| Labeling UI (CAPTCHA-style, anti-drift) | shipped — optional; the human-control→fidelity path measured null, kept for users who want a manual track |
| Fidelity check (cross-family judge, Sonnet baseline measured 2026-05-21) | shipped |
| Baseline comparison harness (6 rankers + mixture, incl. `/compact` sim) | measured 2026-05-21 — see [How it compares](#how-it-compares) |
| Standalone session-start delivery CLI (ambient render) | next |
| Cross-session correlation reader (corrections accumulate across sessions) | direction |

**Alpha.** Honest label: this wore `beta` before it had the results to back
it. What works end-to-end on a real corpus: the recap reader (with its audit),
the substrate builder, the compaction reader and its fidelity harness, schema
extraction. What is *not* a win and is marked as such: the importance mixture
beating cheap baselines. Architectural invariants are locked; the numbers
around them are not. Migration notes in `CHANGELOG.md`.

Contributor-grade full component table (17 rows): [`docs/status.md`](docs/status.md).

---

## Where to read further

| File | Topic |
|---|---|
| [`docs/01-substrate.md`](docs/01-substrate.md) | Your sessions as a self-distillation corpus |
| [`docs/02-pipeline.md`](docs/02-pipeline.md) | Eight modules as black boxes, box by box |
| [`docs/03-quality-driver.md`](docs/03-quality-driver.md) | Why fidelity, not compression ratio |
| [`docs/04-grep-vs-judge.md`](docs/04-grep-vs-judge.md) | Two-tier signal economics: cheap regex vs LLM judge |
| [`docs/05-roadmap.md`](docs/05-roadmap.md) | Open items, honest forward look, 2026-05-21 baseline |
| [`docs/baselines.md`](docs/baselines.md) | Baseline rankers — methodology + how to run the comparison |
| [`docs/schema-extraction.md`](docs/schema-extraction.md) | Third retrieval tier — auto-extracted rules above chunks |
| [`docs/concept.md`](docs/concept.md) | Longer-form take on the problem |
| [`docs/invariants.md`](docs/invariants.md) | Three locked design invariants |
| [`docs/architecture.md`](docs/architecture.md) | Module map and substrate pipeline |
| [`docs/importance-mixture.md`](docs/importance-mixture.md) | Six-signal mixture, weight by weight + ablation data |
| [`docs/reconstruction-qa.md`](docs/reconstruction-qa.md) | Compression-fidelity measurement loop |
| [`docs/span-annotation.md`](docs/span-annotation.md) | Sub-turn char-range tier design |
| [`docs/topic-decay.md`](docs/topic-decay.md) | Unsupervised topic segmentation |
| [`docs/claude-code-integration.md`](docs/claude-code-integration.md) | How the bootstrap reads `~/.claude/projects/` |
| [`docs/install.md`](docs/install.md) | Platform matrix, install footprint |
| [`docs/faq.md`](docs/faq.md) | Troubleshooting |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | What lands easily, what needs discussion |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

---

## License

MIT — see [LICENSE](LICENSE).
