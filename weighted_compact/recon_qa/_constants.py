"""Internal constants — paths from `config` module + ollama URL/model defaults.

Black box: вход — env overrides (WEIGHTED_COMPACT_OLLAMA_URL, WEIGHTED_COMPACT_RECON_MODEL,
WEIGHTED_COMPACT_JUDGE_MODEL, WEIGHTED_COMPACT_SUGGEST_MODEL); выход — module-level
Path objects + URL/model strings. Как открыт — import _constants from any
sub-module; everything is plain attribute access. Not part of public API
(underscore prefix); use the re-exports in `__init__.py`.

Snapshot semantics: paths and URLs are captured at first import time.
If a test fixture or process changes env vars *after* this module loaded,
the cached values stay. Tests that need to override should either set
the env vars before importing `weighted_compact` or call
`_reload_paths()` defined below.
"""
import os

from weighted_compact import config


def _reload_paths() -> None:
    """Re-resolve all module-level path constants from current env state.

    Used by tests that monkeypatch `$WEIGHTED_COMPACT_DATA` mid-session and
    need the recon_qa sub-package to pick up the new substrate location.
    """
    global RECON_SET, PAIRS, DENSITY, IMPORTANCE, TOPIC_SEGMENTS
    RECON_SET = config.recon_qa_set_path()
    PAIRS = config.pairs_path()
    DENSITY = config.features_density_path()
    IMPORTANCE = config.importance_path()
    TOPIC_SEGMENTS = config.topic_segments_path()


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
