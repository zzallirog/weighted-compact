"""Annotation schema backward-compat: char_start/char_end without char_range.

The frontend reads `char_range[0]` / `char_range[1]`. Annotations written
through the POST API always include `char_range`. Hand-written or migrated
fixtures sometimes carry `char_start` / `char_end` instead — without
normalization on load the labeler crashed silently with
"Cannot read properties of undefined (reading '0')" (caught while
producing v0.0.1 screenshots, 2026-05-16).
"""

from __future__ import annotations

import importlib
import json


def test_reload_normalizes_char_start_end_to_char_range(monkeypatch, tmp_path):
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))

    from weighted_compact import config

    importlib.reload(config)

    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    annotations = [
        # Legacy form: char_start / char_end only
        {"id": 1, "pair_idx": 0, "side": "correction",
         "char_start": 5, "char_end": 12, "marker": "keep", "note": "", "ts": 1},
        # Modern form: char_range already present
        {"id": 2, "pair_idx": 0, "side": "premise",
         "char_range": [0, 8], "marker": "skip", "note": "", "ts": 2},
    ]
    config.annotations_path().write_text(
        "\n".join(json.dumps(a) for a in annotations) + "\n"
    )
    # Empty pairs + features so reload_state doesn't choke on missing files
    config.pairs_path().write_text("")

    from weighted_compact import tool

    importlib.reload(tool)
    tool.reload_state()

    grouped = tool.STATE["annotations_by_pair"][0]
    assert len(grouped) == 2
    by_id = {a["id"]: a for a in grouped}
    # Legacy entry must now expose char_range
    assert by_id[1]["char_range"] == [5, 12]
    # Modern entry untouched
    assert by_id[2]["char_range"] == [0, 8]
