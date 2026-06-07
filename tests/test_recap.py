"""Tests for the recap consumer — synthetic fixtures only, no real data.

Recap is a lossy navigation map, so it cannot be checked by reconstruction.
What CAN be checked is faithfulness: the four invariants in `recap.audit`.
These tests pin them on a hand-built session whose answers we know exactly,
plus the edge cases that broke earlier drafts (image-only prompts, harness
interrupts, repeated edits to one file).
"""
import json

from weighted_compact import recap


def _session(records: list[dict]) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


def _write(tmp_path, records):
    p = tmp_path / "synthetic.jsonl"
    p.write_text(_session(records))
    return p


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _assistant_tools(blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}}


def _tool_result(tool_id, text):
    return {"type": "user", "message": {"role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}


def test_invariants_pass_on_a_normal_session(tmp_path):
    records = [
        _user("fix the off-by-one in the loop"),
        _assistant_tools([
            {"type": "text", "text": "Looking now."},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/proj/a.py"}},
        ]),
        _tool_result("t1", "1\tfor i in range(n):"),
        _assistant_tools([
            {"type": "tool_use", "id": "t2", "name": "Edit",
             "input": {"file_path": "/proj/a.py",
                       "old_string": "for i in range(n):",
                       "new_string": "for i in range(n + 1):\n    pass"}},
            {"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "pytest -q"}},
            {"type": "text", "text": "Fixed and tests pass."},
        ]),
        _tool_result("t3", "1 passed"),
    ]
    p = _write(tmp_path, records)
    rc = recap.build(p)
    result = recap.audit(p, rc)
    assert recap.audit_passes(result), result
    # one Edit = +2/-1 (replace 1 line with 2 lines)
    assert result["add"] == 2 and result["rem"] == 1
    assert result["tool_calls"] == 3
    md = recap.render(p, rc)
    assert "fix the off-by-one" in md
    assert "/proj/a.py" in md
    assert "Fixed and tests pass." in md  # outcome is the verbatim final assistant line


def test_conservation_holds_across_two_tasks(tmp_path):
    records = [
        _user("task one"),
        _assistant_tools([{"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "ls"}}]),
        _tool_result("a", "files"),
        _user("task two"),
        _assistant_tools([
            {"type": "tool_use", "id": "b", "name": "Write",
             "input": {"file_path": "/proj/new.py", "content": "x = 1\ny = 2\n"}},
            {"type": "tool_use", "id": "c", "name": "Bash", "input": {"command": "ls"}},
        ]),
        _tool_result("c", "files"),
    ]
    p = _write(tmp_path, records)
    rc = recap.build(p)
    result = recap.audit(p, rc)
    assert recap.audit_passes(result), result
    assert result["tool_calls"] == 3            # 2 Bash + 1 Write, none lost across the boundary
    assert result["add"] == 2                   # Write of two lines counts as +2
    # the two distinct user prompts produced two task segments
    goals = [s.goal for s in rc.segments]
    assert "task one" in goals and "task two" in goals


def test_image_only_and_interrupt_are_handled(tmp_path):
    records = [
        _user([{"type": "image", "source": {}}]),                       # image-only prompt
        _assistant_tools([{"type": "tool_use", "id": "i", "name": "Bash", "input": {"command": "echo hi"}}]),
        _tool_result("i", "hi"),
        _user("[Request interrupted by user for tool use]"),            # harness interrupt, NOT a goal
        _assistant_tools([{"type": "text", "text": "ok"}]),
    ]
    p = _write(tmp_path, records)
    rc = recap.build(p)
    result = recap.audit(p, rc)
    assert recap.audit_passes(result), result
    goals = [s.goal for s in rc.segments]
    assert "(screenshot)" in goals                                      # image-only labeled, not blank
    assert not any(g.startswith("[Request interrupted") for g in goals)  # interrupt absorbed, no fake task


def test_repeated_edits_to_one_file_accumulate(tmp_path):
    records = [
        _user("refactor"),
        _assistant_tools([
            {"type": "tool_use", "id": "e1", "name": "Edit",
             "input": {"file_path": "/proj/x.py", "old_string": "a", "new_string": "b\nc"}},
            {"type": "tool_use", "id": "e2", "name": "Edit",
             "input": {"file_path": "/proj/x.py", "old_string": "d", "new_string": "e"}},
        ]),
    ]
    p = _write(tmp_path, records)
    rc = recap.build(p)
    result = recap.audit(p, rc)
    assert recap.audit_passes(result)
    # both edits land on the same file entry; determinism invariant cross-checks totals
    seg = [s for s in rc.segments if s.goal == "refactor"][0]
    assert "/proj/x.py" in seg.files
    add, rem, kinds = seg.files["/proj/x.py"]
    assert add == 3 and rem == 2 and kinds == {"edit"}   # (+2/-1) + (+1/-1)
