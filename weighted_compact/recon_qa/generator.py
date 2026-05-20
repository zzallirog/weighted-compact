"""Question generator: turn a source pair into n Q/a_truth candidates via ollama.

Black box:
  вход — pair dict (premise_text + correction_text), n, optional focus highlight,
         optional prior candidate list + mode (complement | refine | deepen).
  выход — list of {q, a_truth} dicts; empty list on parse/timeout failure.
  как открыт — `suggest_qa` is the single entry. `ask_ollama` is the shared
         low-level LLM call also used by fidelity eval. Prompt is the §5.1
         two-axis quality bar + self-check (EN edition).
"""
import json
import re

from ._constants import MODEL, OLLAMA_URL, SUGGEST_MODEL, _requests


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


def suggest_qa(pair, n=3, timeout=90, focus=None, prior=None, mode='complement'):
    """Generate n candidate {q, a_truth} pairs for given pair.

    pair = dict with premise_text, correction_text.
    focus: optional user-highlighted string from premise/correction.
    prior: optional list of dicts [{q, a_truth}, ...] from previous iterations.
    mode: 'complement' | 'refine' | 'deepen' (see prompt for semantics).

    Returns list of dicts [{q: str, a_truth: str}, ...] or [] on error.
    """
    focus_block = ""
    if focus and focus.strip():
        focus_clean = focus.strip()[:500]
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
        for i, p in enumerate(prior[-6:], 1):
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

REQUIRED — each of the {n} questions must target a DIFFERENT type of
NON-PARAPHRASEABLE information. Phrasing examples below are illustrative,
not templates — adapt to the actual content:

  1. Specific actor or value (the WHAT/WHO): name a service, function,
     number, version, threshold. A = that concrete token, never a
     generic noun.
  2. Directional change (the DELTA): what got replaced/added/removed,
     in which direction. A = the named delta (e.g. "removed dense
     prefix", "α from 0.5 to 0.05"), not the verb alone.
  3. Constraint or invariant (the BOUNDARY): what must NOT happen, what
     is forbidden, what is locked. A = the named constraint
     (e.g. "no upload to cloud", "vector-first not classifier-first"),
     not a directive modifier alone.

A_truth must be a substring that is highly likely to appear in any reasonable phrasing of the answer. Avoid rare words the LLM might paraphrase.

A_truth quality bar (CRITICAL, models often fail here):
- A_truth MUST be content-bearing. If you can replace it with a synonym
  and the meaning stays — wrong choice. If you can DROP it from any
  reasonable answer and the answer is still correct — wrong choice.
- REJECT a_truth that is: a path fragment alone (/etc/, ~/.config),
  a modifier alone (обязательно, нужно, важно, must, should), a UI
  shortcut name (Ctrl+Shift+R) UNLESS the question is literally
  "which keyboard shortcut".
- PREFER a_truth that names: the actor (which service, which command,
  which function), the specific value (the number, the name, the
  threshold), the direction of change (increased/blocked/replaced).
- If the fragment is mostly a vibe-discussion or meta-comment with no
  concrete answerable hook — return an EMPTY array []. Better zero
  than three noisy ones.

Self-check before responding:
- Would the user himself write this Q and this A as a probe? If the Q
  reads like a school quiz and the A is a single rare noise word —
  rewrite or drop.
- Are any of your a_truth values just `обязательно` / `нужно` / `must` /
  `system` / `function` / `ok` / a bare path? If yes — that entry is
  noise, replace it or drop it.

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
