"""Judge: semantic verdict + iter-drift telemetry.

Black box:
  вход — question, a_truth, predicted, optional source_pair.
  выход — {verdict: 'yes'|'no'|'other', reasoning, model}. Tri-value verdict
         policy: 'other' лучше чем guessed 'yes' под uncertainty (§5.2).
  как открыт — `llm_judge` main scoring. `score` cheap substring backup.
         `iter_chain_metrics` separate telemetry over a generation chain.

`_get_e5_model` lazy ~120MB; only loaded when iter_chain_metrics fires.
"""
import re

import numpy as np

from ._constants import JUDGE_MODEL, OLLAMA_URL, _requests


_E5_MODEL = None


ITER_MODE_RANGES = {
    'complement': (0.45, 0.78),
    'refine':     (0.78, 0.93),
    'deepen':     (0.60, 0.85),
}


def _get_e5_model():
    global _E5_MODEL
    if _E5_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _E5_MODEL = SentenceTransformer('intfloat/multilingual-e5-small')
    return _E5_MODEL


def _embed_candidates(candidates):
    """Embed list of {q, a_truth} as 'passage: Q ... A ...' via e5."""
    if not candidates:
        return None
    texts = [
        f"passage: Q: {c.get('q', '').strip()} | A: {c.get('a_truth', '').strip()}"
        for c in candidates
    ]
    vecs = _get_e5_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def iter_chain_metrics(new_candidates, prior_candidates, mode):
    """Return semantic-drift metrics for one iter step.

    Returns dict with semantic_drift (mean-vec cosine), in_range (bool vs
    ITER_MODE_RANGES), expected_range, mode echo.
    """
    out = {
        'mode': mode, 'semantic_drift': None,
        'in_range': None, 'expected_range': None,
    }
    if not prior_candidates or not new_candidates:
        return out
    try:
        new_vec = _embed_candidates(new_candidates)
        prior_vec = _embed_candidates(prior_candidates)
        if new_vec is None or prior_vec is None:
            return out
        m_new = new_vec.mean(axis=0)
        m_prior = prior_vec.mean(axis=0)
        m_new /= (np.linalg.norm(m_new) + 1e-9)
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


def score(predicted, a_truth):
    """Case-insensitive substring match — cheap auxiliary signal.

    Guards against empty predicted/a_truth — '' in '' returns True otherwise,
    silently inflating fidelity counts on ollama-error responses.
    ~30% false-negative on paraphrase. Use as debug, not primary.
    """
    if not predicted or not a_truth:
        return False
    return a_truth.lower().strip() in predicted.lower()


def llm_judge(question, a_truth, predicted, source_pair=None, timeout=60):
    """Judge predicted answer vs a_truth semantically.

    Two-axis evaluation: vector match (same direction) AND anchor match
    (specific information present). Vague gesture without anchor = NOT pass.
    Prefer 'other' over a guessed 'yes' when uncertain.

    source_pair: optional dict with premise_text + correction_text. If
    provided, it is appended to the prompt so the judge can verify
    against actual source, not just compare two strings.

    Returns dict {verdict: 'yes'|'no'|'other', reasoning, model}.
    """
    source_block = ""
    if source_pair:
        src_p = str(source_pair.get('premise_text', '')).strip()[:1500]
        src_c = str(source_pair.get('correction_text', '')).strip()[:1500]
        source_block = f"""

SOURCE DIALOG (for verification — REFERENCE was extracted from here):
PREMISE: {src_p}
CORRECTION: {src_c}
"""

    prompt = f"""You are a judge for a memory-compaction system. A question
was generated from a source dialog fragment. Another LLM produced
SYSTEM ANSWER trying to reconstruct the original information. Decide
whether SYSTEM ANSWER preserves the information.

QUESTION: {question}
REFERENCE ANSWER (extracted from source): {a_truth}
SYSTEM ANSWER: {predicted}{source_block}

Evaluate on TWO axes:
- Vector match: does SYSTEM ANSWER point in the same semantic
  direction as REFERENCE? Synonyms, paraphrase, reordering — all OK
  if the direction holds.
- Anchor match: does SYSTEM ANSWER contain enough of the specific
  information (entity, number, delta, constraint) that a reader
  could act on it? Vague gesturing in the right direction without
  the specific anchor — that is NOT a pass.

Verdict policy:
- "yes" — both vector AND anchor match
- "no" — wrong vector, OR right vector but no anchor (vague paraphrase
  without the concrete information), OR explicit "I don't know"
- "other" — when REFERENCE itself looks underspecified or noisy,
  OR you would need to consult the source dialog to be sure. Choosing
  "other" because you are uncertain is BETTER than guessing "yes" to
  the nearest semantic centroid.

Reply in this format:
VERDICT: yes
REASON: one short phrase naming what matched / what is missing.

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
