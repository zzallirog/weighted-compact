"""Reconstruction Q&A module — weighted-compact W3.

density score = mean of 16 density features per pair (scalar in [0, 1] range approx).
Higher density → pair carries more signal → kept when compacting.
"""
import datetime
import json
import os
import random
import re
from collections import Counter

import numpy as np

from weighted_compact import config

# `requests` is only used to POST to a local Ollama instance for the
# optional reconstruction-QA evaluator. Importing it at module top would
# force every consumer of recon_qa (the labeler `tool.py`, the importance
# mixture) to install `requests` just to load the module. Lazy-import it
# inside the three functions that actually call Ollama.


def _requests():
    import requests  # noqa: PLC0415

    return requests

# ── Iter-chain QC layer 1: embedding cos-distance ─────────────────────────────
# Embedded e5 model loaded lazily (~120MB). Used to compute semantic drift
# between iter candidates and prior candidates. Filed in TASKS.md §"Iter-chain QC".

_E5_MODEL = None

# Expected cos-sim ranges per mode. Outside → drift warning.
ITER_MODE_RANGES = {
    'complement': (0.45, 0.78),  # new aspects → moderate sim, not too high
    'refine':     (0.78, 0.93),  # paraphrase → high sim, same intent
    'deepen':     (0.60, 0.85),  # continuation → mid-high sim
}


def _get_e5_model():
    global _E5_MODEL
    if _E5_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _E5_MODEL = SentenceTransformer('intfloat/multilingual-e5-small')
    return _E5_MODEL


def _embed_candidates(candidates):
    """Embed a list of {q, a_truth} as 'passage: Q ... A ...' strings via e5."""
    if not candidates:
        return None
    texts = [
        f"passage: Q: {c.get('q', '').strip()} | A: {c.get('a_truth', '').strip()}"
        for c in candidates
    ]
    vecs = _get_e5_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def iter_chain_metrics(new_candidates, prior_candidates, mode):
    """Return semantic-drift metrics for an iter step.

    Returns dict:
      semantic_drift: float — cos-sim of mean(new) vs mean(prior); None if no prior
      in_range: bool        — whether drift sits in expected range for mode
      expected_range: [lo, hi] or null
      mode: echo of mode
    """
    out = {'mode': mode, 'semantic_drift': None,
           'in_range': None, 'expected_range': None}
    if not prior_candidates or not new_candidates:
        return out
    try:
        new_vec   = _embed_candidates(new_candidates)
        prior_vec = _embed_candidates(prior_candidates)
        if new_vec is None or prior_vec is None:
            return out
        m_new   = new_vec.mean(axis=0)
        m_prior = prior_vec.mean(axis=0)
        # L2-normalize means (encode already normalized rows; mean may not be unit-norm)
        m_new   /= (np.linalg.norm(m_new)   + 1e-9)
        m_prior /= (np.linalg.norm(m_prior) + 1e-9)
        sim = float(np.dot(m_new, m_prior))
        out['semantic_drift'] = round(sim, 4)
        rng = ITER_MODE_RANGES.get(mode)
        if rng:
            out['expected_range'] = list(rng)
            out['in_range'] = bool(rng[0] <= sim <= rng[1])
    except Exception as e:
        out['error'] = str(e)
    return out

RECON_SET = config.recon_qa_set_path()
PAIRS = config.pairs_path()
DENSITY = config.features_density_path()

# Optional Ollama-backed evaluator. Override with environment variables:
#   $WEIGHTED_COMPACT_OLLAMA_URL    (default: http://localhost:11434/api/generate)
#   $WEIGHTED_COMPACT_RECON_MODEL   (default: qwen2.5:7b)
#   $WEIGHTED_COMPACT_JUDGE_MODEL   (default: gemma3:4b — cross-model anti-bias)
OLLAMA_URL = os.environ.get(
    'WEIGHTED_COMPACT_OLLAMA_URL', 'http://localhost:11434/api/generate'
)
MODEL = os.environ.get('WEIGHTED_COMPACT_RECON_MODEL', 'qwen2.5:7b')
JUDGE_MODEL = os.environ.get('WEIGHTED_COMPACT_JUDGE_MODEL', 'gemma3:4b')
SUGGEST_MODEL = os.environ.get('WEIGHTED_COMPACT_SUGGEST_MODEL', MODEL)


def load_pairs():
    """Load pairs.jsonl, return list of dicts with added 'pair_idx' = enumerate index."""
    pairs = []
    for i, line in enumerate(open(PAIRS)):
        r = json.loads(line)
        r['pair_idx'] = i
        pairs.append(r)
    return pairs


def load_density():
    """Load features_density.npz, return dict pair_idx → density_score (mean of 16 features).

    npz layout: density=(471,16) indexed by pair_indices=(471,) int32.
    density_score = mean across 16 features. Higher = denser = more signal.
    """
    npz = np.load(DENSITY)
    arr = npz['density']           # shape (471, 16)
    pair_indices = npz['pair_indices']  # shape (471,) — maps row → pair_idx
    scores = arr.mean(axis=1)
    return {int(pair_indices[i]): float(scores[i]) for i in range(len(scores))}


IMPORTANCE = config.importance_path()
TOPIC_SEGMENTS = config.topic_segments_path()


def load_importance():
    """Load importance.npz (Phase 4C mixture). Returns dict pair_idx → importance.

    Fallback: if importance.npz missing, returns density dict so build_compacted_context
    keeps working in legacy mode.
    """
    if not IMPORTANCE.exists():
        return load_density()
    npz = np.load(IMPORTANCE, allow_pickle=True)
    return {int(npz['pair_indices'][i]): float(npz['importance'][i])
            for i in range(len(npz['importance']))}


def load_topic_map():
    """Load topic_segments.npz → dict pair_idx → topic_id. Empty dict if missing."""
    if not TOPIC_SEGMENTS.exists():
        return {}
    npz = np.load(TOPIC_SEGMENTS, allow_pickle=True)
    return {int(npz['pair_indices'][i]): int(npz['topic_id'][i])
            for i in range(len(npz['pair_indices']))}


def load_qa_set():
    if not RECON_SET.exists():
        return []
    return [json.loads(line) for line in open(RECON_SET) if line.strip()]


def used_pair_idxs():
    return {e['source_pair_idx'] for e in load_qa_set()}


def sample_for_build(pairs, used_idxs):
    """Pick a random pair_idx not in used_idxs, prefer sessions with >=3 pairs.

    Returns one pair dict or None if all candidates exhausted.
    """
    session_sizes = Counter(p['session_id'] for p in pairs)
    candidates = [
        p for p in pairs
        if p['pair_idx'] not in used_idxs
        and session_sizes[p['session_id']] >= 3
    ]
    if not candidates:
        return None
    return random.choice(candidates)


def save_qa_entry(entry):
    """Append entry to recon_qa_set.jsonl.

    Expected shape: {q, a_truth, source_pair_idx, source_session_id}.
    created_at added here.
    """
    entry['created_at'] = datetime.datetime.now().isoformat()
    with open(RECON_SET, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def build_compacted_context(source_pair_idx, pairs, scores, k_drop=0.5,
                            topic_decay=0.5, topic_map=None):
    """Build markdown context for a session, hiding source_pair (ground truth).

    `scores` is a dict pair_idx → ranking score (higher = preserve).

    Topic-shift drop (Phase 4E, no classifier — pure embedding cohesion):
      topic_map = dict pair_idx → topic_id (from topic_segments.npz).
      For each candidate, distance d = |topic_candidate - topic_source|.
      effective_score = scores[pid] * topic_decay^d.
      → pairs in a different topic receive decay; the further the topic_id,
      the harder the drop. d=0 → ×1, d=1 → ×0.5 (default), d=2 → ×0.25, ...
      Pass topic_map=None (or topic_decay=1.0) to disable.
    """
    source_pair = pairs[source_pair_idx]
    sess = source_pair['session_id']
    session_pairs = [p for p in pairs if p['session_id'] == sess and p['pair_idx'] != source_pair_idx]
    if not session_pairs:
        return ''

    if topic_map and topic_decay < 1.0:
        t_source = topic_map.get(source_pair_idx, 0)
        def eff(p):
            t = topic_map.get(p['pair_idx'], 0)
            d = abs(t - t_source)
            return scores.get(p['pair_idx'], 0.0) * (topic_decay ** d)
        ranked = sorted(session_pairs, key=eff, reverse=True)
    else:
        ranked = sorted(session_pairs, key=lambda p: scores.get(p['pair_idx'], 0.0), reverse=True)

    keep_n = max(1, int(len(ranked) * (1 - k_drop)))
    kept = ranked[:keep_n]
    kept.sort(key=lambda p: p['pair_idx'])

    chunks = []
    for p in kept:
        chunks.append(f"PREMISE: {p['premise_text']}\n\nCORRECTION: {p['correction_text']}")
    return '\n\n---\n\n'.join(chunks)


def ask_ollama(context, question, timeout=60):
    """Call ollama with context + question. Returns answer string or '<ollama_error: ...>'."""
    prompt = f"""You are given a dialog fragment:

{context}

---

Answer the question BRIEFLY (1-2 sentences) based ONLY on this fragment. If the answer is not in the fragment, write "I don't know".

Question: {question}

Answer:"""
    try:
        r = _requests().post(OLLAMA_URL, json={
            'model': MODEL,
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.1, 'num_predict': 100},
        }, timeout=timeout)
        return r.json().get('response', '').strip()
    except Exception as e:
        return f'<ollama_error: {e}>'


def score(predicted, a_truth):
    """Case-insensitive substring match."""
    return a_truth.lower().strip() in predicted.lower()


def suggest_qa(pair, n=3, timeout=90, focus=None, prior=None, mode='complement'):
    """Generate n candidate {q, a_truth} pairs for given pair.

    pair = dict with premise_text, correction_text.
    focus: optional user-highlighted string from premise/correction.
    When provided, all candidates are anchored around it.
    prior: optional list of dicts [{q, a_truth}, ...] from previous iterations.
    mode: when prior is given, one of:
      - 'complement' — generate Qs covering aspects NOT in prior
      - 'refine'     — generate alternative phrasings of prior Qs (same intent, different words)
      - 'deepen'     — generate follow-ups that ASSUME prior answers as known context
    Returns list of dicts [{q: str, a_truth: str}, ...] or [] on error.
    """
    focus_block = ""
    if focus and focus.strip():
        focus_clean = focus.strip()[:500]  # cap length so we don't blow up the prompt
        focus_block = f"""

CRITICALLY IMPORTANT: the user manually HIGHLIGHTED this part as KEY:
\"\"\"
{focus_clean}
\"\"\"
All {n} generated questions must check the preservation of information SPECIFICALLY from this highlighted part. Do not wander into other parts of the pair unless they are directly related to the highlight.
"""

    prior_block = ""
    if prior and isinstance(prior, list) and len(prior) > 0:
        prior_lines = []
        for i, p in enumerate(prior[-6:], 1):  # cap last 6 so we don't blow up the prompt
            q = str(p.get('q', '')).strip()[:200]
            a = str(p.get('a_truth', '')).strip()[:100]
            if q and a:
                prior_lines.append(f"  {i}. Q: \"{q}\" -> A: \"{a}\"")
        if prior_lines:
            mode_instructions = {
                'complement': (
                    "Generate Qs targeting ASPECTS of the pair that previous iterations did NOT cover. "
                    "Do not repeat what was already asked. Find new angles."
                ),
                'refine': (
                    "Generate ALTERNATIVE PHRASINGS of the previous questions: "
                    "same intent, different words. Goal — robust eval across different phrasings."
                ),
                'deepen': (
                    "Generate Qs that EXTEND the previous ones — assume their answers as known context. "
                    "Ask about consequences, related facts, deeper connections."
                ),
            }
            mode_inst = mode_instructions.get(mode, mode_instructions['complement'])
            prior_str = '\n'.join(prior_lines)
            prior_block = f"""

PREVIOUS ITERATIONS PRODUCED:
{prior_str}

CHAIN MODE ({mode}): {mode_inst}
"""

    prompt = f"""You are given a dialog fragment:

PREMISE (assistant's reply):
{pair['premise_text']}

CORRECTION (user's edit / reaction):
{pair['correction_text']}
{focus_block}{prior_block}
Generate {n} diverse questions with short answers that test preservation of the KEY information in this fragment under compaction.

FORBIDDEN:
- Yes/no questions (where the answer is "yes", "no", "yes/no"). They match trivially.
- Questions about the dialog itself ("what did the user say?"). Only about CONTENT.
- Generic answers ("ok", "got it", "system", "function").

REQUIRED — each of the {n} questions must target a DIFFERENT type of critical information:
  1. Concrete entity: name / number / path / command / url. A = that entity (1-3 words).
  2. Condition or directive: "what must be done", "what is forbidden", "where it must be". A = the condition's keyword.
  3. Cause-and-effect: "what happens if X" / "why Y". A = the consequence or cause (1-3 words).

A_truth must be a substring that is highly likely to appear in any reasonable phrasing of the answer. Avoid rare words the LLM might paraphrase.

Response format — STRICT JSON array (JSON only, no prefixes):
[
  {{"q": "question?", "a": "short answer"}},
  {{"q": "question?", "a": "short answer"}},
  {{"q": "question?", "a": "short answer"}}
]"""
    try:
        r = _requests().post(OLLAMA_URL, json={
            'model': SUGGEST_MODEL,
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.4, 'num_predict': 400},
        }, timeout=timeout)
        text = r.json().get('response', '').strip()
        match = re.search(r'\[\s*\{.*?\}\s*\]', text, re.DOTALL)
        if not match:
            return []
        try:
            arr = json.loads(match.group(0))
            return [
                {'q': str(it.get('q', '')).strip(), 'a_truth': str(it.get('a', '')).strip()}
                for it in arr if it.get('q') and it.get('a')
            ][:n]
        except Exception:
            return []
    except Exception:
        return []


def llm_judge(question, a_truth, predicted, timeout=60):
    """Judge predicted answer vs a_truth semantically.

    Returns dict {verdict: 'yes'|'no'|'other', reasoning: str, model: JUDGE_MODEL}.
    """
    prompt = f"""You are given a question and a reference answer. Then a different system's answer is provided. Decide whether that system's answer SEMANTICALLY matches the reference.

QUESTION: {question}
REFERENCE ANSWER: {a_truth}
SYSTEM ANSWER: {predicted}

Rules:
- "yes" — the system answer conveys the same information as the reference (synonyms, paraphrasing — OK)
- "no" — the system answer contradicts the reference or says "I don't know" / is missing the key information
- "other" — ambiguous, partial, uncertain

Reply in this format:
VERDICT: yes
REASON: one short phrase.

Only one verdict (yes/no/other) and one reason."""
    try:
        r = _requests().post(OLLAMA_URL, json={
            'model': JUDGE_MODEL,
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.0, 'num_predict': 80},
        }, timeout=timeout)
        text = r.json().get('response', '').strip()
        m = re.search(r'VERDICT:\s*(yes|no|other)', text, re.IGNORECASE)
        verdict = m.group(1).lower() if m else 'other'
        return {'verdict': verdict, 'reasoning': text, 'model': JUDGE_MODEL}
    except Exception as e:
        return {'verdict': 'other', 'reasoning': f'<judge_error: {e}>', 'model': JUDGE_MODEL}


def run_eval(k_drop=0.5, ranker='importance', topic_decay=0.5):
    """Evaluate all Q&A entries: build context, query ollama, score with substring + LLM judge.

    ranker: 'importance' (Phase 4C mixture, default) or 'density' (legacy).
    topic_decay: float ∈ (0,1]. Phase 4E embedding-based topic-shift drop.
        1.0 = disabled; 0.5 = each topic step halves score; 0.0 = drop everything outside current topic.
    """
    pairs = load_pairs()
    scores = load_importance() if ranker == 'importance' else load_density()
    topic_map = load_topic_map() if topic_decay < 1.0 else None
    qa_set = load_qa_set()
    results = []
    for entry in qa_set:
        ctx = build_compacted_context(
            entry['source_pair_idx'], pairs, scores, k_drop,
            topic_decay=topic_decay, topic_map=topic_map,
        )
        if not ctx:
            results.append({
                **entry,
                'predicted': '<empty_context>',
                'substring_pass': False,
                'judge': {'verdict': 'no', 'reasoning': 'empty context', 'model': JUDGE_MODEL},
                'context_chars': 0,
            })
            continue
        pred = ask_ollama(ctx, entry['q'])
        sub_pass = score(pred, entry['a_truth'])
        judge = llm_judge(entry['q'], entry['a_truth'], pred)
        results.append({
            **entry,
            'predicted': pred,
            'substring_pass': sub_pass,
            'judge': judge,
            'context_chars': len(ctx),
        })
    return results
