"""schema_extraction.report — write per-case JSON + summary markdown.

Reports go under $XDG_DATA_HOME/weighted-compact/schema-runs/.
Filename pattern: report-YYYYMMDD-HHMMSS.md, results-YYYYMMDD-HHMMSS.json.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config


@dataclass
class CaseResult:
    case_id: str
    trigger_phrase: str
    expected_rule: str
    anti_pattern: str
    stable_since: str | None
    source_files_found: list[str]
    generated: str
    verdict: str
    judge_raw: str
    extract_time_s: float
    judge_time_s: float


def write_run(results: list[CaseResult], extract_model: str, judge_model: str) -> tuple[Path, Path, dict]:
    """Write JSON + markdown report. Return (md_path, json_path, totals_dict)."""
    out_dir = config.schema_runs_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")

    json_path = out_dir / f"results-{timestamp}.json"
    with json_path.open("w") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2, default=str)

    totals = {"MATCH": 0, "NEAR": 0, "MISMATCH": 0, "NO_SOURCE": 0, "PARSE_FAIL": 0}
    for r in results:
        totals[r.verdict] = totals.get(r.verdict, 0) + 1
    total = len(results) or 1
    strict = totals["MATCH"] / total
    loose = (totals["MATCH"] + totals["NEAR"]) / total

    md = [
        f"# Schema-extraction run — {timestamp}",
        "",
        f"**Models**: extract=`{extract_model}` judge=`{judge_model}`",
        f"**Cases**: {len(results)}",
        "",
        "## Coverage",
        "",
        f"- **MATCH** (strict): {totals['MATCH']}/{len(results)} = **{strict:.1%}**",
        f"- **MATCH+NEAR** (loose): {totals['MATCH'] + totals['NEAR']}/{len(results)} = **{loose:.1%}**",
        f"- MISMATCH: {totals['MISMATCH']}",
        f"- NO_SOURCE: {totals['NO_SOURCE']}",
        f"- PARSE_FAIL: {totals['PARSE_FAIL']}",
        "",
        "**P6 ship-gate**: ≥60% strict MATCH.",
        f"**Status**: {'PASS' if strict >= 0.6 else 'BELOW THRESHOLD'} ({strict:.1%})",
        "",
        "## Per-case detail",
        "",
    ]
    for r in results:
        md.extend(
            [
                f"### `{r.case_id}` — **{r.verdict}**",
                f"- trigger: {r.trigger_phrase}",
                f"- expected_rule: {r.expected_rule}",
                f"- stable_since: {r.stable_since or '(null)'}",
                f"- source: {', '.join(r.source_files_found) or '(none)'}",
                f"- timing: extract {r.extract_time_s:.1f}s / judge {r.judge_time_s:.1f}s",
                "",
                "**Generated**:",
                "```",
                r.generated,
                "```",
                "",
                f"**Judge**: `{r.judge_raw}`",
                "",
                "---",
                "",
            ]
        )
    md_path = out_dir / f"report-{timestamp}.md"
    md_path.write_text("\n".join(md))

    return md_path, json_path, {"totals": totals, "strict": strict, "loose": loose}
