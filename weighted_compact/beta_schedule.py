"""β-schedule: single scalar β → 7 signal weights for WC importance mixture.

AutoTTS-inspired monotone parameterisation.  One scalar β ∈ [0, 1] drives all
seven weights deterministically, reducing the effective search dimension from 7
to 1.  CMA-ES in beta_search.py then searches a 3-D perturbation space
(β, Δ_misstep, Δ_skip) instead of raw 7-D — the β-bottleneck regulariser.

Anchor calibration:
    β = 0.5  →  weights close to hand-tuned defaults in importance.py:
        misstep=0.35  density=0.25  label=0.125  span_keep=0.20
        span_maybe=0.10  span_think=0.05  span_skip=-0.175

Monotone directions (dW/dβ sign):
    w_misstep   ↑  (more β → trust ML signal more)
    w_density   ↓  (more β → compress density-only signal)
    w_label     ↓  (more β → trust labels less, lean on richer signals)
    w_span_keep →  (constant: explicit keep label is β-independent)
    w_span_maybe→  (constant)
    w_span_think→  (constant)
    w_span_skip ↑  (penalty weakens with β, i.e. |w_skip| ↓)

All assertions are checked at module load for the β ∈ {0, 0.5, 1} knot set.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class WCBetaSchedule:
    """Frozen weight schedule derived from scalar β ∈ [0, 1].

    Construct via :func:`beta_schedule` factory, not directly.
    """

    beta: float

    # ------------------------------------------------------------------
    # Seven signal weights — monotone functions of β.
    # ------------------------------------------------------------------

    @property
    def w_misstep(self) -> float:
        """Growing with β: 0.20 at β=0, 0.35 at β=0.5, 0.50 at β=1."""
        return 0.20 + 0.30 * self.beta

    @property
    def w_density(self) -> float:
        """Shrinking with β: 0.30 at β=0, 0.25 at β=0.5, 0.20 at β=1."""
        return 0.30 - 0.10 * self.beta

    @property
    def w_label(self) -> float:
        """Shrinking with β: 0.15 at β=0, 0.125 at β=0.5, 0.10 at β=1."""
        return 0.15 - 0.05 * self.beta

    @property
    def w_span_keep(self) -> float:
        """Constant at 0.20 — explicit keep annotation is β-independent."""
        return 0.20

    @property
    def w_span_maybe(self) -> float:
        """Constant at 0.10."""
        return 0.10

    @property
    def w_span_think(self) -> float:
        """Constant at 0.05."""
        return 0.05

    @property
    def w_span_skip(self) -> float:
        """Penalty weakening with β: −0.25 at β=0, −0.175 at β=0.5, −0.10 at β=1.

        Note: *more negative* = stricter SKIP penalty.  Penalty *weakens*
        (absolute value shrinks) as β increases.
        """
        return -(0.25 - 0.15 * self.beta)

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    def as_dict(self) -> dict[str, float]:
        """Return all 7 weights as {signal_name: weight}."""
        return {
            "misstep":    self.w_misstep,
            "density":    self.w_density,
            "label":      self.w_label,
            "span_keep":  self.w_span_keep,
            "span_maybe": self.w_span_maybe,
            "span_think": self.w_span_think,
            "span_skip":  self.w_span_skip,
        }

    def as_vector(self) -> np.ndarray:
        """Return weight vector in canonical importance.py order.

        Order: [misstep, density, label, span_keep, span_maybe, span_skip, span_think]
        Matches the ``components`` axis-1 layout from importance.py.
        """
        return np.array([
            self.w_misstep,
            self.w_density,
            self.w_label,
            self.w_span_keep,
            self.w_span_maybe,
            self.w_span_skip,    # negative (penalty)
            self.w_span_think,
        ], dtype=np.float64)

    def positive_sum(self) -> float:
        """Sum of the six non-negative weights (excludes span_skip penalty)."""
        return (
            self.w_misstep + self.w_density + self.w_label
            + self.w_span_keep + self.w_span_maybe + self.w_span_think
        )

    def verify_monotonicity(self, n_points: int = 21) -> None:
        """Assert all knobs are sign-consistent across β ∈ [0, 1].

        Raises AssertionError with descriptive message on violation.
        """
        betas = np.linspace(0.0, 1.0, n_points)
        schedules = [WCBetaSchedule(float(b)) for b in betas]

        _check_mono_increasing([s.w_misstep for s in schedules], "w_misstep")
        _check_mono_decreasing([s.w_density for s in schedules], "w_density")
        _check_mono_decreasing([s.w_label for s in schedules], "w_label")
        # span_keep, span_maybe, span_think are constants — trivially monotone
        # span_skip goes from -0.25 → -0.10 (increasing, i.e. penalty weakens)
        _check_mono_increasing([s.w_span_skip for s in schedules], "w_span_skip")


# ------------------------------------------------------------------
# Module-level factory + verification
# ------------------------------------------------------------------

def beta_schedule(beta: float) -> WCBetaSchedule:
    """Return a WCBetaSchedule for the given β ∈ [0, 1].

    β is clamped silently to [0, 1] to avoid hard failures at boundary
    candidates during CMA-ES search.
    """
    beta = float(np.clip(beta, 0.0, 1.0))
    return WCBetaSchedule(beta=beta)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _check_mono_increasing(values: list[float], name: str) -> None:
    for i in range(len(values) - 1):
        assert values[i] <= values[i + 1] + 1e-9, (
            f"Monotonicity violation: {name}[{i}]={values[i]:.6f} > "
            f"{name}[{i+1}]={values[i+1]:.6f}"
        )


def _check_mono_decreasing(values: list[float], name: str) -> None:
    for i in range(len(values) - 1):
        assert values[i] >= values[i + 1] - 1e-9, (
            f"Monotonicity violation: {name}[{i}]={values[i]:.6f} < "
            f"{name}[{i+1}]={values[i+1]:.6f}"
        )


# ------------------------------------------------------------------
# Anchor verification at import time (cheap — 21 scalar evals)
# ------------------------------------------------------------------

def _verify_anchor() -> None:
    """Verify β=0.5 anchor is near hand-tuned defaults and all knobs monotone."""
    s_half = beta_schedule(0.5)

    # Anchor checks: β=0.5 should be close to importance.py WEIGHTS
    _tol = 0.06  # tolerance: within 6pp of hand-tuned value
    assert abs(s_half.w_misstep - 0.35) <= _tol, (
        f"β=0.5 anchor: w_misstep={s_half.w_misstep:.3f}, expected ~0.35"
    )
    assert abs(s_half.w_density - 0.25) <= _tol, (
        f"β=0.5 anchor: w_density={s_half.w_density:.3f}, expected ~0.25"
    )
    assert abs(s_half.w_span_keep - 0.20) <= _tol, (
        f"β=0.5 anchor: w_span_keep={s_half.w_span_keep:.3f}, expected ~0.20"
    )

    # Boundary checks
    s0 = beta_schedule(0.0)
    s1 = beta_schedule(1.0)
    assert s0.w_misstep < s1.w_misstep, "w_misstep must grow with β"
    assert s0.w_density > s1.w_density, "w_density must shrink with β"
    assert s0.w_span_skip < s1.w_span_skip, "w_span_skip must increase (penalty weakens) with β"

    # Full monotonicity check
    s_half.verify_monotonicity()


_verify_anchor()
