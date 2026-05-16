"""Smoke tests — import every framework module, exercise the trivial paths.

These run under CI with WEIGHTED_COMPACT_DATA pointed at a tmp dir. They
must not require a real substrate, real sessions, or network access. Tests
that need a corpus belong in tests/integration/ (not run by default).
"""

from __future__ import annotations

import importlib
import json
import os

import pytest


FRAMEWORK_MODULES = [
    "weighted_compact",
    "weighted_compact.config",
    "weighted_compact.cli",
]


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


def test_config_paths_resolve_under_tmp(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # Force reimport so the env override takes effect.
    import importlib

    from weighted_compact import config

    importlib.reload(config)
    assert config.workdir() == tmp_path / "data"
    assert config.pairs_path() == tmp_path / "data" / "pairs.jsonl"
    assert config.state_dir() == tmp_path / "state" / "weighted-compact"


def test_config_port_override(monkeypatch) -> None:
    monkeypatch.setenv("WEIGHTED_COMPACT_PORT", "55555")
    import importlib

    from weighted_compact import config

    importlib.reload(config)
    assert config.labeler_port() == 55555


def test_config_claude_sources_override(monkeypatch, tmp_path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", f"{a}:{b}")
    import importlib

    from weighted_compact import config

    importlib.reload(config)
    sources = config.claude_source_dirs()
    assert sources == [a, b]


def test_cli_version(tmp_path, monkeypatch) -> None:
    from click.testing import CliRunner

    from weighted_compact.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "weighted-compact" in result.output


def test_cli_compat_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))

    from click.testing import CliRunner

    from weighted_compact import cli, config

    # Reload so the env vars are picked up.
    import importlib

    importlib.reload(config)
    importlib.reload(cli)

    runner = CliRunner()
    result = runner.invoke(cli.main, ["compat", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"]
    assert "substrate" in payload
    assert payload["substrate"]["exists"] is False


def test_cli_paths(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))

    from click.testing import CliRunner

    from weighted_compact import cli, config

    import importlib

    importlib.reload(config)
    importlib.reload(cli)

    runner = CliRunner()
    result = runner.invoke(cli.main, ["paths"])
    assert result.exit_code == 0
    assert "WEIGHTED_COMPACT_DATA=" in result.output
    assert str(tmp_path / "data") in result.output
