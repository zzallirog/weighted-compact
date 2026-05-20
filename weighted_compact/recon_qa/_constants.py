"""Internal constants — paths from `config` module + ollama URL/model defaults.

Black box: вход — env overrides (WEIGHTED_COMPACT_OLLAMA_URL, WEIGHTED_COMPACT_RECON_MODEL,
WEIGHTED_COMPACT_JUDGE_MODEL, WEIGHTED_COMPACT_SUGGEST_MODEL); выход — module-level
Path objects + URL/model strings. Как открыт — import _constants from any
sub-module; everything is plain attribute access. Not part of public API
(underscore prefix); use the re-exports in `__init__.py`.
"""
import os

from weighted_compact import config


RECON_SET = config.recon_qa_set_path()
PAIRS = config.pairs_path()
DENSITY = config.features_density_path()
IMPORTANCE = config.importance_path()
TOPIC_SEGMENTS = config.topic_segments_path()

OLLAMA_URL = os.environ.get(
    'WEIGHTED_COMPACT_OLLAMA_URL', 'http://localhost:11434/api/generate'
)
MODEL = os.environ.get('WEIGHTED_COMPACT_RECON_MODEL', 'qwen2.5:7b')
JUDGE_MODEL = os.environ.get('WEIGHTED_COMPACT_JUDGE_MODEL', 'gemma3:4b')
SUGGEST_MODEL = os.environ.get('WEIGHTED_COMPACT_SUGGEST_MODEL', MODEL)


def _requests():
    """Lazy-import requests so consumers of recon_qa don't pay for it at import."""
    import requests
    return requests
