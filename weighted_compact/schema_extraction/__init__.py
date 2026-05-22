"""schema_extraction — third retrieval tier proof-of-concept.

Sub-package mirrors recon_qa layout: small independent black boxes.

    bank_builder.py — scan memory + HANDOFF roots, extract candidate cases via LLM
    synthesizer.py  — episode content → TRIGGER/RULE/ANTI rule
    judge.py        — generated vs expected → MATCH/NEAR/MISMATCH
    report.py       — JSON + markdown writers
    pipeline.py     — orchestrate full validation run

Entry point: `weighted-compact schema {build-bank,run,all}`.
Bank lives at $XDG_DATA_HOME/weighted-compact/schema-bank.yaml (gitignored).

See docs/schema-extraction.md for design notes and the HANDOFF/POSTULATES
documents that drove the v0 cut.
"""

from ._constants import EXTRACT_MODEL, JUDGE_MODEL, OLLAMA_URL
from .bank_builder import build_bank, discover_handoff_roots, discover_memory_roots
from .judge import judge_rule
from .pipeline import run_pipeline
from .report import CaseResult, write_run
from .synthesizer import synthesize_rule

__all__ = [
    "EXTRACT_MODEL",
    "JUDGE_MODEL",
    "OLLAMA_URL",
    "build_bank",
    "discover_handoff_roots",
    "discover_memory_roots",
    "judge_rule",
    "run_pipeline",
    "CaseResult",
    "write_run",
    "synthesize_rule",
]
