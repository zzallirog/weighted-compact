"""Naive `/compact` simulator baseline — full-history summarization.

Black box:
  input  — source_pair_idx + pairs list + optional query; LLM model name.
  output — markdown summary string that replaces pair-selection entirely.
           The summary is used as the compacted context in recon-QA.
  entry  — `CompactSummarizer(model_id)` constructs once with a model
           handle; `.summarize_excluding(source_pair_idx, pairs, query)`
           returns the summary text.

Disclaimer: this is NOT Claude Code's exact `/compact` prompt — that
prompt is closed and varies by Claude Code version. This is a
*representative* simulation: hide the source pair, ask an LLM to
summarize the rest, keep content that would help answer questions about
the hidden pair. The intent matches `/compact`: one forward pass over
the conversation, no signal-aware selection.

Two tiers:
  `compact_qwen`   — qwen2.5:7b via local Ollama; default, free, fair
                     vs the gemma3:4b cheap judge.
  `compact_sonnet` — Claude Sonnet 4.6 via Anthropic API; opt-in tier,
                     uses ANTHROPIC_API_KEY env var, disclosed in README
                     §angle-privacy alongside the existing Sonnet judge
                     calibration.

Both tiers bypass `build_compacted_context`'s pair-selection logic via
the `is_compact_bypass = True` marker class attribute. `fidelity.run_eval`
dispatches accordingly.
"""
from __future__ import annotations

import logging
import os

from weighted_compact.recon_qa._constants import OLLAMA_URL, _requests

log = logging.getLogger(__name__)

QWEN_MODEL = 'qwen2.5:7b'
SONNET_MODEL = 'claude-sonnet-4-5'   # opt-in; upgrade as the maintainer rotates


def _build_prompt(source_pair, session_pairs) -> str:
    """Construct the summarization prompt with the source pair marked HIDDEN."""
    lines = [
        "Below is a conversation. One exchange is marked [HIDDEN] — its",
        "details have been removed. Summarize the conversation, keeping",
        "any content that would help answer questions about what was in",
        "the [HIDDEN] exchange. Output only the summary, no preamble.",
        "",
        "[CONVERSATION]",
    ]
    for p in session_pairs:
        if p['pair_idx'] == source_pair['pair_idx']:
            lines.append("PREMISE: [HIDDEN]\n\nCORRECTION: [HIDDEN]")
        else:
            lines.append(
                f"PREMISE: {p['premise_text']}\n\nCORRECTION: {p['correction_text']}",
            )
        lines.append("---")
    if lines[-1] == "---":
        lines.pop()
    lines.append("\n[SUMMARY]")
    return "\n".join(lines)


def _call_ollama(prompt: str, model: str, timeout: int = 120) -> str:
    """POST to Ollama, return summary text or error stub."""
    try:
        r = _requests().post(
            OLLAMA_URL,
            json={
                'model': model,
                'prompt': prompt,
                'stream': False,
                'options': {'temperature': 0.2, 'num_predict': 600},
            },
            timeout=timeout,
        )
        return r.json().get('response', '').strip()
    except Exception as exc:
        log.warning('compact_simulator ollama call failed: %s', exc)
        return f'<ollama_error: {exc}>'


def _call_anthropic(prompt: str, model: str, timeout: int = 120) -> str:
    """Call Anthropic API; require ANTHROPIC_API_KEY in env. Opt-in tier."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise RuntimeError(
            'ANTHROPIC_API_KEY not set; compact_sonnet is opt-in and '
            'requires user-provided credentials. See README §angle-privacy.',
        )
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "anthropic SDK not installed — install via "
            "`pip install anthropic` or `pip install -e .[baselines-cloud]`",
        ) from exc
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    msg = client.messages.create(
        model=model,
        max_tokens=800,
        messages=[{'role': 'user', 'content': prompt}],
    )
    parts = msg.content or []
    return ''.join(getattr(p, 'text', '') for p in parts).strip()


class CompactSummarizer:
    """Bypass pair-selection; replace context with a single LLM summary.

    is_compact_bypass marker tells fidelity.run_eval to call
    .summarize_excluding() directly instead of build_compacted_context.
    """

    is_compact_bypass = True

    def __init__(self, model: str, *, backend: str = 'ollama'):
        """
        model:   LLM identifier (e.g. 'qwen2.5:7b', 'claude-sonnet-4-5').
        backend: 'ollama' (local) or 'anthropic' (cloud, requires API key).
        """
        if backend not in ('ollama', 'anthropic'):
            raise ValueError(f"unknown backend: {backend!r}")
        self.model = model
        self.backend = backend

    def summarize_excluding(self, source_pair_idx, pairs, query=None) -> str:
        """Return summary text used as compacted context. query is unused
        (the prompt explicitly targets the hidden pair, not the question)."""
        source_pair = pairs[source_pair_idx]
        sess = source_pair['session_id']
        session_pairs = [p for p in pairs if p['session_id'] == sess]
        if not session_pairs:
            return ''
        prompt = _build_prompt(source_pair, session_pairs)
        if self.backend == 'ollama':
            return _call_ollama(prompt, model=self.model)
        return _call_anthropic(prompt, model=self.model)


def build_qwen() -> CompactSummarizer:
    """Default tier — local Ollama."""
    return CompactSummarizer(QWEN_MODEL, backend='ollama')


def build_sonnet() -> CompactSummarizer:
    """Opt-in tier — Anthropic API, requires ANTHROPIC_API_KEY."""
    return CompactSummarizer(SONNET_MODEL, backend='anthropic')


def build() -> dict:
    """Smoke-construct qwen tier (default). Local-only, no API calls made."""
    summarizer = build_qwen()
    return {
        'path': f'<in-memory CompactSummarizer model={summarizer.model}>',
        'n': 0,
        'min': 0.0,
        'max': 0.0,
        'mean': float('nan'),
    }


def main() -> None:
    """CLI smoke entry — `python -m weighted_compact.baselines.compact_simulator`."""
    summary = build()
    print(f"CompactSummarizer constructed: {summary['path']}")
    print('  (no api calls made; constructor smoke only)')


if __name__ == '__main__':
    main()
