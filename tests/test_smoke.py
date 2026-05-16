"""Smoke tests — import every framework module, exercise the trivial paths.

These run under CI with WEIGHTED_COMPACT_DATA pointed at a tmp dir. They
must not require a real substrate, real sessions, or network access. Tests
that need a corpus belong in tests/integration/ (not run by default).
"""

from __future__ import annotations

import importlib
import json

import pytest


FRAMEWORK_MODULES = [
    "weighted_compact",
    "weighted_compact.config",
    "weighted_compact.cli",
]


@pytest.fixture
def isolated_substrate(monkeypatch, tmp_path):
    """Point the package at a fresh substrate dir and reload config/cli so
    env-derived constants are re-resolved."""
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))

    from weighted_compact import cli, config

    importlib.reload(config)
    importlib.reload(cli)
    return tmp_path


@pytest.mark.parametrize("name", FRAMEWORK_MODULES)
def test_import(name: str) -> None:
    importlib.import_module(name)


def test_optional_modules_importable_when_deps_present() -> None:
    """Modules that pull numpy/sklearn/etc. should still import when those
    deps are installed (CI installs `dev` extras only, so we skip when not)."""
    try:
        import numpy  # noqa: F401
    except ImportError:
        pytest.skip("numpy not installed")
    for name in [
        "weighted_compact.extract_pairs",
        "weighted_compact.density_features",
        "weighted_compact.topic_segments",
        "weighted_compact.importance",
        "weighted_compact.build_queue",
        "weighted_compact.auto_label",
        "weighted_compact.label_pairs",
        "weighted_compact.span_features",
    ]:
        importlib.import_module(name)


def test_config_paths_resolve_under_tmp(isolated_substrate) -> None:
    from weighted_compact import config

    assert config.workdir() == isolated_substrate / "data"
    assert config.pairs_path() == isolated_substrate / "data" / "pairs.jsonl"
    assert config.state_dir() == isolated_substrate / "state" / "weighted-compact"


def test_config_port_override(monkeypatch) -> None:
    monkeypatch.setenv("WEIGHTED_COMPACT_PORT", "55555")
    from weighted_compact import config

    importlib.reload(config)
    assert config.labeler_port() == 55555


def test_config_claude_sources_override(monkeypatch, tmp_path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", f"{a}:{b}")
    from weighted_compact import config

    importlib.reload(config)
    assert config.claude_source_dirs() == [a, b]


def test_label_key_map_matches_canonical_tiers() -> None:
    from weighted_compact.config import ANNOTATION_TIERS, LABEL_KEY_MAP

    # Every shortcut maps to a name in the annotation tier set, plus the
    # CLI sentinel `false_positive` which is a label, not a span tier.
    extras = {"false_positive"}
    assert set(LABEL_KEY_MAP.values()) <= ANNOTATION_TIERS | extras


def test_cli_version() -> None:
    from click.testing import CliRunner

    from weighted_compact.cli import main

    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "weighted-compact" in result.output


def test_cli_compat_json(isolated_substrate) -> None:
    from click.testing import CliRunner

    from weighted_compact import cli

    result = CliRunner().invoke(cli.main, ["compat", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"]
    assert "substrate" in payload
    assert payload["substrate"]["exists"] is False


def test_cli_paths(isolated_substrate) -> None:
    from click.testing import CliRunner

    from weighted_compact import cli

    result = CliRunner().invoke(cli.main, ["paths"])
    assert result.exit_code == 0
    assert "WEIGHTED_COMPACT_DATA=" in result.output
    assert str(isolated_substrate / "data") in result.output
