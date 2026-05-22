"""schema_extraction.judge — semantic verdict on generated vs expected rule.

Returns MATCH / NEAR / MISMATCH. Same-model judge by default (cheap, AUC-proven
viable in upstream weighted-compact validation work — see project notes on
gemma3 κ=0.47 calibration).
"""

from __future__ import annotations

from ._constants import JUDGE_MODEL, JUDGE_PROMPT
from .synthesizer import ollama_generate

VERDICTS = ("MISMATCH", "NEAR", "MATCH")


def judge_rule(
    expected_trigger: str,
    expected_rule: str,
    expected_anti: str,
    generated: str,
    model: str = JUDGE_MODEL,
) -> tuple[str, str, float]:
    """Compare generated rule against expected. Returns (verdict, raw_text, elapsed).

    Verdict is one of MATCH / NEAR / MISMATCH / PARSE_FAIL.
    """
    prompt = JUDGE_PROMPT.format(
        expected_trigger=expected_trigger,
        expected_rule=expected_rule,
        expected_anti=expected_anti,
        generated=generated,
    )
    raw, elapsed = ollama_generate(model, prompt)
    verdict = _parse_verdict(raw)
    return verdict, raw, elapsed


def _parse_verdict(response: str) -> str:
    upper = response.upper()
    for token in VERDICTS:
        if token in upper:
            return token
    return "PARSE_FAIL"
