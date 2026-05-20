#!/usr/bin/env python3
"""Auto-label unlabeled pairs in pairs.jsonl following the user's annotation pattern.

Phase 1 of weighted-compact project. Pure stdlib only.
"""

import json
import re
import sys

from weighted_compact import config

PAIRS_FILE = str(config.pairs_path())
LABELS_FILE = str(config.labels_path())

# ---- Helpers ----------------------------------------------------------------

# Patterns that indicate the correction_text starts with system/output leakage
SYSTEM_LEAKAGE_RE = re.compile(
    r'^(tar |/home/|/root/|/etc/|/usr/|```|---\n|'
    r'Phase \d|OK\.|Done\.|Started\.|Session|'
    r'Checking |Running |Monitoring |Starting |'
    r'\d{4}-\d{2}-\d{2}|\[\d+/\d+\])',
    re.IGNORECASE
)

# Wrap-up / scaffolding patterns
WRAPUP_RE = re.compile(
    r"(thanks|thank you|got it|understood|ok let's|okay let's|"
    r"alright|all right|go ahead|let's go|sounds good|"
    r"see you tomorrow|let's do it tomorrow)",
    re.IGNORECASE
)

# Phrasal contexts where a marker word is NOT a correction
# key = marker word (lower), value = list of context patterns that make it FP
PHRASAL_FP_PATTERNS = {
    'no': [
        re.compile(r'\bno result', re.IGNORECASE),
        re.compile(r'\bno point', re.IGNORECASE),
        re.compile(r'\bno idea', re.IGNORECASE),
        re.compile(r'\bno time', re.IGNORECASE),
        re.compile(r'\bno longer', re.IGNORECASE),
        re.compile(r'\bno data', re.IGNORECASE),
        re.compile(r'\bno difference', re.IGNORECASE),
        re.compile(r"\bthere'?s no\b", re.IGNORECASE),
    ],
    'wait': [
        re.compile(r'wait for', re.IGNORECASE),
        re.compile(r"can'?t wait", re.IGNORECASE),
        re.compile(r'wait until', re.IGNORECASE),
    ],
    'exactly': [
        re.compile(r'not exactly', re.IGNORECASE),
    ],
}


# Substantive multi-sentence corrections
def is_substantive(text):
    """True if correction has significant content: multiple sentences or >200 chars with facts."""
    if len(text) > 300:
        return True
    sentences = [s.strip() for s in re.split(r'[.!?]\s+', text) if s.strip()]
    if len(sentences) >= 3:
        return True
    # Has technical facts (paths, numbers, specific terms)
    if re.search(r'(\d{4,}|/[a-z]+/|:\d+|https?://|[a-z_]+\.[a-z]+)', text):
        return True
    return False

def correction_is_question(text):
    """True if correction is mainly a question (ends ?)."""
    stripped = text.strip()
    return stripped.endswith('?') and len(stripped) < 200

def marker_is_standalone(marker_match, correction_text):
    """Check if marker appears standalone (at start or after punct) vs embedded in phrase."""
    marker_lower = marker_match.lower()
    # Standalone: marker at very start of text (trimmed) or after newline or after punct+space
    patterns = [
        re.compile(r'^\s*' + re.escape(marker_lower), re.IGNORECASE),
        re.compile(r'[.!?\n]\s*' + re.escape(marker_lower) + r'\b', re.IGNORECASE),
    ]
    return any(p.search(correction_text) for p in patterns)

def check_phrasal_fp(marker_match, correction_text):
    """Return True if the marker is used in a phrasal non-correction context."""
    marker_lower = marker_match.lower()
    if marker_lower in PHRASAL_FP_PATTERNS:
        for pattern in PHRASAL_FP_PATTERNS[marker_lower]:
            if pattern.search(correction_text):
                return True
    return False


# ---- Main classifier --------------------------------------------------------

def classify(pair):
    """
    Returns (label, confidence, reason).
    label: 'keep' | 'maybe' | 'skip' | 'false_positive'
    confidence: 'high' | 'med' | 'low'
    """
    correction = pair.get('correction_text', '')
    marker = pair.get('marker_match', '')
    marker_type = pair.get('marker_type', '')
    tier_hint = pair.get('tier_hint', '')
    marker_lower = marker.lower().strip()

    # --- Skip: system leakage / wrap-up at start of correction
    if SYSTEM_LEAKAGE_RE.match(correction.strip()):
        return 'skip', 'high', 'system_leakage_start'

    if not correction.strip():
        return 'skip', 'high', 'empty_correction'

    # Very short correction (1-2 words) with wrap-up words
    if len(correction.strip()) < 30 and WRAPUP_RE.search(correction):
        return 'skip', 'high', 'short_wrapup'

    # --- Explicit tags are usually good signals
    if marker_type == 'explicit_tag':
        # (mark), (think), (mark - neutral)
        tag_lower = marker_lower.strip('()')
        if 'neutral' in tag_lower or 'think' in tag_lower:
            return 'maybe', 'med', 'explicit_tag_neutral'
        if 'mark' in tag_lower:
            # explicit annotation - if substantive correction -> keep, else maybe
            if is_substantive(correction):
                return 'keep', 'high', 'explicit_tag_substantive'
            return 'maybe', 'med', 'explicit_tag_short'
        return 'maybe', 'med', 'explicit_tag_other'

    # --- False positive check: phrasal context
    if check_phrasal_fp(marker, correction):
        # But override if correction is clearly substantive and standalone marker also present
        if is_substantive(correction) and marker_is_standalone(marker, correction):
            # Ambiguous
            return 'keep', 'low', 'phrasal_fp_overridden_by_substantive'
        return 'false_positive', 'high', 'phrasal_context'

    standalone = marker_is_standalone(marker, correction)

    # --- Negative / correction markers (no, wrong, not that, stop, ...)
    if marker_type == 'regex_neg':
        if is_substantive(correction):
            return 'keep', 'high', 'neg_substantive'
        if correction_is_question(correction):
            return 'maybe', 'med', 'neg_question'
        if len(correction.strip()) < 80:
            if WRAPUP_RE.search(correction):
                return 'skip', 'med', 'neg_short_wrapup'
            if standalone:
                return 'maybe', 'med', 'neg_standalone_short'
            return 'false_positive', 'med', 'neg_embedded_short'
        if standalone:
            return 'keep', 'med', 'neg_standalone_medium'
        return 'maybe', 'med', 'neg_embedded_medium'

    # --- Positive / validation markers (exactly, perfect, great, that's it, ...)
    if marker_type == 'regex_pos':
        stripped = correction.strip()
        # Pure acknowledgement without elaboration
        if len(stripped) < 60:
            if WRAPUP_RE.search(correction) or len(stripped) < 15:
                return 'skip', 'med', 'pos_pure_ack'
            return 'maybe', 'med', 'pos_short'
        if is_substantive(correction):
            return 'keep', 'high', 'pos_substantive'
        if correction_is_question(correction):
            return 'maybe', 'high', 'pos_question'
        return 'maybe', 'med', 'pos_medium'

    # --- Tier hint from extractor as tiebreaker
    if tier_hint == 'keep':
        if is_substantive(correction):
            return 'keep', 'med', 'tier_hint_keep_substantive'
        return 'maybe', 'low', 'tier_hint_keep_short'
    if tier_hint == 'skip':
        return 'skip', 'med', 'tier_hint_skip'

    # --- Fallback
    if is_substantive(correction):
        return 'keep', 'low', 'fallback_substantive'
    if correction_is_question(correction):
        return 'maybe', 'low', 'fallback_question'
    return 'maybe', 'low', 'fallback_generic'


# ---- Run --------------------------------------------------------------------

def main():
    # Load already-labeled indices
    labeled_idx = set()
    with open(LABELS_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                d = json.loads(line)
                labeled_idx.add(d['pair_idx'])

    print(f"Already labeled: {len(labeled_idx)}", file=sys.stderr)

    # Load pairs
    pairs = []
    with open(PAIRS_FILE) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                p = json.loads(line)
                p['pair_idx'] = i
                pairs.append(p)

    unlabeled = [p for p in pairs if p['pair_idx'] not in labeled_idx]
    print(f"Pairs to label: {len(unlabeled)}", file=sys.stderr)

    # Classify
    new_labels = []
    for p in unlabeled:
        label, confidence, reason = classify(p)
        rec = {
            'pair_idx': p['pair_idx'],
            'label': label,
            'marker_match': p.get('marker_match', ''),
            'marker_type': p.get('marker_type', ''),
            'session_id': p.get('session_id', ''),
            'labeled_by': 'claude_auto',
            'confidence': confidence,
            '_reason': reason,  # debug; strip for prod
        }
        new_labels.append(rec)

    # Append to labels file
    with open(LABELS_FILE, 'a') as f:
        for rec in new_labels:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # Summary
    dist = {}
    conf_low = 0
    for r in new_labels:
        dist[r['label']] = dist.get(r['label'], 0) + 1
        if r['confidence'] == 'low':
            conf_low += 1

    print("\n=== Auto-label summary ===")
    print(f"New labels added: {len(new_labels)}")
    print("Distribution:")
    for label in ('keep', 'maybe', 'skip', 'false_positive'):
        cnt = dist.get(label, 0)
        pct = cnt / len(new_labels) * 100 if new_labels else 0
        print(f"  {label}: {cnt} ({pct:.1f}%)")
    print(f"Low-confidence (needs review): {conf_low}")

    # Show breakdown by reason for inspection
    reasons = {}
    for r in new_labels:
        key = (r['label'], r['_reason'])
        reasons[key] = reasons.get(key, 0) + 1
    print("\nTop reason buckets:")
    for (lbl, rsn), cnt in sorted(reasons.items(), key=lambda x: -x[1])[:20]:
        print(f"  {lbl:15} {rsn:40} {cnt}")


if __name__ == '__main__':
    main()
