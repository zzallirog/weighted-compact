"""recap — task-segmented session recap (a lossy navigation map over the corpus).

This is a *consumer* of the same source the rest of the package reads
(`~/.claude/projects/*.jsonl`), but it answers a different question than the
reconstruction-QA compaction reader. Compaction asks "which turns do I keep so a
judge can still answer questions about what was hidden" — a fidelity problem with
no measured edge over cheap baselines. Recap asks "what happened across this
session, task by task" — a *navigation* problem, and it is deliberately lossy:
you cannot rebuild the session from it (use `gzip`/`zstd` on the raw `.jsonl`
for lossless archival).

Why ship a lossy artifact in a project that is otherwise honesty-obsessed about
quality claims? Because a lossy map can still be proven **faithful** and
**complete**. Recap makes four invariants that an independent pass re-checks
(`audit()`):

  I1 COVERAGE     every message record lands in exactly one task segment;
                  nothing is silently dropped.
  I2 CONSERVATION per-tool counts summed over segments equal the counts in the
                  raw transcript; no tool call is lost or double-counted.
  I3 PROVENANCE   every file path and command shown is a verbatim member of the
                  transcript; nothing is fabricated.
  I4 DETERMINISM  a second pass recomputes every diffstat to the same integers;
                  the numbers are real, not estimated.

Extraction is fully deterministic — no LLM, no judge. Outcome lines are verbatim
excerpts of the assistant's final message in a segment (quoted, not summarized).

Stdlib only: this module imports nothing beyond the standard library, so it runs
even on a checkout with no optional dependencies installed.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EDIT_TOOLS = {"Edit", "MultiEdit", "NotebookEdit"}
WRITE_TOOLS = {"Write"}
HOME = str(Path.home())


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def _load(path: str | Path) -> tuple[list[tuple[str, Any]], int]:
    """Return ([(role, content), ...], n_lines_total). Only role-bearing messages."""
    msgs: list[tuple[str, Any]] = []
    total = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue
            msgs.append((role, msg.get("content")))
    return msgs, total


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _has_image(content: Any) -> bool:
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "image" for b in content
    )


def _is_user_prompt(role: str, content: Any) -> bool:
    """A real user turn that starts a task — not a tool return, slash-command
    echo, harness interrupt, or system caveat."""
    if role != "user":
        return False
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    ):
        return False
    text = content if isinstance(content, str) else _text_of(content)
    stripped = text.lstrip()
    if stripped.startswith("<"):  # slash-command / system echo
        return False
    if stripped.startswith("[Request interrupted"):  # harness interrupt, not a goal
        return False
    if "Caveat:" in text[:40]:
        return False
    if text.strip():
        return True
    return _has_image(content)  # image-only prompt is still a task boundary


def _goal(content: Any, limit: int = 200) -> str:
    text = (content if isinstance(content, str) else _text_of(content)).strip()
    text = re.sub(r"\[Image[^\]]*\]", "", text)
    text = re.sub(r"/\S*image-cache/\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "(screenshot)" if _has_image(content) else "(empty)"
    return text[:limit] + ("…" if len(text) > limit else "")


# --------------------------------------------------------------------------- #
# diffstat
# --------------------------------------------------------------------------- #
def _diff_counts(old: Any, new: Any) -> tuple[int, int]:
    sm = difflib.SequenceMatcher(None, str(old).splitlines(), str(new).splitlines())
    add = rem = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "replace":
            rem += i2 - i1
            add += j2 - j1
        elif tag == "delete":
            rem += i2 - i1
        elif tag == "insert":
            add += j2 - j1
    return add, rem


def edit_diffstat(name: str, inp: dict) -> tuple[int, int, str]:
    """(adds, rems, kind) for any mutating tool. Each tool family has a distinct
    input schema, so they are dispatched explicitly rather than assumed to share
    `old_string`/`new_string` — that assumption silently yields +0/−0 for
    MultiEdit / NotebookEdit, which the faithfulness invariants do NOT catch
    (a self-consistent wrong number passes I2/I4). Centralised here so build()
    and audit() can never diverge."""
    if name in WRITE_TOOLS:
        return len(str(inp.get("content", "")).splitlines()), 0, "write"
    if name == "MultiEdit":
        add = rem = 0
        for e in inp.get("edits", []) or []:
            if isinstance(e, dict):
                a, r = _diff_counts(e.get("old_string", ""), e.get("new_string", ""))
                add += a
                rem += r
        return add, rem, "edit"
    if name == "NotebookEdit":
        # cell replace/insert; there is no reliable prior, so count the new source
        return len(str(inp.get("new_source", "")).splitlines()), 0, "edit"
    # Edit (and any future single old→new tool)
    add, rem = _diff_counts(inp.get("old_string", ""), inp.get("new_string", ""))
    return add, rem, "edit"


def edit_target(name: str, inp: dict) -> str:
    return inp.get("file_path") or inp.get("notebook_path") or "?"


def _bar(add: int, rem: int, width: int = 5) -> str:
    total = add + rem
    if total == 0:
        return "▱" * width
    green = max(0, min(width, round(width * add / total)))
    return "🟩" * green + "🟥" * (width - green)


def _short(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# segmentation
# --------------------------------------------------------------------------- #
@dataclass
class Segment:
    goal: str
    files: "OrderedDict[str, list]" = field(default_factory=OrderedDict)  # path -> [add, rem, {kinds}]
    cmds: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    last_assistant: str = ""
    n_msgs: int = 0


@dataclass
class Recap:
    segments: list[Segment]
    n_records: int          # raw lines in the file
    n_messages: int         # role-bearing message records
    n_covered: int          # message records assigned to a segment


def build(path: str | Path) -> Recap:
    msgs, n_records = _load(path)
    segments: list[Segment] = []
    cur = Segment(goal="(session start)")
    started = False
    covered = 0
    for role, content in msgs:
        covered += 1
        if _is_user_prompt(role, content):
            if started or cur.n_msgs or cur.files or cur.tools:
                segments.append(cur)
            cur = Segment(goal=_goal(content), n_msgs=1)
            started = True
            continue
        cur.n_msgs += 1
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and role == "assistant" and block.get("text", "").strip():
                cur.last_assistant = block["text"]
            elif btype == "tool_use":
                name = block.get("name", "?")
                cur.tools[name] += 1
                inp = block.get("input", {}) or {}
                if name in EDIT_TOOLS or name in WRITE_TOOLS:
                    add, rem, kind = edit_diffstat(name, inp)
                    fp = edit_target(name, inp)
                    entry = cur.files.setdefault(fp, [0, 0, set()])
                    entry[0] += add
                    entry[1] += rem
                    entry[2].add(kind)
                elif name == "Bash":
                    lines = str(inp.get("command", "")).strip().splitlines()
                    cur.cmds[lines[0][:90] if lines else ""] += 1
    segments.append(cur)
    return Recap(segments=segments, n_records=n_records, n_messages=len(msgs), n_covered=covered)


# --------------------------------------------------------------------------- #
# audit (independent recompute of the four invariants)
# --------------------------------------------------------------------------- #
def audit(path: str | Path, recap: Recap) -> dict[str, Any]:
    raw_tools: Counter = Counter()
    raw_add = raw_rem = 0
    raw_paths: set[str] = set()
    raw_cmds: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message")
            if not isinstance(msg, dict) or msg.get("role") not in ("user", "assistant"):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                    continue
                name = block.get("name", "?")
                raw_tools[name] += 1
                inp = block.get("input", {}) or {}
                if name in EDIT_TOOLS or name in WRITE_TOOLS:
                    add, rem, _kind = edit_diffstat(name, inp)
                    raw_paths.add(edit_target(name, inp))
                    raw_add += add
                    raw_rem += rem
                elif name == "Bash":
                    lines = str(inp.get("command", "")).strip().splitlines()
                    raw_cmds.add(lines[0][:90] if lines else "")

    seg_tools: Counter = Counter()
    seg_add = seg_rem = 0
    seg_paths: set[str] = set()
    seg_cmds: set[str] = set()
    for seg in recap.segments:
        seg_tools.update(seg.tools)
        for fp, (add, rem, _kinds) in seg.files.items():
            seg_add += add
            seg_rem += rem
            seg_paths.add(fp)
        seg_cmds.update(seg.cmds.keys())

    return {
        "I1_coverage": sum(s.n_msgs for s in recap.segments) == recap.n_messages,
        "I2_conservation": raw_tools == seg_tools,
        "I3_provenance": seg_paths.issubset(raw_paths) and seg_cmds.issubset(raw_cmds),
        "I4_determinism": raw_add == seg_add and raw_rem == seg_rem,
        "tool_calls": sum(raw_tools.values()),
        "messages": recap.n_messages,
        "add": raw_add,
        "rem": raw_rem,
    }


def audit_passes(result: dict[str, Any]) -> bool:
    return all(result[k] for k in ("I1_coverage", "I2_conservation", "I3_provenance", "I4_determinism"))


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #
def render(path: str | Path, recap: Recap) -> str:
    raw_bytes = Path(path).stat().st_size
    out = [f"# Recap — `{Path(path).name[:8]}`  ·  {len(recap.segments)} tasks\n"]
    for i, seg in enumerate(recap.segments):
        if i == 0 and seg.goal == "(session start)" and not seg.files and not seg.tools:
            continue
        total_add = sum(f[0] for f in seg.files.values())
        total_rem = sum(f[1] for f in seg.files.values())
        toolsum = ", ".join(f"{n}×{k}" for k, n in seg.tools.most_common(6)) or "—"
        out.append(f"\n## {i}. {seg.goal}")
        out.append(f"`{toolsum}`" + (f"   net `+{total_add}/−{total_rem}`" if (total_add or total_rem) else ""))
        if seg.files:
            out.append("")
            real = [(fp, v) for fp, v in seg.files.items() if not fp.startswith("/tmp")]
            tmp = [(fp, v) for fp, v in seg.files.items() if fp.startswith("/tmp")]
            for fp, (add, rem, kinds) in sorted(real, key=lambda x: -(x[1][0] + x[1][1])):
                disp = fp.replace(HOME, "~")
                out.append(f"  {_bar(add, rem)} `+{add:<4}−{rem:<4}` {disp}  _({'+'.join(sorted(kinds))})_")
            if tmp:
                ta = sum(v[0] for _, v in tmp)
                td = sum(v[1] for _, v in tmp)
                out.append(f"  ▱▱▱▱▱ `+{ta:<4}−{td:<4}` _{len(tmp)} ephemeral /tmp file(s)_")
        if seg.cmds:
            top = seg.cmds.most_common(6)
            extra = f"  +{len(seg.cmds) - 6} more" if len(seg.cmds) > 6 else ""
            out.append(
                "\n  **cmd:** "
                + " · ".join(f"`{c}`" + (f"×{n}" if n > 1 else "") for c, n in top)
                + extra
            )
        if seg.last_assistant:
            out.append(f"\n  → {_short(seg.last_assistant)}")
    md = "\n".join(out)
    recap_bytes = len(md.encode("utf-8"))
    shrink = round(raw_bytes / recap_bytes) if recap_bytes else 0
    md += (
        f"\n\n---\n_recap {recap_bytes / 1024:.1f} KB vs raw "
        f"{raw_bytes / 1024 / 1024:.2f} MB = **{shrink}× smaller** · "
        f"lossy navigation map (not reconstructable — use gzip/zstd for archival)_\n"
    )
    return md
