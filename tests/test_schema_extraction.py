"""Smoke tests for schema_extraction sub-package.

These tests do NOT call Ollama. They verify:
    - Package imports cleanly with no network / no LLM.
    - CLI subgroup mounts under main `weighted-compact`.
    - Paths resolve under $XDG_DATA_HOME.
    - Bank format parses (YAML round-trip).
    - Verdict parser maps tokens correctly.

Integration tests that hit a live Ollama belong in tests/integration/
(not in this file, not run in CI by default).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from weighted_compact import config, schema_extraction
from weighted_compact.schema_extraction import bank_builder, judge
from weighted_compact.schema_extraction._constants import EXTRACT_MODEL, JUDGE_MODEL


def test_package_imports_cleanly():
    assert hasattr(schema_extraction, "build_bank")
    assert hasattr(schema_extraction, "run_pipeline")
    assert hasattr(schema_extraction, "synthesize_rule")
    assert hasattr(schema_extraction, "judge_rule")


def test_cli_subgroup_mounted():
    from weighted_compact.cli import main as cli_main

    assert "schema" in cli_main.commands
    schema_group = cli_main.commands["schema"]
    assert {"build-bank", "run", "all", "paths"}.issubset(set(schema_group.commands.keys()))


def test_paths_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path))
    assert config.schema_bank_path() == tmp_path / "schema-bank.yaml"
    assert config.schema_runs_dir() == tmp_path / "schema-runs"


def test_verdict_parser():
    assert judge._parse_verdict("MATCH") == "MATCH"
    assert judge._parse_verdict("the verdict is NEAR.") == "NEAR"
    assert judge._parse_verdict("MISMATCH — different rule") == "MISMATCH"
    assert judge._parse_verdict("я не уверен") == "PARSE_FAIL"


def test_case_block_parser():
    block = """TRIGGER: when X happens
RULE: do Y
ANTI: don't do Z
STABLE_SINCE: 2026-01-15"""
    parsed = bank_builder._parse_case_block(block)
    assert parsed is not None
    assert parsed["trigger"] == "when X happens"
    assert parsed["rule"] == "do Y"
    assert parsed["anti"] == "don't do Z"
    assert parsed["stable_since"] == "2026-01-15"


def test_case_block_parser_no_rule():
    assert bank_builder._parse_case_block("NO_RULE") is None


def test_case_block_parser_missing_required():
    assert bank_builder._parse_case_block("TRIGGER: something") is None


def test_bank_yaml_roundtrip(tmp_path):
    bank = {
        "cases": [
            {
                "id": "test-case",
                "trigger_phrase": "когда X",
                "expected_rule": "сделать Y",
                "anti_pattern_fragment": "не делать Z",
                "source_episodes": ["project_test"],
                "stable_since": "2026-01-01",
                "last_contradicted_at": None,
            }
        ]
    }
    bank_path = tmp_path / "schema-bank.yaml"
    with bank_path.open("w") as f:
        yaml.safe_dump(bank, f, allow_unicode=True, sort_keys=False)
    with bank_path.open() as f:
        loaded = yaml.safe_load(f)
    assert loaded == bank


def test_default_models_are_local():
    assert EXTRACT_MODEL.startswith(("gemma", "qwen", "llama"))
    assert JUDGE_MODEL.startswith(("gemma", "qwen", "llama"))


def test_path_to_id_normalization():
    assert bank_builder._path_to_id(Path("project_foo_bar.md")) == "foo-bar"
    assert bank_builder._path_to_id(Path("zone_baz.md")) == "zone-baz"
    assert bank_builder._path_to_id(Path("/abc/work/some-feature/HANDOFF.md")) == "handoff-some-feature"


def test_discover_returns_lists():
    mem_roots = bank_builder.discover_memory_roots()
    handoff_roots = bank_builder.discover_handoff_roots()
    assert isinstance(mem_roots, list)
    assert isinstance(handoff_roots, list)
