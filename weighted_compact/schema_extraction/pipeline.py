"""schema_extraction.pipeline — orchestrate full proof run.

Sequence: load (or build) case-bank → for each case load source content →
synthesize rule → judge against expected → write reports.

This is the entry point for `weighted-compact schema run`.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import yaml

from .. import config
from ._constants import EXTRACT_MODEL, JUDGE_MODEL, MAX_CONTEXT_CHARS
from .bank_builder import build_bank, discover_handoff_roots, discover_memory_roots
from .judge import judge_rule
from .report import CaseResult, write_run
from .synthesizer import synthesize_rule


def load_source_content(source_episodes: list[str]) -> tuple[str, list[str]]:
    """Resolve source refs against discovered memory + HANDOFF roots."""
    parts: list[str] = []
    found: list[str] = []
    roots = discover_memory_roots() + discover_handoff_roots()
    for ref in source_episodes:
        path = _resolve_ref(ref, roots)
        if path and path.exists():
            try:
                parts.append(f"### {ref}\n{path.read_text(errors='ignore')}")
                found.append(ref)
            except OSError:
                continue
    content = "\n\n".join(parts)
    if len(content) > MAX_CONTEXT_CHARS:
        content = content[:MAX_CONTEXT_CHARS] + "\n[...truncated...]"
    return content, found


def _resolve_ref(ref: str, roots: list[Path]) -> Path | None:
    for root in roots:
        candidate = root / f"{ref}.md"
        if candidate.exists():
            return candidate
        nested = root / ref / "HANDOFF.md"
        if nested.exists():
            return nested
    home_claude = Path.home() / "CLAUDE.md"
    if ref in ("CLAUDE.md", "~/CLAUDE.md") and home_claude.exists():
        return home_claude
    return None


def run_pipeline(
    bank_path: Path | None = None,
    limit: int | None = None,
    extract_model: str = EXTRACT_MODEL,
    judge_model: str = JUDGE_MODEL,
    auto_build: bool = True,
) -> dict:
    """Run full validation pipeline.

    If bank_path is None and auto_build is True, builds bank first (idempotent).
    """
    if bank_path is None:
        bank_path = config.schema_bank_path()
    if not bank_path.exists():
        if not auto_build:
            print(f"Bank not found: {bank_path}", file=sys.stderr)
            return {"error": "no_bank"}
        print(f"[pipeline] no bank at {bank_path} — building first")
        build_bank()

    with bank_path.open() as f:
        bank = yaml.safe_load(f) or {}

    cases = bank.get("cases", [])
    if limit:
        cases = cases[:limit]
    print(f"[pipeline] running {len(cases)} cases (model={extract_model})")

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        case_id = case.get("id", f"case-{i}")
        print(f"[{i}/{len(cases)}] {case_id} ...", end=" ", flush=True)
        try:
            result = _run_one(case, extract_model, judge_model)
            print(f"{result.verdict} (extract {result.extract_time_s:.1f}s)")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"FAIL: {e}")
            result = CaseResult(
                case_id=case_id,
                trigger_phrase=case.get("trigger_phrase", ""),
                expected_rule=case.get("expected_rule", ""),
                anti_pattern=case.get("anti_pattern_fragment", ""),
                stable_since=str(case.get("stable_since")) if case.get("stable_since") else None,
                source_files_found=[],
                generated=f"(error: {e})",
                verdict="PARSE_FAIL",
                judge_raw="",
                extract_time_s=0.0,
                judge_time_s=0.0,
            )
        results.append(result)

    md_path, json_path, summary = write_run(results, extract_model, judge_model)
    print(f"\nReport: {md_path}")
    print(f"JSON:   {json_path}")
    print(
        f"Coverage: strict {summary['strict']:.1%} / loose {summary['loose']:.1%}"
        f" — gate (≥60%) {'PASS' if summary['strict'] >= 0.6 else 'BELOW'}"
    )
    return {"summary": summary, "report_md": str(md_path), "results_json": str(json_path)}


def _run_one(case: dict, extract_model: str, judge_model: str) -> CaseResult:
    content, found = load_source_content(case.get("source_episodes", []))
    stable_since = case.get("stable_since")
    stable_since_str = str(stable_since) if stable_since else None

    if not content:
        return CaseResult(
            case_id=case["id"],
            trigger_phrase=case.get("trigger_phrase", ""),
            expected_rule=case.get("expected_rule", ""),
            anti_pattern=case.get("anti_pattern_fragment", ""),
            stable_since=stable_since_str,
            source_files_found=[],
            generated="(no source content loaded)",
            verdict="NO_SOURCE",
            judge_raw="",
            extract_time_s=0.0,
            judge_time_s=0.0,
        )

    generated, extract_t = synthesize_rule(
        content,
        extract_model,
        trigger=case.get("trigger_phrase"),
    )
    verdict, judge_raw, judge_t = judge_rule(
        case.get("trigger_phrase", ""),
        case.get("expected_rule", ""),
        case.get("anti_pattern_fragment", ""),
        generated,
        judge_model,
    )
    return CaseResult(
        case_id=case["id"],
        trigger_phrase=case.get("trigger_phrase", ""),
        expected_rule=case.get("expected_rule", ""),
        anti_pattern=case.get("anti_pattern_fragment", ""),
        stable_since=stable_since_str,
        source_files_found=found,
        generated=generated,
        verdict=verdict,
        judge_raw=judge_raw,
        extract_time_s=extract_t,
        judge_time_s=judge_t,
    )
