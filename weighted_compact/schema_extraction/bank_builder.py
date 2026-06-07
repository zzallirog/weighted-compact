"""schema_extraction.bank_builder — auto-collect case bank from memory dir.

Walks Claude Code memory directories (`~/.claude/projects/*/memory/`) and any
provided HANDOFF roots, finds files that look like resolved/stable cases by
heuristic patterns, then uses local LLM to extract a structured rule from each.

Output: case-bank.yaml in $XDG_DATA_HOME/weighted-compact/. Bank file stays
local — never committed, never uploaded.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from .. import config
from ._constants import (
    BANK_BUILD_PROMPT,
    CANDIDATE_PATTERNS,
    DATE_RE,
    EXTRACT_MODEL,
    MAX_CONTEXT_CHARS,
)
from .synthesizer import ollama_generate

CANDIDATE_RE = re.compile("|".join(CANDIDATE_PATTERNS), re.IGNORECASE)
DATE_PATTERN = re.compile(DATE_RE)


@dataclass
class Candidate:
    case_id: str
    source_path: Path
    source_ref: str
    content: str


def discover_memory_roots() -> list[Path]:
    """Return memory dirs under ~/.claude/projects/*/memory/."""
    roots: list[Path] = []
    for src in config.claude_source_dirs():
        if not src.exists():
            continue
        for project_dir in src.iterdir():
            mem = project_dir / "memory"
            if mem.is_dir():
                roots.append(mem)
    return roots


def discover_handoff_roots() -> list[Path]:
    """Optional HANDOFF directories — best-effort discovery."""
    roots: list[Path] = []
    candidate = Path.home() / ".claude" / "work"
    if candidate.is_dir():
        roots.append(candidate)
    return roots


def iter_candidates(roots: list[Path]) -> Iterator[Candidate]:
    """Yield candidate files matching stability/resolved patterns."""
    seen: set[Path] = set()
    for root in roots:
        for path in root.rglob("*.md"):
            if path in seen:
                continue
            seen.add(path)
            try:
                content = path.read_text(errors="ignore")
            except OSError:
                continue
            if not CANDIDATE_RE.search(content):
                continue
            case_id = _path_to_id(path)
            source_ref = path.stem if path.parent.name == "memory" else f"{path.parent.name}/{path.stem}"
            yield Candidate(
                case_id=case_id,
                source_path=path,
                source_ref=source_ref,
                content=content[:MAX_CONTEXT_CHARS],
            )


def _path_to_id(path: Path) -> str:
    stem = path.stem
    if stem.startswith("project_"):
        return stem[len("project_"):].replace("_", "-")
    if stem.startswith("zone_"):
        return f"zone-{stem[len('zone_'):].replace('_', '-')}"
    if stem.upper() == "HANDOFF":
        return f"handoff-{path.parent.name}"
    return stem.lower().replace("_", "-")


def extract_case(cand: Candidate, model: str = EXTRACT_MODEL) -> dict | None:
    """Use LLM to extract a case entry from a candidate file. Returns None if NO_RULE."""
    prompt = BANK_BUILD_PROMPT.format(content=cand.content)
    raw, _ = ollama_generate(model, prompt)
    parsed = _parse_case_block(raw)
    if parsed is None:
        return None
    stable_since = parsed.get("stable_since")
    if not stable_since:
        m = DATE_PATTERN.search(cand.content)
        stable_since = m.group(1) if m else None
    return {
        "id": cand.case_id,
        "trigger_phrase": parsed["trigger"],
        "expected_rule": parsed["rule"],
        "anti_pattern_fragment": parsed["anti"],
        "source_episodes": [cand.source_ref],
        "stable_since": stable_since,
        "last_contradicted_at": None,
    }


def _parse_case_block(text: str) -> dict[str, str | None] | None:
    if "NO_RULE" in text.upper():
        return None
    out: dict[str, str | None] = {"trigger": "", "rule": "", "anti": "", "stable_since": None}
    keys = {"TRIGGER:": "trigger", "RULE:": "rule", "ANTI:": "anti", "STABLE_SINCE:": "stable_since"}
    for line in text.splitlines():
        for prefix, key in keys.items():
            if line.strip().upper().startswith(prefix):
                value = line.split(":", 1)[1].strip()
                if key == "stable_since" and value.lower() in ("null", "none", "n/a", ""):
                    out[key] = None
                else:
                    out[key] = value
                break
    if not (out["trigger"] and out["rule"]):
        return None
    return out


def build_bank(force: bool = False, verbose: bool = True) -> Path:
    """Build case-bank.yaml from discovered memory + HANDOFF roots.

    Idempotent: if bank file exists and force is False, returns existing path
    without re-running LLM extraction.
    """
    bank_path = config.schema_bank_path()
    bank_path.parent.mkdir(parents=True, exist_ok=True)

    if bank_path.exists() and not force:
        if verbose:
            print(f"[bank] already exists: {bank_path} (use --force to rebuild)")
        return bank_path

    roots = discover_memory_roots() + discover_handoff_roots()
    if not roots:
        print("[bank] no memory or HANDOFF roots discovered — nothing to scan", file=sys.stderr)
        return bank_path

    candidates = list(iter_candidates(roots))
    if verbose:
        print(f"[bank] {len(candidates)} candidate files match stability patterns")

    cases: list[dict] = []
    for i, cand in enumerate(candidates, 1):
        if verbose:
            print(f"[bank {i}/{len(candidates)}] {cand.case_id} ... ", end="", flush=True)
        try:
            case = extract_case(cand)
        except (OSError, ValueError) as e:
            if verbose:
                print(f"ERROR: {e}")
            continue
        if case is None:
            if verbose:
                print("NO_RULE (skip)")
            continue
        cases.append(case)
        if verbose:
            print("ok")

    payload = {
        "cases": cases,
        "_meta": {
            "generated_by": "weighted-compact schema build-bank",
            "model": EXTRACT_MODEL,
            "candidates_scanned": len(candidates),
            "cases_extracted": len(cases),
        },
    }
    with bank_path.open("w") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
    if verbose:
        print(f"[bank] wrote {len(cases)} cases to {bank_path}")
    return bank_path
