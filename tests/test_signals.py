"""Importance signal composition + density feature sizing.

importance.compose stacks 6 signals: density (backbone), label, and four span
fractions (keep/maybe/skip/think). The machine-learned `misstep` predictor was
removed from the mixture 2026-06-07 (near-chance AUC; absent on fresh installs).

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


def test_importance_composes_six_signals(importance_fixture):
    from weighted_compact import importance

    importlib.reload(importance)
    importance.main()

    out = np.load(importance.OUT, allow_pickle=True)
    components = out["components"]
    names = list(out["component_names"])

    assert components.shape[1] == 6, "mixture is six signals (misstep removed 2026-06-07)"
    assert out["weights"].shape == (6,)
    assert "misstep" not in names, "misstep predictor removed from the mixture"
    assert names[0] == "density", "density is the backbone (first column)"
    assert "span_think_corr" in names


def test_importance_meta_has_no_misstep_keys(importance_fixture):
    """Removing misstep must also drop its meta keys — no stale provenance."""
    from weighted_compact import importance

    importlib.reload(importance)
    importance.main()

    out = np.load(importance.OUT, allow_pickle=True)
    import json as _json
    meta = _json.loads(str(out["meta"][0]))
    assert "misstep_present" not in meta
    assert "misstep_held_out_auc" not in meta
