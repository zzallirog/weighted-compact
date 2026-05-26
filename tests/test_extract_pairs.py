"""Regression tests for extract_pairs subdir glob walk.

The bug: Claude Code stores sessions under per-project subdirs
(~/.claude/projects/<slug>/*.jsonl). extract_pairs.py originally globbed
only the source root flat, returning 0 sessions for every user.

These tests pin the two layouts the glob must handle:
  1. flat: <source>/<session>.jsonl  (legacy / minimal harness)
  2. subdir: <source>/<slug>/<session>.jsonl  (current Claude Code layout)
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest


SESSION_JSONL = "\n".join([
    json.dumps({
        "type": "assistant",
        "uuid": "u-asm-1",
        "message": {"content": "Run the migration with --apply flag to commit changes."},
    }),
    json.dumps({
        "type": "user",
        "uuid": "u-usr-1",
        "message": {"content": "не то, нужно --dry-run сначала проверить"},
    }),
]) + "\n"


def _run_extract(tmpdir, sources_value, expect_pairs_min=1):
    """Run extract_pairs as a subprocess against a tmp substrate, return stats."""
    env = os.environ.copy()
    env["WEIGHTED_COMPACT_DATA"] = str(tmpdir / "substrate")
    env["WEIGHTED_COMPACT_CLAUDE_SOURCES"] = sources_value
    (tmpdir / "substrate").mkdir(parents=True, exist_ok=True)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "-m", "weighted_compact.extract_pairs"],
        env=env,
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    pairs_path = tmpdir / "substrate" / "pairs.jsonl"
    assert pairs_path.exists(), f"pairs.jsonl not written: {result.stdout}"

    with open(pairs_path) as f:
        pairs = [json.loads(line) for line in f if line.strip()]

    return pairs, result.stdout


def test_glob_walks_subdir_layout(tmp_path):
    """Sessions under <source>/<slug>/<session>.jsonl must be picked up."""
    source = tmp_path / "claude-projects"
    project = source / "-home-user-foo"
    project.mkdir(parents=True)
    session = project / "abc-123.jsonl"
    # Inflate so file passes MIN_FILE_SIZE check (5 KiB).
    session.write_text(SESSION_JSONL + ("\n" * 5500))

    pairs, stdout = _run_extract(tmp_path, str(source))
    assert len(pairs) >= 1, f"expected at least 1 pair from subdir layout: {stdout}"


def test_glob_walks_flat_layout(tmp_path):
    """Legacy flat layout <source>/<session>.jsonl still works."""
    source = tmp_path / "claude-projects"
    source.mkdir(parents=True)
    session = source / "abc-456.jsonl"
    session.write_text(SESSION_JSONL + ("\n" * 5500))

    pairs, stdout = _run_extract(tmp_path, str(source))
    assert len(pairs) >= 1, f"expected at least 1 pair from flat layout: {stdout}"


def test_ru_marker_is_detected(tmp_path):
    """`не то` (RU correction) must trigger pair extraction."""
    source = tmp_path / "claude-projects"
    project = source / "-slug"
    project.mkdir(parents=True)
    session = project / "ru-marker.jsonl"
    session.write_text(SESSION_JSONL + ("\n" * 5500))

    pairs, _ = _run_extract(tmp_path, str(source))
    assert len(pairs) >= 1
    # The RU `не то` should be the trigger here (no EN-only word in user msg).
    assert any("не то" in p.get("marker_match", "").lower() for p in pairs)
