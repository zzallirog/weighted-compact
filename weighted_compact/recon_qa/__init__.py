"""recon_qa — Reconstruction Q&A module (W3) split into black boxes.

Layout:
    judge.py     — semantic verdict + iter-drift telemetry (evaluator)
    generator.py — suggest_qa + ask_ollama (system-under-test)
    gate.py      — admission gate via difficulty buckets (EvoEnv-style)
    context.py   — compacted-context assembly + signal loaders
    fidelity.py  — run_eval + qa_set helpers

Backward compat: every public symbol from the pre-split monolith is re-exported
here, so `import weighted_compact.recon_qa as recon_qa; recon_qa.suggest_qa(...)`
keeps working. Tests that `monkeypatch.setattr` on package-level names also
keep working.

For new code, prefer explicit imports from submodules.
"""

from ._constants import (
    DENSITY,
    IMPORTANCE,
    JUDGE_MODEL,
    MODEL,
    OLLAMA_URL,
    PAIRS,
    RECON_SET,
    SUGGEST_MODEL,
    TOPIC_SEGMENTS,
)
from .context import (
    build_compacted_context,
    load_density,
    load_importance,
    load_pairs,
    load_topic_map,
)
from .fidelity import (
    load_qa_set,
    run_eval,
    sample_for_build,
    save_qa_entry,
    used_pair_idxs,
)
from .gate import classify_difficulty
from .generator import ask_ollama, suggest_qa
from .judge import (
    ITER_MODE_RANGES,
    iter_chain_metrics,
    llm_judge,
    score,
)
# Underscore-prefixed internals are reachable via the submodule path
# (e.g. weighted_compact.recon_qa.judge._embed_candidates) — not re-exported
# at package level to keep the public surface lean.

__all__ = [
    # constants
    'RECON_SET', 'PAIRS', 'DENSITY', 'IMPORTANCE', 'TOPIC_SEGMENTS',
    'OLLAMA_URL', 'MODEL', 'JUDGE_MODEL', 'SUGGEST_MODEL',
    'ITER_MODE_RANGES',
    # context
    'load_pairs', 'load_density', 'load_importance', 'load_topic_map',
    'build_compacted_context',
    # generator
    'ask_ollama', 'suggest_qa',
    # judge
    'iter_chain_metrics', 'score', 'llm_judge',
    # gate
    'classify_difficulty',
    # fidelity
    'load_qa_set', 'used_pair_idxs', 'sample_for_build', 'save_qa_entry',
    'run_eval',
]
