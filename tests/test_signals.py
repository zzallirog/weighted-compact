"""Importance signal composition + density feature sizing.

C2 regression — importance.compose stacks 7 signals (was documented 6
while code already produced 7 for some time; reconciled in v0.2.0-beta.2).
Also: importance.main() must not crash when features_misstep.npz is missing —
the architectural invariant "vectors first, classifier as refinement" requires
graceful degradation to a zero column.

M3 regression — density_features.extract_density returns vectors of
len(FEATURE_NAMES); adding a feature in FEATURE_NAMES must propagate
without editing extract_density's hardcoded site count.
"""

from __future__ import annotations

import importlib

import numpy as np
import pytest


def test_extract_density_returns_feature_names_dims():
    from weighted_compact import density_features as df

    v_text = df.extract_density("hello world")
    v_empty = df.extract_density("")
    assert v_text.shape == (len(df.FEATURE_NAMES),)
    assert v_empty.shape == (len(df.FEATURE_NAMES),)


def _write_npz(path, **arrays):
    np.savez(path, **arrays)


@pytest.fixture
def importance_fixture(monkeypatch, tmp_path):
    """Substrate with the minimum inputs importance.main() consumes."""
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))

    from weighted_compact import config

    importlib.reload(config)

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

    pair_indices = np.array([0, 1, 2], dtype=np.int64)
    # density: (N, 2*D); use D=8 (current FEATURE_NAMES length)
    from weighted_compact import density_features
    D = len(density_features.FEATURE_NAMES)
    density_arr = np.random.rand(len(pair_indices), 2 * D).astype(np.float32)
    _write_npz(
        config.features_density_path(),
        density=density_arr,
        pair_indices=pair_indices,
        labels_3tier=np.array([0, 1, 2], dtype=np.int8),
    )
    # spans: (N, 4) — keep/maybe/skip/think correction-side fractions
    spans_arr = np.array(
        [[0.5, 0.2, 0.1, 0.05],
         [0.0, 0.3, 0.4, 0.10],
         [0.9, 0.0, 0.0, 0.20]],
        dtype=np.float32,
    )
    _write_npz(
        config.features_spans_path(),
        spans=spans_arr,
        pair_indices=pair_indices,
    )
    # No labels.jsonl — load_labels_keep_mask handles absence (returns zeros).
    return tmp_path, pair_indices


def test_importance_composes_seven_signals(importance_fixture):
    from weighted_compact import importance

    importlib.reload(importance)
    importance.main()

    out = np.load(importance.OUT, allow_pickle=True)
    components = out["components"]
    names = list(out["component_names"])

    assert components.shape[1] == 7, "v0.2.0-beta.2 reconciled docs to 7-signal mix"
    assert "span_think_corr" in names, "span_think is the 7th signal added in C2"
    # Weights array also has 7 entries.
    assert out["weights"].shape == (7,)


def test_importance_graceful_when_misstep_missing(importance_fixture):
    """C2 — `vectors first, classifier as refinement`: importance.compose
    must run with a zero misstep column instead of asserting / crashing when
    the predictor was never installed."""
    from weighted_compact import config, importance

    importlib.reload(importance)

    misstep_path = config.features_misstep_path()
    assert not misstep_path.exists(), "fixture invariant: misstep.npz absent"

    # Must not raise.
    importance.main()

    out = np.load(importance.OUT, allow_pickle=True)
    components = out["components"]
    # First column is sig_misstep; with predictor absent it should be all-zero.
    assert np.allclose(components[:, 0], 0.0)

    import json as _json
    meta = _json.loads(str(out["meta"][0]))
    assert meta["misstep_present"] is False
    assert meta["misstep_held_out_auc"] is None


def test_importance_uses_misstep_when_present(importance_fixture):
    """When misstep.npz is present, sig_misstep column reflects it."""
    from weighted_compact import config, importance

    importlib.reload(importance)
    _, pair_indices = importance_fixture

    misstep_vec = np.array([0.9, 0.1, 0.5], dtype=np.float32)
    _write_npz(
        config.features_misstep_path(),
        importance=misstep_vec,
        pair_indices=pair_indices,
        meta=np.array(['{"auc_held_out": 0.665}'], dtype=object),
    )

    importance.main()

    out = np.load(importance.OUT, allow_pickle=True)
    components = out["components"]
    assert np.allclose(components[:, 0], misstep_vec)

    import json as _json
    meta = _json.loads(str(out["meta"][0]))
    assert meta["misstep_present"] is True
    assert meta["misstep_held_out_auc"] == 0.665
