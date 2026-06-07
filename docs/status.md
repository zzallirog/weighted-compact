# Status — full component table

Contributor-facing detailed status. The README carries a 6-row
user-facing summary; this file is the full 18-row inventory.

## Component status

| Component | Status |
|---|---|
| Substrate (extract_pairs + e5 features) | shipped |
| Importance mixture (6 signals + topic-decay multiplier) | shipped |
| Span-level annotations | shipped |
| Drift inspector + iter chain | shipped (`v0.2.0-beta.1`) |
| Per-pair fidelity (conflict / fidelity modes) | shipped (`v0.2.0-beta.1`) |
| Reconstruction-QA loop (W3) | end-to-end + Sonnet baseline measured 2026-05-21; gate→labeling-queue routing partial |
| `recon_qa/` package split (5 black boxes) | shipped (`v0.2.0-beta.1`) |
| `weighted-compact qa-gate` CLI | shipped |
| Cheap-judge calibration (cross-family) | shipped — κ=0.47 vs Sonnet on gemma3:4b |
| Anchor-pattern catalogue (what survives compaction) | shipped — technical identifiers + numeric anchors + short verbatim |
| `weighted-compact recap` (task-segmented navigation map) | shipped — stdlib-only, ~5 ms/session; 4-invariant audit (coverage/conservation/provenance/determinism); see [`recap.md`](recap.md) |
| W2 — ambient render layer | next (target `v0.2.x`) — anchor patterns identified, verbatim-tier policy waiting |
| Full coefficient-grid ablation (`--weights` wrapper) | filed (`v0.3`) |
| Anti-baseline vs `/compact` | **shipped + measured 2026-05-21** — 8 pp gap vs qwen-summary (mixture 11.3 % vs 3.2 %, N=62, gemma3:4b judge); no measured edge vs random/recency/cosine at N=62; see [`baselines.md`](baselines.md) |
| Baseline harness (6 structured rankers + `/compact` sim) | shipped (`v0.2.0-beta.2`) — `weighted-compact baseline run-all`; null result for mixture vs random/recency/cosine at N=62 |
| Iter-chain mode-distinction QC | parked — modes show bleed under qwen-7b, redesign filed |
| Classifier-as-fidelity-proxy | parked — current features don't predict Sonnet labels (AUC ≈ 0.5) |
| Cross-session correlation | `v0.3` direction |
| Decision-anticipation layer | `v0.4+` direction |

## Reading the status table

- **shipped** — runs end-to-end on the maintainer's corpus; tested in CI
  where applicable; documented module contract.
- **next** — scaffold exists, completion is the next development push.
- **filed** — work is named and scoped, not started.
- **parked** — was attempted, did not work under current conditions,
  redesign filed.
- ***vX.Y* direction** — strategic direction, not concretely scheduled.

The 2026-05-21 honest-baseline run with Sonnet 4.6 turned several
scaffolded items into measured ones — and surfaced two known limitations
(iter-chain mode bleed, classifier-proxy not learning). See
[`05-roadmap.md`](05-roadmap.md) for full breakdown.
