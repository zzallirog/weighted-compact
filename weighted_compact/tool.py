#!/usr/bin/env python3
"""weighted-compact CAPTCHA labeler — local web tool.

Run via the CLI:
    weighted-compact serve

Or directly:
    python -m weighted_compact.tool

Then open http://localhost:18890/.

Design (per docs/invariants.md):
- Equal-weight assistant/user blocks (symmetric typography)
- Anti-drift sidebar: five cosine-nearest prior labeled pairs
- Keyboard shortcuts: k / m / s / x → KEEP / MAYBE / SKIP / FALSE-POS
- Queue-driven, resumable via labels.jsonl
- Stability principle: shows your own past decisions on similar pairs

Note: the embedded HTML UI is currently bilingual (Russian first, mixed
with English). A full i18n pass is filed as a contributor task; see
CONTRIBUTING.md for the PR template.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from weighted_compact import config, recon_qa
from weighted_compact.config import ANNOTATION_TIERS, LABEL_KEY_MAP

WORKDIR = config.workdir()
PAIRS = config.pairs_path()
LABELS = config.labels_path()
QUEUE = config.queue_path()
FEATURES = config.features_path()
ANNOTATIONS = config.annotations_path()

PORT = config.labeler_port()
LABEL_NAMES = LABEL_KEY_MAP
ANNOTATION_MARKERS = set(ANNOTATION_TIERS)

# Inline-marker → tier mapping. The labeler accepts canonical tier names
# directly via API; this map is used when bootstrapping queue entries from
# inline markers a user typed during a live Claude Code session.
# Add other-language patterns in extract_pairs.MARKER_PATTERNS and mirror
# canonical tiers here.
INLINE_SYNTAX_MAP = {
    '(маркер)': 'keep',
    '(маркер - нейтральный)': 'maybe',
    '(mark)': 'maybe',
    '(подумать)': 'think',
    '(пропос)': 'think',
}

STATE: dict = {
    'pairs': [],
    'labels': {},
    'queue': [],
    'features': None,
    'annotations': [],
    'annotations_by_pair': {},
    'next_annotation_id': 1,
}


log = logging.getLogger("weighted_compact.tool")


@asynccontextmanager
async def lifespan(app: FastAPI):
    reload_state()
    qrem = sum(1 for q in STATE['queue'] if not already_tool_labeled(q['pair_idx']))
    log.info(
        "weighted-compact labeler listening on http://localhost:%d "
        "(labels=%d, queue_remaining=%d, corpus=%d)",
        PORT, len(STATE['labels']), qrem, len(STATE['pairs']),
    )
    yield


app = FastAPI(title='weighted-compact labeler', lifespan=lifespan)


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def reload_state() -> None:
    STATE['pairs'] = load_jsonl(PAIRS)
    labels_list = load_jsonl(LABELS)
    STATE['labels'] = {l['pair_idx']: l for l in labels_list}
    STATE['queue'] = load_jsonl(QUEUE)

    # Annotations: filter out soft-deleted, group by pair_idx.
    # The POST /api/annotation handler writes records with a `char_range:
    # [start, end]` array; hand-written or migrated fixtures sometimes carry
    # `char_start` / `char_end` instead. The frontend only reads `char_range`,
    # so normalize on load — without this the labeler crashes silently
    # with "Cannot read properties of undefined (reading '0')".
    raw = load_jsonl(ANNOTATIONS)
    STATE['annotations'] = raw
    grouped: dict[int, list[dict]] = {}
    max_id = 0
    for ann in raw:
        max_id = max(max_id, int(ann.get('id', 0)))
        if ann.get('deleted'):
            continue
        if 'char_range' not in ann and 'char_start' in ann and 'char_end' in ann:
            ann['char_range'] = [int(ann['char_start']), int(ann['char_end'])]
        grouped.setdefault(int(ann['pair_idx']), []).append(ann)
    STATE['annotations_by_pair'] = grouped
    STATE['next_annotation_id'] = max_id + 1

    if FEATURES.exists():
        f = np.load(FEATURES, allow_pickle=True)
        windows = f['windows']  # (N, 3, 384) — [prev_assistant, premise, correction]
        pair_indices = f['pair_indices']

        # Anti-drift signal: correction embedding ONLY — это user's turn vector.
        # NOT mean-of-window (which mixes assistant + user). Transparency
        # surfaced in UI as "sim by: correction embedding".
        correction = windows[:, 2, :]
        correction = correction / (np.linalg.norm(correction, axis=1, keepdims=True) + 1e-9)

        STATE['features'] = {
            'vectors': correction,
            'vector_basis': 'correction embedding (e5 multilingual-small, 384d, normalized)',
            'pair_indices': pair_indices,
            'row_by_idx': {int(pidx): row for row, pidx in enumerate(pair_indices)},
        }
        STATE['clusters'] = compute_clusters(correction, pair_indices)
    else:
        STATE['features'] = None
        STATE['clusters'] = None


def compute_clusters(vectors: np.ndarray, pair_indices: np.ndarray, k: int = 10) -> dict:
    """KMeans clustering for «correlation classifier» browse mode.
    Pairs in same cluster = semantically nearest correction turns → labeling
    them consecutively surfaces inconsistencies fast."""
    try:
        from sklearn.cluster import KMeans
    except ImportError:
        return None
    n = len(vectors)
    if n < k * 2:
        k = max(2, n // 4)
    km = KMeans(n_clusters=k, n_init=5, random_state=42)
    labels = km.fit_predict(vectors)
    cluster_by_idx = {int(pair_indices[i]): int(labels[i]) for i in range(n)}
    members: dict = {}
    for pidx, c in cluster_by_idx.items():
        members.setdefault(c, []).append(pidx)
    sizes = {c: len(m) for c, m in members.items()}
    return {
        'cluster_by_idx': cluster_by_idx,
        'members': members,
        'sizes': sizes,
        'n_clusters': k,
    }


def already_tool_labeled(pid: int) -> bool:
    """Tool re-label беспрепятственно перезаписывает bootstrap label.
    Queue entry consumed только когда tool сам поставил label."""
    lab = STATE['labels'].get(pid)
    return bool(lab and lab.get('labeled_via') == 'tool')


QUEUE_SOURCES = {
    'disagreement': 'bootstrap_disagreement',
    'low_conf': 'low_confidence',
    'audit': 'audit_anchor',
}


def pick_next(mode: str = 'all', current_cluster: int | None = None) -> tuple[int, str] | tuple[None, None]:
    if mode == 'unknown':
        # Truly never-labeled pairs (no bootstrap, no tool)
        for i in range(len(STATE['pairs'])):
            if i not in STATE['labels']:
                return i, 'unknown'
        return None, None

    if mode == 'cluster':
        return pick_next_cluster(current_cluster)

    # Filter queue by source if specified
    target_source = QUEUE_SOURCES.get(mode)
    for entry in STATE['queue']:
        pid = entry['pair_idx']
        src = entry.get('source', 'queue')
        if target_source and src != target_source:
            continue
        if 0 <= pid < len(STATE['pairs']) and not already_tool_labeled(pid):
            return pid, src

    if mode == 'all':
        # Fallback to unknown if queue exhausted
        for i in range(len(STATE['pairs'])):
            if not already_tool_labeled(i) and i not in STATE['labels']:
                return i, 'fallback_random'
    return None, None


def pick_next_cluster(current_cluster: int | None) -> tuple[int, str] | tuple[None, None]:
    """Browse pairs by semantic cluster. Picks cluster with most remaining work,
    or continues current cluster if specified. Within cluster — order by pair_idx."""
    clusters = STATE.get('clusters')
    if not clusters:
        return None, None

    remaining_by_cluster: dict[int, list[int]] = {}
    for c, members in clusters['members'].items():
        rem = [p for p in members if not already_tool_labeled(p)]
        if rem:
            remaining_by_cluster[c] = sorted(rem)

    if not remaining_by_cluster:
        return None, None

    if current_cluster is not None and current_cluster in remaining_by_cluster:
        c = current_cluster
    else:
        # Pick cluster with most remaining work — surface most-correlated batch
        c = max(remaining_by_cluster, key=lambda k: len(remaining_by_cluster[k]))

    pid = remaining_by_cluster[c][0]
    return pid, f'cluster_{c}'


def get_anti_drift(pair_idx: int, k: int = 5) -> list[dict]:
    feats = STATE['features']
    if feats is None or pair_idx not in feats['row_by_idx']:
        return []
    row = feats['row_by_idx'][pair_idx]
    target = feats['vectors'][row]

    labeled_pids = [pid for pid in STATE['labels'] if pid != pair_idx and pid in feats['row_by_idx']]
    if not labeled_pids:
        return []

    rows = np.array([feats['row_by_idx'][pid] for pid in labeled_pids])
    sims = feats['vectors'][rows] @ target
    top = np.argsort(-sims)[:k]

    out = []
    for ti in top:
        pid = int(labeled_pids[ti])
        lab = STATE['labels'][pid]
        out.append({
            'sim': float(sims[ti]),
            'pair_idx': pid,
            'label': lab['label'],
            'marker': lab.get('marker_match', ''),
            'session': (lab.get('session_id') or '')[:8],
            'labeled_via': lab.get('labeled_via', 'bootstrap'),
        })
    return out


class LabelPayload(BaseModel):
    pair_idx: int
    label: str
    source: str = 'tool'


class AnnotationPayload(BaseModel):
    pair_idx: int
    side: str             # 'premise' | 'correction'
    char_start: int       # 0-indexed char within side text (Python str semantics)
    char_end: int         # exclusive
    marker: str           # 'keep' | 'maybe' | 'skip' | 'think'
    note: str = ''


@app.get('/api/next')
def api_next(
    mode: str = Query('all'),
    cluster: int | None = Query(None),
) -> JSONResponse:
    pid, source = pick_next(mode, current_cluster=cluster)
    if pid is None:
        return JSONResponse({'done': True, 'mode': mode, 'labeled': len(STATE['labels'])})

    pair = STATE['pairs'][pid]
    existing = STATE['labels'].get(pid)
    existing_brief = None
    if existing:
        existing_brief = {
            'label': existing.get('label'),
            'via': existing.get('labeled_via', 'bootstrap'),
        }

    clusters = STATE.get('clusters')
    cluster_id = clusters['cluster_by_idx'].get(pid) if clusters else None
    cluster_size = clusters['sizes'].get(cluster_id) if (clusters and cluster_id is not None) else None

    feats = STATE.get('features') or {}

    return JSONResponse({
        'done': False,
        'mode': mode,
        'pair_idx': pid,
        'source': source,
        'cluster_id': cluster_id,
        'cluster_size': cluster_size,
        'session_id': pair.get('session_id', ''),
        'marker_type': pair.get('marker_type', ''),
        'marker_match': pair.get('marker_match', ''),
        'premise_text': pair.get('premise_text', ''),
        'correction_text': pair.get('correction_text', ''),
        'tier_hint': pair.get('tier_hint'),
        'existing': existing_brief,
        'annotations': STATE['annotations_by_pair'].get(pid, []),
        'anti_drift': get_anti_drift(pid),
        'anti_drift_basis': feats.get('vector_basis', 'unavailable'),
        'mode_stats': mode_stats(),
        'progress': {
            'labeled': len(STATE['labels']),
            'tool_labeled': sum(1 for l in STATE['labels'].values() if l.get('labeled_via') == 'tool'),
            'queue_remaining': sum(
                1 for q in STATE['queue']
                if not already_tool_labeled(q['pair_idx'])
            ),
            'corpus_total': len(STATE['pairs']),
        },
    })


def mode_stats() -> dict:
    """Counts per mode — what's available right now."""
    stats = {'all': 0, 'disagreement': 0, 'low_conf': 0, 'audit': 0, 'unknown': 0, 'cluster': 0}
    for entry in STATE['queue']:
        if already_tool_labeled(entry['pair_idx']):
            continue
        src = entry.get('source', '')
        stats['all'] += 1
        if src == 'bootstrap_disagreement':
            stats['disagreement'] += 1
        elif src == 'low_confidence':
            stats['low_conf'] += 1
        elif src == 'audit_anchor':
            stats['audit'] += 1
    stats['unknown'] = sum(1 for i in range(len(STATE['pairs'])) if i not in STATE['labels'])
    clusters = STATE.get('clusters')
    if clusters:
        stats['cluster'] = sum(
            1 for c, members in clusters['members'].items()
            if any(not already_tool_labeled(p) for p in members)
        )
    return stats


@app.post('/api/label')
def api_label(payload: LabelPayload) -> JSONResponse:
    if payload.label not in LABEL_NAMES.values():
        raise HTTPException(400, f'invalid label: {payload.label}')
    if not (0 <= payload.pair_idx < len(STATE['pairs'])):
        raise HTTPException(400, f'invalid pair_idx: {payload.pair_idx}')

    pair = STATE['pairs'][payload.pair_idx]
    rec = {
        'pair_idx': payload.pair_idx,
        'label': payload.label,
        'marker_match': pair.get('marker_match', ''),
        'marker_type': pair.get('marker_type', ''),
        'session_id': pair.get('session_id', ''),
        'labeled_via': payload.source,
    }
    with open(LABELS, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    STATE['labels'][payload.pair_idx] = rec
    return JSONResponse({'ok': True, 'total_labeled': len(STATE['labels'])})


@app.post('/api/skip-pair')
def api_skip_pair() -> JSONResponse:
    # Skip current without saving label — picks next from queue
    return JSONResponse({'ok': True})


@app.get('/api/annotations/{pair_idx}')
def api_annotations_get(pair_idx: int) -> JSONResponse:
    return JSONResponse({'pair_idx': pair_idx, 'annotations': STATE['annotations_by_pair'].get(pair_idx, [])})


@app.post('/api/annotation')
def api_annotation_add(payload: AnnotationPayload) -> JSONResponse:
    if payload.marker not in ANNOTATION_MARKERS:
        raise HTTPException(400, f'invalid marker: {payload.marker} (must be one of {ANNOTATION_MARKERS})')
    if payload.side not in ('premise', 'correction'):
        raise HTTPException(400, f'invalid side: {payload.side}')
    if not (0 <= payload.pair_idx < len(STATE['pairs'])):
        raise HTTPException(400, f'invalid pair_idx: {payload.pair_idx}')

    pair = STATE['pairs'][payload.pair_idx]
    text = pair.get(f'{payload.side}_text', '') or ''
    n = len(text)
    if not (0 <= payload.char_start < payload.char_end <= n):
        raise HTTPException(400, f'char range [{payload.char_start},{payload.char_end}) out of bounds (len={n})')

    aid = STATE['next_annotation_id']
    STATE['next_annotation_id'] += 1

    from datetime import datetime
    rec = {
        'id': aid,
        'pair_idx': payload.pair_idx,
        'side': payload.side,
        'char_range': [payload.char_start, payload.char_end],
        'snippet': text[payload.char_start:payload.char_end][:200],
        'marker': payload.marker,
        'note': payload.note,
        'created_at': datetime.now(UTC).isoformat(timespec='seconds'),
        'labeled_via': 'tool',
    }
    with open(ANNOTATIONS, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    STATE['annotations'].append(rec)
    STATE['annotations_by_pair'].setdefault(payload.pair_idx, []).append(rec)
    return JSONResponse({'ok': True, 'annotation': rec})


@app.delete('/api/annotation/{annotation_id}')
def api_annotation_delete(annotation_id: int) -> JSONResponse:
    # Soft delete: append tombstone, rebuild grouping.
    target = next((a for a in STATE['annotations'] if int(a.get('id', -1)) == annotation_id and not a.get('deleted')), None)
    if not target:
        raise HTTPException(404, f'annotation {annotation_id} not found')

    from datetime import datetime
    tombstone = {
        'id': annotation_id,
        'pair_idx': target['pair_idx'],
        'deleted': True,
        'deleted_at': datetime.now(UTC).isoformat(timespec='seconds'),
    }
    with open(ANNOTATIONS, 'a') as f:
        f.write(json.dumps(tombstone, ensure_ascii=False) + '\n')
    STATE['annotations'].append(tombstone)
    pid = int(target['pair_idx'])
    STATE['annotations_by_pair'][pid] = [a for a in STATE['annotations_by_pair'].get(pid, []) if int(a.get('id', -1)) != annotation_id]
    return JSONResponse({'ok': True, 'deleted_id': annotation_id})


@app.get('/api/markers')
def api_markers() -> JSONResponse:
    return JSONResponse({
        'tiers': sorted(ANNOTATION_MARKERS),
        'inline_syntax_map': INLINE_SYNTAX_MAP,
    })


@app.get('/api/progress')
def api_progress() -> JSONResponse:
    return JSONResponse({
        'labeled': len(STATE['labels']),
        'tool_labeled': sum(1 for l in STATE['labels'].values() if l.get('labeled_via') == 'tool'),
        'queue_total': len(STATE['queue']),
        'queue_remaining': sum(1 for q in STATE['queue'] if not already_tool_labeled(q['pair_idx'])),
        'corpus_total': len(STATE['pairs']),
    })


# ── W3 Reconstruction Q&A endpoints ──────────────────────────────────────────

@app.get('/api/recon/sample')
def api_recon_sample() -> JSONResponse:
    pairs = recon_qa.load_pairs()
    used = recon_qa.used_pair_idxs()
    pair = recon_qa.sample_for_build(pairs, used)
    if pair is None:
        return JSONResponse({'done': True, 'total_in_set': len(used), 'available_count': 0})
    from collections import Counter
    session_sizes = Counter(p['session_id'] for p in pairs)
    available_count = sum(
        1 for p in pairs
        if p['pair_idx'] not in used and session_sizes[p['session_id']] >= 3
    )
    return JSONResponse({
        'done': False,
        'pair_idx': pair['pair_idx'],
        'session_id': pair['session_id'],
        'premise_text': pair['premise_text'],
        'correction_text': pair['correction_text'],
        'total_in_set': len(used),
        'available_count': available_count,
    })


class ReconSavePayload(BaseModel):
    q: str
    a_truth: str
    source_pair_idx: int
    source_session_id: str


@app.post('/api/recon/save')
def api_recon_save(payload: ReconSavePayload) -> JSONResponse:
    recon_qa.save_qa_entry({
        'q': payload.q,
        'a_truth': payload.a_truth,
        'source_pair_idx': payload.source_pair_idx,
        'source_session_id': payload.source_session_id,
    })
    total = len(recon_qa.load_qa_set())
    return JSONResponse({'status': 'ok', 'total': total})


class ReconEvalPayload(BaseModel):
    k_drop: float = 0.5
    ranker: str = 'importance'  # 'importance' (Phase 4C mixture) or 'density' (legacy)
    topic_decay: float = 0.5    # Phase 4E topic-shift drop; 1.0 = disabled


@app.post('/api/recon/eval')
def api_recon_eval(payload: ReconEvalPayload = ReconEvalPayload()) -> JSONResponse:
    results = recon_qa.run_eval(
        k_drop=payload.k_drop, ranker=payload.ranker, topic_decay=payload.topic_decay,
    )
    passed = sum(1 for r in results if r.get('pass'))
    total = len(results)
    accuracy = passed / total if total else 0.0
    return JSONResponse({'results': results, 'accuracy': accuracy, 'total': total, 'passed': passed})


@app.get('/api/recon/set')
def api_recon_set() -> JSONResponse:
    return JSONResponse({'entries': recon_qa.load_qa_set()})


class ReconSuggestPayload(BaseModel):
    source_pair_idx: int
    focus: str | None = None
    prior: list[dict] | None = None
    mode: str = 'complement'


@app.post('/api/recon/suggest')
def api_recon_suggest(payload: ReconSuggestPayload) -> JSONResponse:
    pairs = recon_qa.load_pairs()
    if not (0 <= payload.source_pair_idx < len(pairs)):
        return JSONResponse({'candidates': []})
    pair = pairs[payload.source_pair_idx]
    candidates = recon_qa.suggest_qa(
        pair, n=3,
        focus=payload.focus,
        prior=payload.prior,
        mode=payload.mode,
    )
    iter_meta = recon_qa.iter_chain_metrics(candidates, payload.prior, payload.mode) if candidates else None
    return JSONResponse({'candidates': candidates, 'iter_meta': iter_meta})


# ── HTML ──────────────────────────────────────────────────────────────────────

PAGE_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>weighted-compact опросник</title>
<style>
  :root {
    --bg: #0f1115;
    --bg2: #161922;
    --bg3: #1d212c;
    --fg: #d8dee9;
    --fg-dim: #6b7280;
    --accent: #7aa2f7;
    --keep: #9ece6a;
    --maybe: #e0af68;
    --skip: #6b7280;
    --fpos: #f7768e;
    --border: #2a2f3c;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 0;
    background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 14px; line-height: 1.55;
  }
  .top {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 22px; border-bottom: 1px solid var(--border);
    background: var(--bg2); font-size: 12px; color: var(--fg-dim);
  }
  .top .progress { color: var(--fg); }
  .layout {
    display: grid; grid-template-columns: 1fr 320px;
    gap: 22px; padding: 22px; max-width: 1400px; margin: 0 auto;
  }
  .pair-col h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--fg-dim); margin: 0 0 8px 0; font-weight: 600;
  }
  .pair-col h2 .role { color: var(--accent); }
  .block {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 18px;
    margin-bottom: 18px;
    font-family: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
    font-size: 13.5px; line-height: 1.6;
    white-space: pre-wrap; word-break: break-word;
    max-height: 38vh; overflow-y: auto;
  }
  /* Equal-weight: assistant and user blocks identical styling.
     Differential only via h2 label, not via block treatment. */
  .meta {
    display: flex; gap: 16px; padding: 12px 0;
    font-size: 12px; color: var(--fg-dim);
  }
  .meta span { padding: 2px 8px; background: var(--bg3); border-radius: 4px; }
  .meta b { color: var(--fg); font-weight: 500; }
  .prior {
    margin: 0 0 14px 0; padding: 10px 14px;
    background: rgba(122,162,247,0.07);
    border: 1px solid rgba(122,162,247,0.25);
    border-radius: 6px; font-size: 12.5px;
    display: flex; gap: 12px; align-items: center;
  }
  .prior .key { color: var(--fg-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .prior .src { color: var(--fg-dim); font-size: 11px; margin-left: auto; }
  .modebar {
    display: flex; gap: 6px; padding: 8px 22px;
    background: var(--bg2); border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .mode {
    background: transparent; color: var(--fg-dim);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 5px 11px; font-size: 11.5px; cursor: pointer;
    font-family: inherit; white-space: nowrap;
    display: flex; gap: 8px; align-items: center;
    transition: all 120ms ease;
  }
  .mode:hover { background: var(--bg3); color: var(--fg); }
  .mode.active { background: var(--accent); color: #0f1115; border-color: var(--accent); font-weight: 600; }
  .mode .count { font-family: monospace; font-size: 10.5px; opacity: 0.7; }
  .basis {
    font-size: 10.5px; color: var(--fg-dim); margin-top: 4px;
    font-family: monospace; line-height: 1.4;
  }
  .actions {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px; margin-top: 12px;
  }
  .actions button { justify-content: flex-start; }
  /* Rubric — collapsible sticky cheat-sheet (full-bleed) */
  .rubric {
    position: sticky; top: 0; z-index: 50;
    background: linear-gradient(180deg, rgba(22,25,34,0.97) 0%, rgba(22,25,34,0.93) 100%);
    backdrop-filter: blur(8px);
    border-bottom: 1px solid rgba(122,162,247,0.30);
    box-shadow: 0 2px 8px rgba(0,0,0,0.25);
    font-size: 10.5px; line-height: 1.5; color: var(--fg);
    margin-left: calc((100vw - 100%) / -2);
    margin-right: calc((100vw - 100%) / -2);
    width: 100vw; max-width: 100vw;
  }
  .rubric > summary {
    list-style: none;
    cursor: pointer; user-select: none;
    padding: 5px 22px;
    display: flex; align-items: center; gap: 8px;
    transition: background 120ms ease;
  }
  .rubric > summary:hover { background: rgba(122,162,247,0.05); }
  .rubric > summary::-webkit-details-marker { display: none; }
  .rubric > summary .r-h {
    color: var(--accent); font-size: 9.5px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.5px;
    padding-right: 10px; border-right: 1px solid rgba(122,162,247,0.25);
  }
  .rubric > summary .r-tag {
    color: var(--fg-dim); font-size: 9.5px; font-style: italic;
  }
  .rubric > summary .r-toggle {
    margin-left: auto;
    color: var(--fg-dim); font-size: 10px;
    font-family: monospace;
  }
  .rubric[open] > summary .r-toggle::before { content: "▾ скрыть"; }
  .rubric:not([open]) > summary .r-toggle::before { content: "▸ раскрыть"; }
  .rubric .r-body {
    padding: 10px 22px 12px 22px;
    border-top: 1px solid rgba(122,162,247,0.12);
  }
  .rubric .r-grid {
    display: grid;
    grid-template-columns: minmax(220px, 1fr) minmax(220px, 1fr) minmax(220px, 1.4fr);
    gap: 12px 22px;
  }
  .rubric .r-col {
    border-left: 2px solid rgba(122,162,247,0.18);
    padding-left: 10px;
  }
  .rubric .r-k {
    color: var(--fg-dim); font-size: 9.5px;
    text-transform: uppercase; letter-spacing: 1px;
    font-weight: 600; margin-bottom: 4px;
  }
  .rubric .r-v { color: var(--fg); font-size: 11px; line-height: 1.55; }
  .rubric .r-note {
    margin-top: 9px; font-size: 10px; line-height: 1.5;
    padding: 6px 10px;
    background: rgba(158,206,106,0.08);
    border-left: 2px solid rgba(158,206,106,0.45);
    border-radius: 3px; color: var(--fg);
  }
  .rubric .sep { color: var(--fg-dim); opacity: 0.35; padding: 0 2px; }
  .rubric code, .rubric kbd {
    background: var(--bg3); padding: 1px 5px; border-radius: 3px;
    font-family: monospace; font-size: 10px; color: var(--fg);
    border: 1px solid var(--border);
  }
  .rubric kbd { font-size: 9.5px; padding: 0 4px; margin: 0 1px; }
  .rubric b { font-weight: 600; color: var(--fg); }
  .rubric .tier-keep  { color: var(--keep);  font-weight: 600; }
  .rubric .tier-maybe { color: var(--maybe); font-weight: 600; }
  .rubric .tier-skip  { color: var(--skip);  font-weight: 600; }
  .rubric .tier-think {
    color: #b39df0; font-weight: 600;
    cursor: help; border-bottom: 1px dotted rgba(179,157,240,0.55);
  }
  .hint {
    font-size: 11px; color: var(--fg-dim);
    margin: -4px 0 8px 0; line-height: 1.5;
  }
  .hint .k { color: var(--keep); }
  .hint .m { color: var(--maybe); }
  .hint .s { color: var(--skip); }
  .hint .t { color: #b39df0; }
  button {
    background: var(--bg2); color: var(--fg);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 11px 18px; font-size: 14px; cursor: pointer;
    font-family: inherit; transition: all 120ms ease;
    display: flex; align-items: center; gap: 10px;
  }
  button:hover { background: var(--bg3); transform: translateY(-1px); }
  button kbd {
    background: var(--bg); padding: 2px 6px; border-radius: 3px;
    font-size: 11px; font-family: monospace; color: var(--fg-dim);
    border: 1px solid var(--border);
  }
  button.keep  { border-color: var(--keep); }
  button.keep:hover  { background: rgba(158,206,106,0.1); }
  button.maybe { border-color: var(--maybe); }
  button.maybe:hover { background: rgba(224,175,104,0.1); }
  button.skip  { border-color: var(--skip); }
  button.skip:hover  { background: rgba(107,114,128,0.15); }
  button.fpos  { border-color: var(--fpos); }
  button.fpos:hover  { background: rgba(247,118,142,0.1); }
  button.sec   { font-size: 12px; padding: 8px 12px; color: var(--fg-dim); }
  .sidebar {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
    align-self: start; position: sticky; top: 22px;
    max-height: calc(100vh - 80px); overflow-y: auto;
  }
  .sidebar h3 {
    margin: 0 0 6px 0; font-size: 11px; text-transform: uppercase;
    letter-spacing: 1.2px; color: var(--fg-dim); font-weight: 600;
  }
  .sidebar .help {
    font-size: 11.5px; color: var(--fg-dim); line-height: 1.5;
    margin-bottom: 14px; padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }
  .neighbor {
    padding: 10px 0; border-bottom: 1px solid var(--border);
    font-size: 12px;
  }
  .neighbor:last-child { border-bottom: none; }
  .neighbor .row1 {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 4px;
  }
  .neighbor .sim { color: var(--fg-dim); font-family: monospace; }
  .neighbor .lab {
    font-weight: 600; padding: 1px 7px; border-radius: 3px; font-size: 11px;
  }
  .lab-keep { background: rgba(158,206,106,0.18); color: var(--keep); }
  .lab-maybe { background: rgba(224,175,104,0.18); color: var(--maybe); }
  .lab-skip { background: rgba(107,114,128,0.18); color: var(--skip); }
  .lab-false_positive { background: rgba(247,118,142,0.18); color: var(--fpos); }
  .neighbor .marker {
    color: var(--fg-dim); font-family: monospace; font-size: 11px;
  }
  .empty { color: var(--fg-dim); font-size: 12px; padding: 8px 0; }
  .src-bootstrap { font-size: 0.7em; opacity: 0.6; margin-left: 4px; padding: 1px 4px; border: 1px solid #888; border-radius: 3px; color: #888; }
  .neighbor-bootstrap { opacity: 0.65; }
  .done {
    text-align: center; padding: 80px 22px; color: var(--fg-dim);
  }
  .done h1 { color: var(--fg); margin-bottom: 8px; }
  /* Tab switcher */
  .tabbar {
    display: flex; gap: 4px; padding: 8px 22px;
    background: var(--bg); border-bottom: 1px solid var(--border);
  }
  .tab-btn {
    background: transparent; color: var(--fg-dim);
    border: 1px solid var(--border); border-radius: 4px;
    padding: 5px 14px; font-size: 12px; cursor: pointer;
    font-family: inherit; transition: all 120ms ease;
  }
  .tab-btn:hover { background: var(--bg3); color: var(--fg); transform: none; }
  .tab-btn.active { background: var(--accent); color: #0f1115; border-color: var(--accent); font-weight: 600; }
  /* Reconstruction tab */
  #recon-tab { padding: 22px; max-width: 900px; margin: 0 auto; }
  #recon-tab h2 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1.2px;
    color: var(--fg-dim); margin: 0 0 12px 0; font-weight: 600;
  }
  .recon-card {
    background: var(--bg2); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px 18px; margin-bottom: 16px;
  }
  .recon-card .block {
    max-height: 20vh;
  }
  .recon-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--fg-dim); margin: 12px 0 4px 0; }
  .recon-input {
    width: 100%; background: var(--bg3); color: var(--fg);
    border: 1px solid var(--border); border-radius: 6px;
    padding: 10px 12px; font-family: inherit; font-size: 13.5px;
    resize: vertical; outline: none;
  }
  .recon-input:focus { border-color: var(--accent); }
  .recon-counter { font-size: 11.5px; color: var(--fg-dim); margin-bottom: 14px; }
  .recon-eval-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
  .recon-result-table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 14px; }
  .recon-result-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border);
    font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--fg-dim); }
  .recon-result-table td { padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-word; }
  .pass-yes { color: var(--keep); font-weight: 600; }
  .pass-no  { color: var(--fpos); }
  .pass-other { color: #d4a72c; }
  .suggest-card:hover { border-color: var(--accent, #7fd4a9); background: rgba(127, 212, 169, 0.03); }
  .accuracy-box {
    display: inline-block; padding: 8px 16px;
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 6px; font-family: monospace; font-size: 15px; margin-bottom: 14px;
  }
  /* Inline annotations: drag-select + tier border */
  .block.annotatable { cursor: text; user-select: text; position: relative; }
  .ann {
    border-bottom: 2px solid transparent;
    border-radius: 2px;
    padding: 0 1px;
    cursor: pointer;
    transition: background 120ms ease;
  }
  .ann:hover { background: rgba(255,255,255,0.05); }
  .ann-keep   { border-bottom-color: var(--keep);  background: rgba(158,206,106,0.10); }
  .ann-maybe  { border-bottom-color: var(--maybe); background: rgba(224,175,104,0.10); }
  .ann-skip   { border-bottom-color: var(--skip);  background: rgba(107,114,128,0.10); }
  .ann-think  { border-bottom-color: #b39df0;      background: rgba(179,157,240,0.10); }
  .ann-popup {
    position: fixed; z-index: 9999;
    background: var(--bg3); border: 1px solid var(--border);
    border-radius: 6px; padding: 6px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.45);
    display: none; gap: 4px;
  }
  .ann-popup button {
    padding: 4px 10px; font-size: 11px;
    border-radius: 4px; border: 1px solid var(--border);
    background: var(--bg2); color: var(--fg); cursor: pointer;
  }
  .ann-popup button:hover { transform: none; }
  .ann-popup .b-keep:hover  { background: rgba(158,206,106,0.18); border-color: var(--keep); }
  .ann-popup .b-maybe:hover { background: rgba(224,175,104,0.18); border-color: var(--maybe); }
  .ann-popup .b-skip:hover  { background: rgba(107,114,128,0.18); border-color: var(--skip); }
  .ann-popup .b-think:hover { background: rgba(179,157,240,0.18); border-color: #b39df0; }
  .ann-popup .b-cancel { color: var(--fg-dim); font-size: 10px; padding: 2px 8px; }
</style>
</head>
<body>
<div class="tabbar">
  <button class="tab-btn active" id="tab-quiz-btn" onclick="switchTab('quiz')">Опросник</button>
  <button class="tab-btn" id="tab-recon-btn" onclick="switchTab('recon')">Reconstruction</button>
</div>
<div id="quiz-tab">
<details class="rubric" id="rubric-quiz">
  <summary>
    <span class="r-h">Cheat · Опросник</span>
    <span class="r-tag">span tiers · workflow · hotkeys · modes</span>
    <span class="r-toggle"></span>
  </summary>
  <div class="r-body">
    <div class="r-grid">
      <div class="r-col">
        <div class="r-k">Span tiers (popup)</div>
        <div class="r-v">
          <span class="tier-keep">KEEP</span> — verbatim, load-bearing<br>
          <span class="tier-maybe">MAYBE</span> — gist хватит, перефраз ок<br>
          <span class="tier-skip">SKIP</span> — filler, безопасно drop<br>
          <span class="tier-think">THINK</span> — приглашение к рассуждению / re-examination
        </div>
      </div>
      <div class="r-col">
        <div class="r-k">Поток работы</div>
        <div class="r-v">
          <b>drag-select</b> текст → popup → tier (<b>auto-save</b> в момент клика)<br>
          клик по существующему span'у → удалить (с подтверждением)<br>
          нижние кнопки <kbd>K</kbd><kbd>M</kbd><kbd>S</kbd><kbd>X</kbd> → pair-level verdict + переход к следующей паре
        </div>
      </div>
      <div class="r-col">
        <div class="r-k">Modes & sidebar</div>
        <div class="r-v">
          <b>modebar</b> сверху — фильтр очереди: disagreement (бутстрап спорит с моделью) · low_conf · audit (sanity anchors) · unknown (никогда не размечал) · cluster (по semantic similarity).<br>
          <b>anti-drift</b> справа — 5 cosine-nearest прошлых решений на correction embedding. Цель: быть consistent с собой, не optimize'ить под model.
        </div>
      </div>
    </div>
    <div class="r-note">
      <b><span class="tier-think">THINK</span> tier semantics:</b> wired в <code>importance.py</code> с весом <code>+0.05</code> — «preserve + flag для re-examination» (меньше KEEP по силе, но не drop). Компонент сохранён в matrix отдельно — render-движок W2 сможет рисовать «here be open thread» специально.
    </div>
  </div>
</details>
<div id="root">Загрузка...</div>
</div>
<div id="recon-tab" style="display:none">
  <details class="rubric" id="rubric-recon">
    <summary>
      <span class="r-h">Cheat · Reconstruction</span>
      <span class="r-tag">build · eval · controls</span>
      <span class="r-toggle"></span>
    </summary>
    <div class="r-body">
      <div class="r-grid">
        <div class="r-col">
          <div class="r-k">Build set (сверху)</div>
          <div class="r-v">
            пишешь Q+A про текущую pair → <code>recon_qa_set.jsonl</code> (regression set «такой факт должен выживать»).<br>
            <b>Generate 3 candidates</b> — qwen2.5:7b сочиняет черновики, можно принять/редактировать.<br>
            <b>Iter chain</b>: complement (новые углы) / refine (другие фразы) / deepen (следствия).<br>
            <b>drift</b> над итерами — cos-distance от прошлых iter, ⚠ если вне expected range.
          </div>
        </div>
        <div class="r-col">
          <div class="r-k">Run eval (снизу)</div>
          <div class="r-v">
            для всех Q+A: <b>скрывает</b> source pair → <b>сжимает</b> остальные по importance (выкидывает нижнюю <code>k_drop</code> долю) → задаёт мне вопрос на сжатом контексте → судья gemma3 yes/no/other.<br>
            итог: <b>% pass</b> = насколько pipeline сохранил факт после compression.
          </div>
        </div>
        <div class="r-col">
          <div class="r-k">Controls</div>
          <div class="r-v">
            <b>k_drop</b> — доля pair'ов, что прячем. <code>0.5</code> = половину. Выше = жёстче, стресс-тест.<br>
            <b>ranker</b> — <code>importance</code> (4C: misstep+density+label+span) или <code>density</code> (legacy) для A/B.<br>
            <b>topic_decay</b> (4E) — embedding-based topic shift drop. <code>1.0</code> выкл, <code>0.5</code> пол-веса при смене темы, <code>0.0</code> режет всё чужое. Без classifier'а, чистая геометрия cohesion.
          </div>
        </div>
      </div>
    </div>
  </details>
  <div class="recon-counter" id="recon-counter">Загрузка...</div>

  <h2>Build set — добавить Q&amp;A</h2>
  <div class="recon-card" id="recon-build-card">Загрузка...</div>

  <div class="recon-label">Вопрос (factual, по correction_text)</div>
  <textarea class="recon-input" id="recon-q" rows="2" placeholder="Например: Что пользователь попросил исправить?"></textarea>

  <div class="recon-label">Правильный ответ (substring, case-insensitive match)</div>
  <input type="text" class="recon-input" id="recon-a" placeholder="Ключевое слово или фраза из ответа" style="resize:none">

  <div class="recon-label" style="margin-top:14px;display:flex;align-items:center;gap:12px">
    <span>Auto-suggest</span>
    <button onclick="reconSuggest()" class="sec" id="recon-suggest-btn" style="padding:4px 10px;font-size:11px">&#x1FA84; Generate 3 candidates</button>
    <span id="recon-suggest-status" style="font-size:11px;color:var(--fg-dim)"></span>
  </div>
  <div id="recon-suggest-list" style="display:flex;flex-direction:column;gap:6px;margin-bottom:12px"></div>

  <div id="recon-chain-controls" style="display:none;margin-top:8px;padding:8px;border:1px dashed var(--bd-dim,#333);border-radius:4px">
    <div style="font-size:11px;color:var(--fg-dim);margin-bottom:6px">Iter chain (накапливается, формирует полную картину связности):</div>
    <div style="display:flex;gap:6px;flex-wrap:wrap">
      <button onclick="reconIterChain('complement')" class="sec" style="padding:4px 10px;font-size:11px">+ complement (новые углы)</button>
      <button onclick="reconIterChain('refine')" class="sec" style="padding:4px 10px;font-size:11px">+ refine (другие фразы)</button>
      <button onclick="reconIterChain('deepen')" class="sec" style="padding:4px 10px;font-size:11px">+ deepen (следствия)</button>
      <button onclick="reconChainReset()" class="sec" style="padding:4px 10px;font-size:11px;margin-left:auto">&#x21BB; reset chain</button>
    </div>
    <div id="recon-chain-status" style="font-size:10px;color:var(--fg-dim);margin-top:4px"></div>
  </div>

  <div class="actions" style="margin-top:12px;margin-bottom:24px">
    <button onclick="reconSave()"><kbd>Save</kbd></button>
    <button class="sec" onclick="reconSkip()">Skip →</button>
  </div>

  <h2>Run eval</h2>
  <div class="recon-eval-row">
    <button onclick="reconRun()">▶ Run eval</button>
    <label style="font-size:12px;color:var(--fg-dim)">
      k_drop <input type="range" id="kdrop" min="0.1" max="0.9" step="0.1" value="0.5"
        style="vertical-align:middle;width:100px" oninput="document.getElementById('kdrop-val').textContent=this.value">
      <span id="kdrop-val">0.5</span>
    </label>
    <label style="font-size:12px;color:var(--fg-dim);margin-left:14px">
      ranker
      <select id="ranker" style="background:var(--bg3);color:var(--fg);border:1px solid var(--border);border-radius:4px;padding:3px 6px;font-size:12px">
        <option value="importance">importance (Phase 4C: misstep+span+density+label)</option>
        <option value="density">density (legacy)</option>
      </select>
    </label>
    <label style="font-size:12px;color:var(--fg-dim);margin-left:14px" title="каждый topic-step множит score на topic_decay; 1.0 = выкл, 0.5 = пол-веса при смене темы, 0.0 = режем всё чужое">
      topic_decay <input type="range" id="topic_decay" min="0.0" max="1.0" step="0.1" value="0.5"
        style="vertical-align:middle;width:90px" oninput="document.getElementById('topic_decay-val').textContent=this.value">
      <span id="topic_decay-val">0.5</span>
    </label>
  </div>
  <div id="recon-eval-status" style="font-size:12px;color:var(--fg-dim);margin-bottom:8px"></div>
  <div id="recon-eval-results"></div>
</div>

<script>
// Rubric collapse state — persists across page loads.
(function initRubricState() {
  for (const id of ['rubric-quiz', 'rubric-recon']) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.open = localStorage.getItem(id + '-open') === '1';
    el.addEventListener('toggle', () => {
      localStorage.setItem(id + '-open', el.open ? '1' : '0');
    });
  }
})();

const LABELS = {
  k: { name: 'keep',           cls: 'keep',  display: 'KEEP'      },
  m: { name: 'maybe',          cls: 'maybe', display: 'MAYBE'     },
  s: { name: 'skip',           cls: 'skip',  display: 'SKIP'      },
  x: { name: 'false_positive', cls: 'fpos',  display: 'FALSE-POS' },
};

const MODES = [
  { id: 'all',          label: 'Все' },
  { id: 'disagreement', label: 'Disagreement' },
  { id: 'low_conf',     label: 'Low-conf' },
  { id: 'audit',        label: 'Audit' },
  { id: 'unknown',      label: 'Unknown' },
  { id: 'cluster',      label: 'Cluster' },
];

let currentPair = null;
let currentMode = 'all';
let currentCluster = null;

async function loadNext() {
  const qs = new URLSearchParams({ mode: currentMode });
  if (currentMode === 'cluster' && currentCluster !== null) qs.set('cluster', currentCluster);
  const r = await fetch('/api/next?' + qs);
  const data = await r.json();
  if (data.done) {
    renderDone(data);
    return;
  }
  currentPair = data;
  if (data.cluster_id !== null && data.cluster_id !== undefined) {
    currentCluster = data.cluster_id;
  }
  render(data);
}

function setMode(m) {
  if (m === currentMode) return;
  currentMode = m;
  currentCluster = null;  // reset cluster pin when switching modes
  loadNext();
}

function nextCluster() {
  // Force cluster change — pick the next cluster with remaining work
  currentCluster = null;
  loadNext();
}

async function submit(key) {
  if (!currentPair || !LABELS[key]) return;
  await fetch('/api/label', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      pair_idx: currentPair.pair_idx,
      label: LABELS[key].name,
      source: 'tool',
    }),
  });
  await loadNext();
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

// ── Inline annotations ────────────────────────────────────────────────────────

let pendingRange = null;  // {side, start, end} awaiting tier choice

function renderAnnotated(text, annotations, side) {
  if (!text) return '';
  const live = annotations
    .filter(a => a.side === side && !a.deleted)
    .map(a => ({ id: a.id, start: a.char_range[0], end: a.char_range[1], marker: a.marker }))
    .sort((a, b) => a.start - b.start);
  // Drop overlapping (later wins by acceptance order would be wrong; keep first non-overlap)
  const flat = [];
  let cursor = 0;
  for (const a of live) {
    if (a.start < cursor) continue;
    flat.push(a);
    cursor = a.end;
  }
  let out = '';
  let pos = 0;
  for (const a of flat) {
    if (a.start > pos) out += esc(text.slice(pos, a.start));
    out += `<span class="ann ann-${a.marker}" data-ann-id="${a.id}" onclick="deleteAnnotation(${a.id})">${esc(text.slice(a.start, a.end))}</span>`;
    pos = a.end;
  }
  if (pos < text.length) out += esc(text.slice(pos));
  return out;
}

function charOffsetInBlock(block, node, offset) {
  // Sum textContent lengths of all preceding text nodes in DOM order.
  let acc = 0;
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let cur;
  while ((cur = walker.nextNode())) {
    if (cur === node) return acc + offset;
    acc += cur.textContent.length;
  }
  return acc;
}

function onBlockMouseUp(ev, side) {
  const sel = window.getSelection ? window.getSelection() : null;
  if (!sel || sel.isCollapsed) { hideAnnPopup(); return; }
  const block = ev.currentTarget;
  const range = sel.getRangeAt(0);
  if (!block.contains(range.startContainer) || !block.contains(range.endContainer)) {
    hideAnnPopup();
    return;
  }
  const start = charOffsetInBlock(block, range.startContainer, range.startOffset);
  const end   = charOffsetInBlock(block, range.endContainer,   range.endOffset);
  const a = Math.min(start, end), b = Math.max(start, end);
  if (b - a < 1) { hideAnnPopup(); return; }
  pendingRange = { side, start: a, end: b };

  // position:fixed → coords are viewport-relative, popup escapes block overflow clipping.
  const popup = document.getElementById('ann-popup');
  if (popup.parentElement !== document.body) document.body.appendChild(popup);
  popup.style.display = 'flex';
  const popupW = 280, popupH = 36;
  let x = ev.clientX + 8;
  let y = ev.clientY + 8;
  if (x + popupW > window.innerWidth)  x = window.innerWidth  - popupW - 8;
  if (y + popupH > window.innerHeight) y = ev.clientY - popupH - 8;
  popup.style.left = Math.max(8, x) + 'px';
  popup.style.top  = Math.max(8, y) + 'px';
}

function hideAnnPopup() {
  const popup = document.getElementById('ann-popup');
  if (popup) popup.style.display = 'none';
  pendingRange = null;
}

async function submitAnnotation(marker) {
  if (!pendingRange || !currentPair) { hideAnnPopup(); return; }
  const payload = {
    pair_idx: currentPair.pair_idx,
    side: pendingRange.side,
    char_start: pendingRange.start,
    char_end: pendingRange.end,
    marker: marker,
    note: '',
  };
  const r = await fetch('/api/annotation', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  const data = await r.json();
  if (!data.ok) { hideAnnPopup(); return; }
  currentPair.annotations = currentPair.annotations || [];
  currentPair.annotations.push(data.annotation);
  hideAnnPopup();
  rerenderBlocks();
}

async function deleteAnnotation(id) {
  if (!confirm('Удалить annotation #' + id + '?')) return;
  const r = await fetch('/api/annotation/' + id, { method: 'DELETE' });
  const data = await r.json();
  if (!data.ok) return;
  currentPair.annotations = (currentPair.annotations || []).filter(a => a.id !== id);
  rerenderBlocks();
}

function rerenderBlocks() {
  if (!currentPair) return;
  for (const side of ['premise', 'correction']) {
    const block = document.querySelector(`.block.annotatable[data-side="${side}"]`);
    if (!block) continue;
    const text = side === 'premise' ? currentPair.premise_text : currentPair.correction_text;
    // Preserve popup element across re-render
    const popup = document.getElementById('ann-popup');
    block.innerHTML = renderAnnotated(text, currentPair.annotations || [], side);
    if (popup && popup.parentElement !== block) {
      // Keep popup attached somewhere; will be reparented on next selection
    }
  }
  // Ensure popup exists (re-attach to body if orphaned)
  if (!document.getElementById('ann-popup')) {
    const p = document.createElement('div');
    p.id = 'ann-popup'; p.className = 'ann-popup';
    p.innerHTML = `
      <button class="b-keep"   onclick="submitAnnotation('keep')">KEEP</button>
      <button class="b-maybe"  onclick="submitAnnotation('maybe')">MAYBE</button>
      <button class="b-skip"   onclick="submitAnnotation('skip')">SKIP</button>
      <button class="b-think"  onclick="submitAnnotation('think')">THINK</button>
      <button class="b-cancel" onclick="hideAnnPopup()">×</button>`;
    p.onmousedown = (e) => e.stopPropagation();
    document.body.appendChild(p);
  }
}

document.addEventListener('mousedown', (ev) => {
  const popup = document.getElementById('ann-popup');
  if (!popup) return;
  if (popup.style.display === 'none') return;
  if (popup.contains(ev.target)) return;
  // Click on an existing annotation handles itself via onclick
  if (ev.target.classList && ev.target.classList.contains('ann')) return;
  // Click outside .block → hide
  const inBlock = ev.target.closest && ev.target.closest('.block.annotatable');
  if (!inBlock) hideAnnPopup();
});

function render(d) {
  const drift = (d.anti_drift || []).map(n => {
    const isBootstrap = n.labeled_via !== 'tool';
    const bootstrapBadge = isBootstrap ? `<span class="src-bootstrap">bootstrap</span>` : '';
    const cls = isBootstrap ? 'neighbor neighbor-bootstrap' : 'neighbor';
    return `
    <div class="${cls}">
      <div class="row1">
        <span class="sim">sim ${n.sim.toFixed(3)}</span>
        <span class="lab lab-${n.label}">${n.label}</span>${bootstrapBadge}
      </div>
      <div class="marker">[${esc(n.session)}] ${esc(n.marker || '—')}</div>
    </div>
  `;
  }).join('') || '<div class="empty">Соседи появятся после первых labels.</div>';

  const tierHint = d.tier_hint !== null && d.tier_hint !== undefined
    ? `<span>tier_hint <b>${d.tier_hint}</b></span>` : '';

  const clusterMeta = d.cluster_id !== null && d.cluster_id !== undefined
    ? `<span>cluster <b>#${d.cluster_id}</b> · ${d.cluster_size} pairs</span>` : '';

  const priorBlock = d.existing
    ? `<div class="prior">
         <span class="key">Прошлое решение</span>
         <span class="lab lab-${d.existing.label}">${d.existing.label}</span>
         <span class="src">via ${esc(d.existing.via)}</span>
       </div>`
    : '';

  const modeBar = MODES.map(m => {
    const cnt = (d.mode_stats || {})[m.id] ?? 0;
    const active = m.id === currentMode ? ' active' : '';
    return `<button class="mode${active}" onclick="setMode('${m.id}')">${m.label} <span class="count">${cnt}</span></button>`;
  }).join('') + (currentMode === 'cluster' ? `<button class="mode" onclick="nextCluster()">→ next cluster</button>` : '');

  document.getElementById('root').innerHTML = `
    <div class="top">
      <div>pair <b style="color:var(--fg)">#${d.pair_idx}</b> · session ${esc(d.session_id.slice(0,8))} · source <b style="color:var(--fg)">${esc(d.source)}</b></div>
      <div class="progress">${d.progress.tool_labeled} tool · ${d.progress.labeled} total · ${d.progress.queue_remaining} в очереди</div>
    </div>
    <div class="modebar">${modeBar}</div>
    <div class="layout">
      <div class="pair-col">
        ${priorBlock}
        <h2><span class="role">ASSISTANT</span> — premise (что я сказал до)</h2>
        <div class="block annotatable" data-side="premise" data-pair-idx="${d.pair_idx}"
             onmouseup="onBlockMouseUp(event, 'premise')">${renderAnnotated(d.premise_text, d.annotations || [], 'premise')}</div>
        <h2><span class="role">USER</span> — correction (твой ответ на это)</h2>
        <div class="block annotatable" data-side="correction" data-pair-idx="${d.pair_idx}"
             onmouseup="onBlockMouseUp(event, 'correction')">${renderAnnotated(d.correction_text, d.annotations || [], 'correction')}</div>
        <div id="ann-popup" class="ann-popup" onmousedown="event.stopPropagation()">
          <button class="b-keep"   onclick="submitAnnotation('keep')">KEEP</button>
          <button class="b-maybe"  onclick="submitAnnotation('maybe')">MAYBE</button>
          <button class="b-skip"   onclick="submitAnnotation('skip')">SKIP</button>
          <button class="b-think"  onclick="submitAnnotation('think')">THINK</button>
          <button class="b-cancel" onclick="hideAnnPopup()">×</button>
        </div>
        <div class="meta">
          <span>marker <b>${esc(d.marker_type)}</b></span>
          <span>match <b>${esc(d.marker_match)}</b></span>
          ${clusterMeta}
          ${tierHint}
        </div>
        <div class="actions">
          <button class="keep"  onclick="submit('k')"><kbd>K</kbd> KEEP <span style="color:var(--fg-dim);font-size:11px">load-bearing</span></button>
          <button class="maybe" onclick="submit('m')"><kbd>M</kbd> MAYBE <span style="color:var(--fg-dim);font-size:11px">gist хватит</span></button>
          <button class="skip"  onclick="submit('s')"><kbd>S</kbd> SKIP <span style="color:var(--fg-dim);font-size:11px">pointer-only</span></button>
          <button class="fpos"  onclick="submit('x')"><kbd>X</kbd> FALSE-POS <span style="color:var(--fg-dim);font-size:11px">не correction</span></button>
        </div>
      </div>
      <aside class="sidebar">
        <h3>Anti-drift · похожие прошлые решения</h3>
        <div class="help">
          Похожие pair'ы (cosine top-5). Цель — соответствовать своему классификатору, не optimize'ить под model.
          <div class="basis">sim by: ${esc(d.anti_drift_basis || 'n/a')}</div>
        </div>
        ${drift}
      </aside>
    </div>
  `;
}

function renderDone(d) {
  const modeBar = MODES.map(m => {
    const active = m.id === currentMode ? ' active' : '';
    return `<button class="mode${active}" onclick="setMode('${m.id}')">${m.label}</button>`;
  }).join('');
  document.getElementById('root').innerHTML = `
    <div class="modebar">${modeBar}</div>
    <div class="done">
      <h1>Mode «${currentMode}» пройден</h1>
      <p>Tool-labeled: ${d.labeled}. Переключись на другой mode сверху, или обнови queue.jsonl / build_queue.py.</p>
    </div>
  `;
}

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  const k = e.key.toLowerCase();
  if (LABELS[k]) { e.preventDefault(); submit(k); }
});

loadNext();

// ── Reconstruction tab ────────────────────────────────────────────────────────

let reconCurrentPair = null;
let reconChainState = { iter: 2, candidates: [], modes: [] };

function switchTab(tab) {
  const isQuiz = tab === 'quiz';
  document.getElementById('quiz-tab').style.display = isQuiz ? '' : 'none';
  document.getElementById('recon-tab').style.display = isQuiz ? 'none' : '';
  document.getElementById('tab-quiz-btn').classList.toggle('active', isQuiz);
  document.getElementById('tab-recon-btn').classList.toggle('active', !isQuiz);
  if (!isQuiz && !reconCurrentPair) reconLoadSample();
}

async function reconLoadSample() {
  reconChainReset();
  const r = await fetch('/api/recon/sample');
  const data = await r.json();
  document.getElementById('recon-counter').textContent =
    `В set: ${data.total_in_set} записей · доступно для добавления: ${data.available_count ?? '—'}`;
  const card = document.getElementById('recon-build-card');
  if (data.done) {
    card.innerHTML = `<div class="empty">Все eligible pairs уже в set.</div>`;
    reconCurrentPair = null;
    return;
  }
  reconCurrentPair = data;
  card.innerHTML = `
    <div style="font-size:11px;color:var(--fg-dim);margin-bottom:8px">
      pair #${data.pair_idx} · session ${esc(data.session_id.slice(0,8))}
    </div>
    <h2><span class="role">ASSISTANT</span> — premise</h2>
    <div class="block">${esc(data.premise_text)}</div>
    <h2><span class="role">USER</span> — correction (hidden in eval)</h2>
    <div class="block">${esc(data.correction_text)}</div>
  `;
  document.getElementById('recon-q').value = '';
  document.getElementById('recon-a').value = '';
  document.getElementById('recon-suggest-list').innerHTML = '';
  document.getElementById('recon-suggest-status').textContent = '';
}

async function reconSave() {
  if (!reconCurrentPair) return;
  const q = document.getElementById('recon-q').value.trim();
  const a = document.getElementById('recon-a').value.trim();
  if (!q || !a) { alert('Заполни Q и A'); return; }
  const r = await fetch('/api/recon/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      q, a_truth: a,
      source_pair_idx: reconCurrentPair.pair_idx,
      source_session_id: reconCurrentPair.session_id,
    }),
  });
  const data = await r.json();
  reconShowToast(`saved · ${data.total} в set`);
  reconCurrentPair = null;
  await reconLoadSample();
}

function reconShowToast(msg) {
  let t = document.getElementById('recon-toast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'recon-toast';
    t.style.cssText = 'position:fixed;bottom:24px;right:24px;background:#1a2520;border:1px solid #3a8e6f;color:#7fd4a9;padding:10px 16px;border-radius:6px;font-size:13px;opacity:0;transition:opacity 0.2s;z-index:1000;font-family:inherit';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = '1';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.opacity = '0'; }, 1800);
}

async function reconSkip() {
  reconCurrentPair = null;
  await reconLoadSample();
}

async function reconRun() {
  const kDrop = parseFloat(document.getElementById('kdrop').value);
  const ranker = document.getElementById('ranker').value;
  const topicDecay = parseFloat(document.getElementById('topic_decay').value);
  document.getElementById('recon-eval-status').textContent = 'Запрос к ollama... (может занять 60-120с с judge)';
  document.getElementById('recon-eval-results').innerHTML = '';
  const r = await fetch('/api/recon/eval', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({k_drop: kDrop, ranker: ranker, topic_decay: topicDecay}),
  });
  const data = await r.json();
  document.getElementById('recon-eval-status').textContent = '';
  if (!data.total) {
    document.getElementById('recon-eval-results').innerHTML = '<div class="empty">Set пустой — сначала добавь Q&amp;A.</div>';
    return;
  }
  const rows = data.results.map(r => {
    const verdict = (r.judge && r.judge.verdict) ? r.judge.verdict : 'other';
    const verdictClass = verdict === 'yes' ? 'pass-yes' : verdict === 'no' ? 'pass-no' : 'pass-other';
    const verdictIcon = verdict === 'yes' ? '✓' : verdict === 'no' ? '✗' : '?';
    const subIcon = r.substring_pass ? '✓' : '✗';
    const reasoning = (r.judge && r.judge.reasoning) ? r.judge.reasoning : '';
    return `
    <tr>
      <td>${esc(r.q)}</td>
      <td>${esc(r.a_truth)}</td>
      <td>${esc(r.predicted)}</td>
      <td class="${r.substring_pass ? 'pass-yes' : 'pass-no'}" title="substring case-insensitive">${subIcon}</td>
      <td class="${verdictClass}" title="${esc(reasoning)}">${verdictIcon}<span style="font-size:10px;margin-left:4px;color:var(--fg-dim)">${verdict}</span></td>
      <td style="color:var(--fg-dim);font-size:11px;max-width:240px">${esc(reasoning).slice(0, 100)}</td>
      <td style="color:var(--fg-dim)">${r.context_chars != null ? r.context_chars : '—'}</td>
    </tr>`;
  }).join('');
  const total = data.results.length;
  const judgeYes = data.results.filter(r => r.judge && r.judge.verdict === 'yes').length;
  const judgeOther = data.results.filter(r => r.judge && r.judge.verdict === 'other').length;
  const subPass = data.results.filter(r => r.substring_pass).length;
  document.getElementById('recon-eval-results').innerHTML = `
    <div class="accuracy-box">
      judge: <b>${(judgeYes / total * 100).toFixed(1)}%</b> yes (${judgeYes}/${total}) · ${judgeOther} other → ревизия<br>
      substring: ${(subPass / total * 100).toFixed(1)}% (нижняя граница)
    </div>
    <table class="recon-result-table">
      <thead><tr><th>Q</th><th>A truth</th><th>Predicted</th><th>Substr</th><th>Judge (gemma3:4b)</th><th>Reasoning</th><th>ctx</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

async function reconSuggest() {
  if (!reconCurrentPair) return;
  const sel = window.getSelection ? window.getSelection().toString().trim() : '';
  const focus = sel.length > 5 ? sel : null;  // >5 chars чтобы не ловить случайный клик

  const status = document.getElementById('recon-suggest-status');
  const list = document.getElementById('recon-suggest-list');
  status.textContent = focus
    ? `Генерируется с фокусом на выделение (${focus.length} симв)...`
    : 'Генерируется (qwen2.5:7b, до 90с)...';
  list.innerHTML = '';
  const r = await fetch('/api/recon/suggest', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({source_pair_idx: reconCurrentPair.pair_idx, focus: focus}),
  });
  const data = await r.json();
  status.textContent = '';
  if (!data.candidates || data.candidates.length === 0) {
    list.innerHTML = `<div style="font-size:11px;color:var(--fg-dim)">Не удалось сгенерировать. Попробуй ещё раз или напиши вручную.</div>`;
    return;
  }
  window._reconCandidates = data.candidates;
  list.innerHTML = data.candidates.map((c, i) => `
    <button class="suggest-card" onclick="reconPickSuggest(${i})" style="text-align:left;padding:8px 10px;border:1px solid var(--bd-dim,#333);background:transparent;cursor:pointer;font-size:12px;border-radius:4px">
      <div style="color:var(--fg-dim);font-size:10px;margin-bottom:2px">candidate ${i + 1}</div>
      <div><b>Q:</b> ${esc(c.q)}</div>
      <div><b>A:</b> ${esc(c.a_truth)}</div>
    </button>
  `).join('');
  reconChainState = { iter: 2, candidates: [...data.candidates], modes: ['initial'] };
  document.getElementById('recon-chain-controls').style.display = '';
  updateChainStatus();
}

function reconPickSuggest(i) {
  const c = window._reconCandidates && window._reconCandidates[i];
  if (!c) return;
  document.getElementById('recon-q').value = c.q;
  document.getElementById('recon-a').value = c.a_truth;
}

document.addEventListener('selectionchange', () => {
  const btn = document.getElementById('recon-suggest-btn');
  if (!btn) return;
  const sel = window.getSelection ? window.getSelection().toString().trim() : '';
  const reconTab = document.getElementById('recon-tab');
  const tabVisible = reconTab && reconTab.style.display !== 'none';
  if (!tabVisible) return;
  if (sel.length > 5) {
    btn.textContent = String.fromCodePoint(0x1F3AF) + ' Generate focused (' + sel.length + ' симв)';
    btn.style.borderColor = '#7fd4a9';
  } else {
    btn.textContent = String.fromCodePoint(0x1FA84) + ' Generate 3 candidates';
    btn.style.borderColor = '';
  }
});

async function reconIterChain(mode) {
  if (!reconCurrentPair || reconChainState.candidates.length === 0) return;
  const status = document.getElementById('recon-suggest-status');
  const list = document.getElementById('recon-suggest-list');
  const nextIter = reconChainState.iter + 1;
  status.textContent = 'Iter ' + nextIter + ' (' + mode + ')... ~60-90s';
  const sel = window.getSelection ? window.getSelection().toString().trim() : '';
  const focus = sel.length > 5 ? sel : null;
  const r = await fetch('/api/recon/suggest', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      source_pair_idx: reconCurrentPair.pair_idx,
      focus: focus,
      prior: reconChainState.candidates,
      mode: mode,
    }),
  });
  const data = await r.json();
  status.textContent = '';
  if (!data.candidates || data.candidates.length === 0) {
    status.textContent = 'Iter ' + nextIter + ': пусто. Попробуй другой mode или reset.';
    return;
  }
  const sep = document.createElement('div');
  sep.style.cssText = 'margin:10px 0 4px 0;font-size:11px;color:var(--fg-dim);border-top:1px dashed var(--bd-dim,#333);padding-top:8px';
  let driftLabel = '';
  if (data.iter_meta && data.iter_meta.semantic_drift !== null) {
    const m = data.iter_meta;
    const inRange = m.in_range;
    const colour = inRange === false ? 'color:#e0af68' : (inRange === true ? 'color:#9ece6a' : 'color:var(--fg-dim)');
    const rng = m.expected_range ? ` (exp ${m.expected_range[0]}–${m.expected_range[1]})` : '';
    const flag = inRange === false ? ' ⚠ drift вне range' : '';
    driftLabel = ` · <span style="${colour};font-family:monospace">drift ${m.semantic_drift.toFixed(3)}${rng}${flag}</span>`;
  }
  sep.innerHTML = '── iter ' + nextIter + ' · ' + mode + ' ──' + driftLabel;
  list.appendChild(sep);
  const startIdx = reconChainState.candidates.length;
  data.candidates.forEach((c, i) => {
    const idx = startIdx + i;
    const btn = document.createElement('button');
    btn.className = 'suggest-card';
    btn.style.cssText = 'text-align:left;padding:8px 10px;border:1px solid var(--bd-dim,#333);background:transparent;cursor:pointer;font-size:12px;border-radius:4px';
    btn.onclick = () => reconPickSuggest(idx);
    btn.innerHTML =
      '<div style="color:var(--fg-dim);font-size:10px;margin-bottom:2px">iter ' + nextIter + ' · ' + mode + ' · candidate ' + (i + 1) + '</div>' +
      '<div><b>Q:</b> ' + esc(c.q) + '</div>' +
      '<div><b>A:</b> ' + esc(c.a_truth) + '</div>';
    list.appendChild(btn);
    reconChainState.candidates.push(c);
  });
  reconChainState.iter = nextIter;
  reconChainState.modes.push(mode);
  window._reconCandidates = reconChainState.candidates;
  updateChainStatus();
}

function updateChainStatus() {
  const s = document.getElementById('recon-chain-status');
  if (!s) return;
  s.textContent = 'Iter ' + reconChainState.iter + ' · накоплено ' + reconChainState.candidates.length + ' кандидатов · цепь: ' + reconChainState.modes.join(' -> ');
}

function reconChainReset() {
  reconChainState = { iter: 2, candidates: [], modes: [] };
  const controls = document.getElementById('recon-chain-controls');
  if (controls) controls.style.display = 'none';
}
</script>
</body>
</html>
"""


@app.get('/', response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(PAGE_HTML)


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=PORT, log_level='warning')
