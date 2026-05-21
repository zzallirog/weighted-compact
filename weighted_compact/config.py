"""Path resolution for the weighted-compact substrate.

Honors XDG base directories with one explicit override:

    $WEIGHTED_COMPACT_DATA  — substrate root (pairs.jsonl, labels.jsonl, *.npz)

Resolution order:
    1. $WEIGHTED_COMPACT_DATA if set
    2. $XDG_DATA_HOME/weighted-compact
    3. ~/.local/share/weighted-compact

The substrate is created lazily on first write. Nothing in this module
touches the filesystem; callers do.

Claude Code session source is independent of the substrate root and
defaults to the two locations the harness uses:

    ~/.claude/projects/
    ~/.claude-work/projects/

Override with $WEIGHTED_COMPACT_CLAUDE_SOURCES (colon-separated, like $PATH).
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "share"


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state"


def workdir() -> Path:
    """Return the substrate root for this user."""
    override = os.environ.get("WEIGHTED_COMPACT_DATA")
    if override:
        return Path(override).expanduser()
    return _xdg_data_home() / "weighted-compact"


def state_dir() -> Path:
    """Return the state dir (logs, bootstrap journal, ephemeral)."""
    return _xdg_state_home() / "weighted-compact"


def claude_source_dirs() -> list[Path]:
    """Return Claude Code session source directories to scan."""
    override = os.environ.get("WEIGHTED_COMPACT_CLAUDE_SOURCES")
    if override:
        return [Path(p).expanduser() for p in override.split(":") if p]
    home = Path.home()
    return [
        home / ".claude" / "projects",
        home / ".claude-work" / "projects",
    ]


# Common substrate file names. Code should import these constants rather
# than hardcoding filenames so renames stay centralized.
PAIRS_FILE = "pairs.jsonl"
LABELS_FILE = "labels.jsonl"
QUEUE_FILE = "queue.jsonl"
ANNOTATIONS_FILE = "inline_annotations.jsonl"
INLINE_MARKERS_FILE = "inline_markers_observed.jsonl"
RECON_QA_SET_FILE = "recon_qa_set.jsonl"
BOOTSTRAP_LOG = "bootstrap-log.jsonl"
DISAGREEMENT_QUEUE = "disagreement-queue.jsonl"
SUGGEST_AUDIT = "random_suggest_audit.jsonl"

FEATURES_FILE = "features.npz"
FEATURES_DENSITY_FILE = "features_density.npz"
FEATURES_MISSTEP_FILE = "features_misstep.npz"
FEATURES_SPANS_FILE = "features_spans.npz"
TOPIC_SEGMENTS_FILE = "topic_segments.npz"
IMPORTANCE_FILE = "importance.npz"
CLASSIFIER_FILE = "classifier.model"
BASELINE_RANDOM_FILE = "baseline_random.npz"
BASELINE_RECENCY_FILE = "baseline_recency.npz"


def pairs_path() -> Path: return workdir() / PAIRS_FILE
def labels_path() -> Path: return workdir() / LABELS_FILE
def queue_path() -> Path: return workdir() / QUEUE_FILE
def annotations_path() -> Path: return workdir() / ANNOTATIONS_FILE
def inline_markers_path() -> Path: return workdir() / INLINE_MARKERS_FILE
def recon_qa_set_path() -> Path: return workdir() / RECON_QA_SET_FILE
def bootstrap_log_path() -> Path: return state_dir() / BOOTSTRAP_LOG
def disagreement_queue_path() -> Path: return workdir() / DISAGREEMENT_QUEUE
def suggest_audit_path() -> Path: return workdir() / SUGGEST_AUDIT
def features_path() -> Path: return workdir() / FEATURES_FILE
def features_density_path() -> Path: return workdir() / FEATURES_DENSITY_FILE
def features_misstep_path() -> Path: return workdir() / FEATURES_MISSTEP_FILE
def features_spans_path() -> Path: return workdir() / FEATURES_SPANS_FILE
def topic_segments_path() -> Path: return workdir() / TOPIC_SEGMENTS_FILE
def importance_path() -> Path: return workdir() / IMPORTANCE_FILE
def classifier_path() -> Path: return workdir() / CLASSIFIER_FILE
def baseline_random_path() -> Path: return workdir() / BASELINE_RANDOM_FILE
def baseline_recency_path() -> Path: return workdir() / BASELINE_RECENCY_FILE


# Default labeler port. Override with $WEIGHTED_COMPACT_PORT.
def labeler_port() -> int:
    raw = os.environ.get("WEIGHTED_COMPACT_PORT")
    if raw:
        return int(raw)
    return 18890


# Keyboard shortcut → canonical tier name. Shared by tool.py (web labeler)
# and label_pairs.py (CLI fallback). Single source of truth.
LABEL_KEY_MAP: dict[str, str] = {
    "k": "keep",
    "m": "maybe",
    "s": "skip",
    "x": "false_positive",
}

ANNOTATION_TIERS: frozenset[str] = frozenset({"keep", "maybe", "skip", "think"})

# Claude Code internal tool-output markers. These are not conversational
# turns and have no labeling value; skipping them keeps the substrate
# signal/noise high and prevents the topic segmentor from mistaking tool
# floods for topic boundaries.
SKIP_PREFIXES: tuple[str, ...] = (
    "<command",
    "<local-command",
    "<bash-input",
    "<bash-stdout",
    "<bash-stderr",
    "<task-notification",
    "<system-reminder",
    "<user-prompt",
    "<image",
    "<attachment",
)
