#!/usr/bin/env python3
"""Auto-label unlabeled pairs in pairs.jsonl following user's annotation pattern.

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
    r'^(Мониторю|Запускаю|tar |/home/|/root/|/etc/|/usr/|```|---\n|'
    r'Phase \d|OK\.|Готово\.|Запустил\.|Session|Сессия\s\d|'
    r'ОК\. |Ок\. |ok\. |Checking |Running |Done\.|'
    r'\d{4}-\d{2}-\d{2}|\[\d+/\d+\])',
    re.IGNORECASE
)

# Long emotional/philosophical reflections with no directives
EMOTIONAL_REFLECTION_RE = re.compile(
    r'(это очень|это просто|как будто|я понимаю|мне кажется|не знаю даже|'
    r'странно но|как-то так|вот такой я|это сложно|очень сложно|как обычно)',
    re.IGNORECASE
)

# Wrap-up / scaffolding patterns
WRAPUP_RE = re.compile(
    r'(локал гитеа|ингест фоном|окей, спасибо|ок спасибо|хорошо, понял|'
    r'понял, спасибо|давай завтра|до завтра|окей давай|хорошо давай|'
    r'поня[лт]|go ahead|let\'s go|ладно|ну ладно)',
    re.IGNORECASE
)

# Phrasal contexts where marker word is NOT a correction
# key = marker word (lower), value = list of context patterns that make it FP
PHRASAL_FP_PATTERNS = {
    'нет': [
        re.compile(r'а нет ли', re.IGNORECASE),
        re.compile(r'нет результата', re.IGNORECASE),
        re.compile(r'нет слов', re.IGNORECASE),
        re.compile(r'или нет[,\?]', re.IGNORECASE),
        re.compile(r'нет ни', re.IGNORECASE),
        re.compile(r'как нет', re.IGNORECASE),
        re.compile(r'пока нет', re.IGNORECASE),
        re.compile(r'(там|здесь|тут) нет', re.IGNORECASE),
        re.compile(r'нет смысла', re.IGNORECASE),
        re.compile(r'нет времени', re.IGNORECASE),
        re.compile(r'нет данных', re.IGNORECASE),
        re.compile(r'нет информации', re.IGNORECASE),
        re.compile(r'нет ничего', re.IGNORECASE),
        re.compile(r'нет разницы', re.IGNORECASE),
        re.compile(r'\bнет\b.*\bнет\b', re.IGNORECASE),  # repeated "нет" in longer context
    ],
    'вот': [
        re.compile(r'вот так', re.IGNORECASE),
        re.compile(r'вот этот', re.IGNORECASE),
        re.compile(r'вот общение', re.IGNORECASE),
        re.compile(r'вот такой', re.IGNORECASE),
        re.compile(r'вот такая', re.IGNORECASE),
        re.compile(r'вот и всё', re.IGNORECASE),
        re.compile(r'вот и все', re.IGNORECASE),
        re.compile(r'вот что', re.IGNORECASE),
        re.compile(r'вот где', re.IGNORECASE),
        re.compile(r'вот почему', re.IGNORECASE),
        re.compile(r'вот когда', re.IGNORECASE),
        re.compile(r'вот как', re.IGNORECASE),
    ],
    'точно': [
        re.compile(r'не точно', re.IGNORECASE),
        re.compile(r'точно не', re.IGNORECASE),
        re.compile(r'точно так', re.IGNORECASE),
        re.compile(r'это точно', re.IGNORECASE),
    ],
    'именно': [
        re.compile(r'не именно', re.IGNORECASE),
        re.compile(r'да, именно', re.IGNORECASE),
        re.compile(r'именно так', re.IGNORECASE),
        re.compile(r'именно поэтому', re.IGNORECASE),
        re.compile(r'именно то', re.IGNORECASE),
        re.compile(r'именно это', re.IGNORECASE),
    ],
}

# Markers that are almost always validating/directive when standalone
STRONG_CORRECTION_MARKERS = {'не так', 'не то', 'не нужно', 'не надо', 'стоп', 'погоди',
                               'опять', 'нет', 'нет,', 'нет.', 'нет!'}
STRONG_POSITIVE_MARKERS = {'точно', 'именно', 'супер', 'отлично', 'идеально', 'да это'}

# Deferred / soft markers
SOFT_MARKERS = {'погоди', 'подожди', 'стоп', 'стоп,'}

# Short validation questions -> maybe
VALIDATION_QUESTION_RE = re.compile(
    r'^.{0,120}\?$',  # short message ending with question
    re.DOTALL
)

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
    text_lower = correction_text.lower()
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
    premise = pair.get('premise_text', '')
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
        # (маркер), (подумать) etc.
        tag_lower = marker_lower.strip('()')
        if tag_lower in ('маркер', 'mark'):
            # explicit annotation - if substantive correction -> keep, else maybe
            if is_substantive(correction):
                return 'keep', 'high', 'explicit_tag_substantive'
            return 'maybe', 'med', 'explicit_tag_short'
        if tag_lower in ('подумать', 'нейтральный'):
            return 'maybe', 'med', 'explicit_tag_neutral'
        return 'maybe', 'med', 'explicit_tag_other'

    # --- False positive check: phrasal context
    if check_phrasal_fp(marker, correction):
        # But override if correction is clearly substantive and standalone marker also present
        if is_substantive(correction) and marker_is_standalone(marker, correction):
            # Ambiguous
            return 'keep', 'low', 'phrasal_fp_overridden_by_substantive'
        return 'false_positive', 'high', 'phrasal_context'

    # --- Marker standalone check
    standalone = marker_is_standalone(marker, correction)

    # --- "нет" marker
    if marker_lower in ('нет', 'нет,', 'нет.', 'нет!'):
        if not standalone:
            # нет embedded in longer text
            if is_substantive(correction):
                return 'keep', 'low', 'нет_embedded_substantive'
            return 'false_positive', 'med', 'нет_embedded_short'
        # standalone нет
        if is_substantive(correction):
            return 'keep', 'high', 'нет_standalone_substantive'
        if correction_is_question(correction):
            return 'maybe', 'med', 'нет_standalone_question'
        if len(correction.strip()) < 80:
            # Very short correction after standalone нет
            if WRAPUP_RE.search(correction):
                return 'skip', 'med', 'нет_standalone_wrapup'
            return 'maybe', 'med', 'нет_standalone_short'
        return 'keep', 'med', 'нет_standalone_medium'

    # --- "вот" marker
    if marker_lower in ('вот',):
        if not standalone:
            return 'false_positive', 'high', 'вот_not_standalone'
        if is_substantive(correction):
            return 'keep', 'high', 'вот_standalone_substantive'
        if correction_is_question(correction):
            return 'maybe', 'med', 'вот_standalone_question'
        return 'keep', 'med', 'вот_standalone_medium'

    # --- "опять" marker - usually bug report or repeated issue
    if marker_lower == 'опять':
        if is_substantive(correction):
            return 'keep', 'high', 'опять_substantive'
        if standalone:
            return 'keep', 'med', 'опять_standalone'
        return 'maybe', 'med', 'опять_embedded'

    # --- "точно" marker
    if marker_lower in ('точно', 'Точно'):
        if not standalone:
            if is_substantive(correction):
                return 'keep', 'med', 'точно_embedded_substantive'
            return 'false_positive', 'med', 'точно_embedded_short'
        if is_substantive(correction):
            return 'keep', 'high', 'точно_standalone_substantive'
        if correction_is_question(correction):
            return 'maybe', 'high', 'точно_question'
        return 'keep', 'med', 'точно_standalone_medium'

    # --- "именно" marker
    if marker_lower in ('именно', 'Именно'):
        if check_phrasal_fp('именно', correction):
            return 'false_positive', 'med', 'именно_phrasal'
        if is_substantive(correction):
            return 'keep', 'high', 'именно_substantive'
        if standalone:
            return 'keep', 'med', 'именно_standalone'
        return 'maybe', 'med', 'именно_embedded'

    # --- "супер" marker
    if marker_lower == 'супер':
        if len(correction.strip()) < 60:
            # Pure "супер" confirm without elaboration
            if WRAPUP_RE.search(correction) or correction.strip().lower() in ('супер', 'супер!', 'супер.'):
                return 'skip', 'med', 'супер_pure_ack'
            return 'maybe', 'med', 'супер_short'
        if is_substantive(correction):
            return 'keep', 'high', 'супер_substantive'
        if correction_is_question(correction):
            return 'maybe', 'high', 'супер_question'
        return 'maybe', 'med', 'супер_medium'

    # --- "погоди" / "стоп" markers
    if marker_lower in ('погоди', 'подожди', 'стоп', 'стоп,', 'Стоп'):
        if is_substantive(correction):
            return 'keep', 'high', 'стоп_substantive'
        if correction_is_question(correction):
            return 'maybe', 'high', 'стоп_question'
        return 'maybe', 'med', 'стоп_short'

    # --- "не так", "не то", "не нужно", "не надо", "не надо"
    if marker_lower in ('не так', 'не то', 'не нужно', 'не надо', 'не надо,'):
        if is_substantive(correction):
            return 'keep', 'high', 'neg_directive_substantive'
        if standalone:
            return 'keep', 'med', 'neg_directive_standalone'
        return 'maybe', 'med', 'neg_directive_short'

    # --- "отлично", "идеально", "да это"
    if marker_lower in ('отлично', 'идеально', 'да это'):
        if len(correction.strip()) < 60:
            return 'maybe', 'med', 'pos_confirm_short'
        if is_substantive(correction):
            return 'keep', 'high', 'pos_confirm_substantive'
        return 'maybe', 'med', 'pos_confirm_medium'

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

    print(f"\n=== Auto-label summary ===")
    print(f"New labels added: {len(new_labels)}")
    print(f"Distribution:")
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
    print(f"\nTop reason buckets:")
    for (lbl, rsn), cnt in sorted(reasons.items(), key=lambda x: -x[1])[:20]:
        print(f"  {lbl:15} {rsn:40} {cnt}")


if __name__ == '__main__':
    main()
