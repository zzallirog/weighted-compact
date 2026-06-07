"""schema_extraction.episode_boundary — heuristic episode arc detection (W2).

Episode = (start → struggle/correction → resolution) within a session.

This is the v0 lexical detector: no embeddings, no model calls. Walks a
Claude Code session jsonl, finds user-side correction markers, builds an
arc around each: backwalk for topic anchor, forward-walk for stable
resolution (next assistant turn not itself followed by another correction).

Future v1 will layer this on top of the existing `topic_segments.npz`
output (TextTiling-style embedding cohesion) for cleaner topic-anchor
detection; v0 ships without that dependency so the detector runs on raw
session files without needing the substrate to be bootstrapped first.

Design notes — alignment with shipped schema-extraction (HANDOFF P-d):
    correction_present : binary signal — fires if any user turn in the
                         arc matches a correction marker regex
    stability_age      : continuous — turns between resolution and next
                         correction within session (cap at window).
                         Reset to 0 if the resolution itself is corrected.

The boundary detector is the prerequisite step that unblocks proper
cluster signatures (P2 in HANDOFF). Without episode boundaries, the
current shipped pipeline falls back to "whole project_*.md file as
episode" which is what the proof run used and what hit R5 (multi-rule
cluster) empirically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .. import extract_pairs

CORRECTION_PATTERNS = [
    r"\b(нет|неверно|не\s+так|не\s+туда|не\s+это|неправильно)\b",
    r"\b(no|wrong|incorrect|nope|nah)\b",
    r"\b(ні|невірно)\b",
    r"\b(исправь|поправь|правильно|должно\s+быть|fix\s+(this|that|it))\b",
    r"\b(should\s+be|actually|instead)\b",
    r"\b(не\s+нужно|не\s+надо|не\s+делай|don'?t|stop)\b",
    r"\bотменя\w+\b",
    r"\bоткат\w+\b",
    r"\brevert\b",
]

CORRECTION_RE = re.compile("|".join(CORRECTION_PATTERNS), re.IGNORECASE)

RESOLUTION_FORWARD_WINDOW = 8
STABILITY_VERIFY_WINDOW = 3
SHORT_USER_CORRECTION_MAXLEN = 200


@dataclass
class EpisodeArc:
    session_id: str
    start_idx: int
    correction_idx: int
    end_idx: int
    correction_text: str
    resolution_text: str
    reason: str
    stability_turns: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_correction(text: str) -> bool:
    if not text:
        return False
    if len(text) > SHORT_USER_CORRECTION_MAXLEN:
        return False
    return bool(CORRECTION_RE.search(text))


def _find_anchor_idx(events: list[dict], correction_idx: int) -> int:
    """Backwalk: find the user turn that started the current sub-topic.

    v0 heuristic: the most recent user turn before the correction that is
    NOT itself a correction marker. Falls back to start of session.
    """
    for i in range(correction_idx - 1, -1, -1):
        ev = events[i]
        if ev["role"] != "user":
            continue
        if is_correction(ev["text"]):
            continue
        return i
    return 0


def _find_resolution_idx(events: list[dict], correction_idx: int) -> tuple[int | None, int]:
    """Forward-walk: assistant turn after correction not followed by another correction.

    Returns (resolution_idx, stability_turns) where stability_turns is how
    many turns the resolution held before the next correction or window-end.
    """
    n = len(events)
    last = min(n, correction_idx + RESOLUTION_FORWARD_WINDOW)
    for j in range(correction_idx + 1, last):
        ev = events[j]
        if ev["role"] != "assistant":
            continue
        stability = _count_stability(events, j)
        if stability >= 1:
            return j, stability
    return None, 0


def _count_stability(events: list[dict], assistant_idx: int) -> int:
    """How many turns the assistant's answer stood before the next correction."""
    n = len(events)
    end = min(n, assistant_idx + 1 + STABILITY_VERIFY_WINDOW)
    held = 0
    for k in range(assistant_idx + 1, end):
        ev = events[k]
        if ev["role"] == "user" and is_correction(ev["text"]):
            return held
        held += 1
    return held


def detect_episodes(events: list[dict]) -> list[EpisodeArc]:
    """Find episode arcs in a session event stream.

    Each correction-marker user turn potentially anchors one arc:
    (last topic-anchor user turn, correction user turn, stable assistant turn).
    Arcs without a found resolution are skipped (incomplete arcs).
    """
    if not events:
        return []

    session_id = events[0].get("session_id", "")
    arcs: list[EpisodeArc] = []

    for i, ev in enumerate(events):
        if ev["role"] != "user":
            continue
        if not is_correction(ev["text"]):
            continue
        anchor = _find_anchor_idx(events, i)
        resolution_idx, stability = _find_resolution_idx(events, i)
        if resolution_idx is None:
            continue
        arcs.append(
            EpisodeArc(
                session_id=session_id,
                start_idx=anchor,
                correction_idx=i,
                end_idx=resolution_idx,
                correction_text=ev["text"][:200],
                resolution_text=events[resolution_idx]["text"][:300],
                reason="correction-marker",
                stability_turns=stability,
            )
        )
    return arcs


def detect_in_session(session_path: Path) -> list[EpisodeArc]:
    """Load a session jsonl and detect episodes. Wraps extract_pairs.process_file."""
    events = extract_pairs.process_file(str(session_path))
    return detect_episodes(events)
