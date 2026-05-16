"""Phase 2 PRIMARY gate — content preservation evaluation.

Picks top-5 sessions by labeled-pair count. For each:
- Run classifier on session pairs → tier predictions per premise turn
- Mock reconstruction (verbatim/first-sentence/pointer by tier)
- Standard /compact mimic (heuristic compression to similar budget)
- Extract entities (names, numbers, quotes, idioms) from original
- Coverage ratio: weighted vs standard
- Gate: mean improvement ≥ 1.70×
"""
import json
import re
from collections import Counter, defaultdict

import numpy as np
import torch

from weighted_compact import config
from weighted_compact.model import WeightedCompactClassifier

WORKDIR = config.workdir()
FEATURES = config.features_path()
MODEL_PATH = config.classifier_path()
PAIRS = config.pairs_path()
REPORT_OUT = WORKDIR / 'eval-report.md'

SESSION_DIRS = config.claude_source_dirs()

META_RE = re.compile(r'^<(command|local-command|bash-input|bash-stdout|bash-stderr|task-notification|system-reminder|user-prompt|image|attachment)')

# Entity extractors (heuristic)
CAPITAL_NAME = re.compile(r'\b([А-ЯЁA-Z][а-яёa-zA-Z]{3,})\b')
NUMBER_DATE = re.compile(r'\b(\d{2,4}[-\./]?\d{0,2}[-\./]?\d{0,4}|\d{3,}[a-zA-Z]*|\d+[.,]\d+|\d+%)\b')
QUOTED = re.compile(r'[«"]([^»"]{4,80})[»"]')
TARGET_BUDGET_CHARS = 8000


def load_session_events(session_id):
    for d in SESSION_DIRS:
        p = d / f'{session_id}.jsonl'
        if not p.exists():
            continue
        events = []
        with open(p) as f:
            for line in f:
                d_ = json.loads(line)
                t = d_.get('type')
                if t not in ('user', 'assistant'):
                    continue
                msg = d_.get('message', {})
                content = msg.get('content', '')
                text = None
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = [x.get('text', '') for x in content if x.get('type') == 'text']
                    if parts:
                        text = '\n'.join(parts)
                if not text:
                    continue
                stripped = text.strip()
                if META_RE.match(stripped[:30]) or '<system-reminder>' in text[:80]:
                    continue
                if t == 'user' and (len(text) < 3 or len(text) > 4000):
                    continue
                if t == 'assistant' and len(text) < 20:
                    continue
                events.append({'uuid': d_.get('uuid', ''), 't': t, 'text': text})
        return events
    return None


def extract_entities(text):
    """Return set of entity strings (lowercased for matching)."""
    ents = set()
    for m in CAPITAL_NAME.findall(text):
        if len(m) >= 4:
            ents.add(m.lower())
    for m in NUMBER_DATE.findall(text):
        if len(m) >= 2:
            ents.add(m.lower())
    for m in QUOTED.findall(text):
        ents.add(m.strip().lower()[:60])
    return ents


def first_sentence(text, max_chars=200):
    text = text.replace('\n', ' ').strip()
    parts = re.split(r'(?<=[.!?])\s+', text)
    if parts:
        return parts[0][:max_chars]
    return text[:max_chars]


def build_weighted_render(events, premise_tiers, budget_chars=TARGET_BUDGET_CHARS):
    """premise_tiers: dict {uuid: tier 0/1/2}"""
    out = []
    used = 0
    for ev in events:
        tier = premise_tiers.get(ev['uuid'], 1)
        if tier == 2:
            chunk = f'[KEEP {ev["t"]}] {ev["text"]}'
        elif tier == 1:
            chunk = f'[MAYBE {ev["t"]}] {first_sentence(ev["text"])}'
        else:
            chunk = f'[PTR {ev["t"]}#{ev["uuid"][:8]}]'
        if used + len(chunk) > budget_chars:
            break
        out.append(chunk)
        used += len(chunk)
    return '\n'.join(out)


def build_standard_mimic(events, budget_chars=TARGET_BUDGET_CHARS):
    """Mimic /compact: take first sentence of each turn, fit budget."""
    out = []
    used = 0
    for ev in events:
        chunk = f'[{ev["t"]}] {first_sentence(ev["text"], max_chars=120)}'
        if used + len(chunk) > budget_chars:
            break
        out.append(chunk)
        used += len(chunk)
    return '\n'.join(out)


def evaluate_session(session_id, pair_data, model, device):
    events = load_session_events(session_id)
    if not events:
        return None

    session_pairs = [(idx, p) for idx, p in pair_data if p['session_id'] == session_id]
    if not session_pairs:
        return None

    feat = np.load(FEATURES)
    pair_indices = feat['pair_indices']

    premise_tiers = {}
    for idx, p in session_pairs:
        npz_idx = np.where(pair_indices == idx)[0]
        if len(npz_idx) == 0:
            continue
        npz_idx = npz_idx[0]
        window = torch.from_numpy(feat['windows'][npz_idx:npz_idx+1]).float().to(device)
        with torch.no_grad():
            pred = model(window).argmax(-1).item()
        premise_tiers[p['premise_uuid']] = max(premise_tiers.get(p['premise_uuid'], 0), pred)
        premise_tiers[p['correction_uuid']] = max(premise_tiers.get(p['correction_uuid'], 0), pred)

    # entity ground truth: top-20 turns by length (proxy for important)
    top20 = sorted(events, key=lambda e: -len(e['text']))[:20]
    entities_orig = set()
    for ev in top20:
        entities_orig |= extract_entities(ev['text'])

    if not entities_orig:
        return None

    weighted = build_weighted_render(events, premise_tiers)
    standard = build_standard_mimic(events)

    weighted_lower = weighted.lower()
    standard_lower = standard.lower()

    preserved_w = sum(1 for e in entities_orig if e in weighted_lower)
    preserved_s = sum(1 for e in entities_orig if e in standard_lower)

    cov_w = preserved_w / len(entities_orig)
    cov_s = preserved_s / len(entities_orig)
    improvement = cov_w / max(cov_s, 0.001)

    return {
        'session_id': session_id,
        'n_events': len(events),
        'n_labeled_pairs': len(session_pairs),
        'n_entities': len(entities_orig),
        'preserved_weighted': preserved_w,
        'preserved_standard': preserved_s,
        'cov_weighted': cov_w,
        'cov_standard': cov_s,
        'improvement': improvement,
        'weighted_chars': len(weighted),
        'standard_chars': len(standard),
        'top_tiers': dict(Counter(premise_tiers.values())),
    }


def main():
    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    # load model
    model = WeightedCompactClassifier().to(device)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=device, weights_only=True))
    model.eval()

    # load pairs
    pair_data = []
    with open(PAIRS) as f:
        for i, line in enumerate(f):
            pair_data.append((i, json.loads(line)))

    # group by session, pick top 5 with most pairs
    by_session = defaultdict(int)
    for _, p in pair_data:
        by_session[p['session_id']] += 1
    top_sessions = sorted(by_session.items(), key=lambda x: -x[1])[:5]

    print('Top-5 sessions by labeled pair count:')
    for sid, n in top_sessions:
        print(f'  {sid[:8]}  {n} pairs')

    results = []
    for sid, _ in top_sessions:
        r = evaluate_session(sid, pair_data, model, device)
        if r:
            results.append(r)

    if not results:
        print('No sessions could be evaluated.')
        return

    mean_imp = np.mean([r['improvement'] for r in results])
    gate_pass = mean_imp >= 1.70

    lines = [
        '# Phase 2 Content Preservation Evaluation',
        '',
        '**Дата:** 2026-05-15',
        f'**Sessions evaluated:** {len(results)}',
        f'**Mean improvement:** {mean_imp:.3f}× (gate ≥ 1.70×)',
        f'**Gate:** {"✓ PASS" if gate_pass else "✗ FAIL"}',
        '',
        '## Per-session breakdown',
        '',
        '| Session | Events | Pairs | Entities | Weighted Cov | Standard Cov | Improvement |',
        '|---|---|---|---|---|---|---|',
    ]
    for r in results:
        lines.append(
            f'| {r["session_id"][:8]} | {r["n_events"]} | {r["n_labeled_pairs"]} | '
            f'{r["n_entities"]} | {r["cov_weighted"]:.2f} | {r["cov_standard"]:.2f} | '
            f'**{r["improvement"]:.2f}×** |'
        )

    lines.extend([
        '',
        '## Tier distribution (per session)',
        '',
    ])
    for r in results:
        tiers_str = ', '.join(f't{k}={v}' for k, v in sorted(r['top_tiers'].items()))
        lines.append(f'- {r["session_id"][:8]}: {tiers_str}')

    lines.extend([
        '',
        '## Token budget',
        '',
        '| Session | Weighted chars | Standard chars |',
        '|---|---|---|',
    ])
    for r in results:
        lines.append(f'| {r["session_id"][:8]} | {r["weighted_chars"]:,} | {r["standard_chars"]:,} |')

    lines.extend([
        '',
        '## Notes',
        '',
        '- Mock reconstruction (Phase 3 render не готов). Verbatim для tier=2, first-sentence для tier=1, pointer для tier=0.',
        '- Standard mimic — heuristic: first sentence каждого turn до budget. Реальный `/compact` LLM-output может быть лучше; этот mimic — conservative baseline.',
        '- Entities = top-20 turns by length → capitalized names (≥4 chars), numbers/dates, quoted strings.',
        '- Если PASS на mock → primary gate проходит. Phase 3 render должен только улучшить.',
        '- Если FAIL — смотри tier distribution: возможно classifier даёт слишком много tier=0 для важных turn\'ов; iterate Phase 2.',
    ])

    REPORT_OUT.write_text('\n'.join(lines))
    print(f'\nReport: {REPORT_OUT}')
    print(f'Mean improvement: {mean_imp:.3f}× | GATE: {"PASS" if gate_pass else "FAIL"}')


if __name__ == '__main__':
    main()
