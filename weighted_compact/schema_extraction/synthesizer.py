"""schema_extraction.synthesizer — extract one schema rule from episode content.

Single black-box: episode content → TRIGGER/RULE/ANTI structure.
Stateless, no I/O beyond Ollama call. Model swappable via $WC_SCHEMA_EXTRACT_MODEL.
"""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from ._constants import EXTRACT_MODEL, EXTRACT_PROMPT, OLLAMA_TIMEOUT_S, OLLAMA_URL


def ollama_generate(model: str, prompt: str, timeout: int = OLLAMA_TIMEOUT_S) -> tuple[str, float]:
    """Call local ollama /api/generate. Returns (text, elapsed_seconds)."""
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0}}
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body: dict[str, Any] = json.load(resp)
    return body.get("response", "").strip(), time.time() - t0


def synthesize_rule(context: str, model: str = EXTRACT_MODEL) -> tuple[str, float]:
    """Extract one schema rule (TRIGGER/RULE/ANTI) from episode content.

    Returns raw generated text + elapsed seconds. Caller parses or judges.
    'NO_RULE' is a valid response indicating no extractable rule in this content.
    """
    prompt = EXTRACT_PROMPT.format(context=context)
    return ollama_generate(model, prompt)
