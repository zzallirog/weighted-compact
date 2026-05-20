#!/usr/bin/env python3
"""Phase 1: extract (correction, premise) pairs from session jsonl corpus.

Walks every subdir under each configured Claude Code source root. The
harness names project dirs from the working directory slug (e.g.
``-home-alice-projects-foo``), so the source roots contain one subdir per
project the user has run Claude Code in. We glob across all of them.
"""
import glob
import json
import os
import re
from collections import Counter

from weighted_compact import config
from weighted_compact.config import SKIP_PREFIXES

DIRS = [str(p) for p in config.claude_source_dirs()]
OUT = str(config.pairs_path())
MIN_FILE_SIZE = 5 * 1024

RE_NEG = re.compile(
    r"\b(no|not that|not what|not right|not quite|wrong|incorrect|"
    r"stop|wait|hold on|nope|don't|revert|undo|again)\b",
    re.IGNORECASE,
)
RE_POS = re.compile(
    r"\b(exactly|that's it|that's right|perfect|great|nailed it|nice|correct)\b",
    re.IGNORECASE,
)
RE_TAG = re.compile(
    r"\(([^)]*?(mark|think|neutral)[^)]*?)\)",
    re.IGNORECASE,
)


def extract_text(content):
    """Return clean text from message content (str or list of parts)."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                t = part.get("text", "").strip()
                if t:
                    texts.append(t)
        return "\n".join(texts).strip()
    return ""


def is_real_text(text, role):
    if not text:
        return False
    if any(text.startswith(p) for p in SKIP_PREFIXES):
        return False
    if role == "user":
        return 3 <= len(text) <= 4000
    if role == "assistant":
        return len(text) >= 20
    return False


def detect_marker(text):
    tag_m = RE_TAG.search(text)
    if tag_m:
        tag_inner = tag_m.group(1).lower()
        if any(w in tag_inner for w in ("neutral", "think")):
            return "explicit_tag", tag_m.group(0), "maybe"
        return "explicit_tag", tag_m.group(0), "keep"
    neg_m = RE_NEG.search(text)
    if neg_m:
        return "regex_neg", neg_m.group(0), "keep"
    pos_m = RE_POS.search(text)
    if pos_m:
        return "regex_pos", pos_m.group(0), "keep"
    return None, None, None


def process_file(path):
    events = []
    session_id = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = obj.get("type")
            if role not in ("user", "assistant"):
                continue
            msg = obj.get("message") or {}
            content = msg.get("content", "")
            text = extract_text(content)
            if not is_real_text(text, role):
                continue
            events.append({
                "role": role,
                "uuid": obj.get("uuid", ""),
                "text": text,
                "session_id": session_id,
            })
    return events


def build_pairs(events):
    pairs = []
    last_assistant = None
    for ev in events:
        if ev["role"] == "assistant":
            last_assistant = ev
        elif ev["role"] == "user" and last_assistant is not None:
            marker_type, marker_match, tier_hint = detect_marker(ev["text"])
            if marker_type:
                pairs.append({
                    "session_id": ev["session_id"],
                    "correction_uuid": ev["uuid"],
                    "correction_text": ev["text"],
                    "premise_uuid": last_assistant["uuid"],
                    "premise_text": last_assistant["text"],
                    "marker_type": marker_type,
                    "marker_match": marker_match,
                    "tier_hint": tier_hint,
                })
    return pairs


def main():
    files = []
    for d in DIRS:
        files.extend(glob.glob(os.path.join(d, "*.jsonl")))

    sessions_processed = 0
    all_pairs = []
    match_counter = Counter()

    for path in sorted(files):
        if os.path.getsize(path) < MIN_FILE_SIZE:
            continue
        events = process_file(path)
        if not events:
            continue
        sessions_processed += 1
        pairs = build_pairs(events)
        all_pairs.extend(pairs)
        for p in pairs:
            match_counter[p["marker_match"].lower()] += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for pair in all_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    by_type = Counter(p["marker_type"] for p in all_pairs)
    by_tier = Counter(p["tier_hint"] for p in all_pairs)

    print(f"Sessions processed : {sessions_processed}")
    print(f"Total pairs        : {len(all_pairs)}")
    print(f"By marker_type     : {dict(by_type)}")
    print(f"By tier_hint       : {dict(by_tier)}")
    print(f"Top-5 regex matches: {match_counter.most_common(5)}")
    print(f"Output             : {OUT}")


if __name__ == "__main__":
    main()
