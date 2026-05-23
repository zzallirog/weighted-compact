#!/usr/bin/env python3
"""Re-judge bench per-entry results with Claude Sonnet 4.6 via OpenRouter.

Standalone — no project imports.

Input: positional path to per-entry JSONL with rows containing at minimum
    {method, source_pair_idx, q, a_truth, predicted, gemma_verdict}.

Output: rejudged JSONL on stdout, one line per entry, with original fields
    plus {sonnet_verdict, sonnet_reasoning, sonnet_model, agreement,
    sonnet_usage}.

Stderr: per-method judge_yes counts + Cohen's kappa cross-judge table.

Env:
    OPENROUTER_API_KEY  required.

Usage:
    OPENROUTER_API_KEY=... python scripts/sonnet_rejudge.py per_entry.jsonl > out.jsonl

Throttles to MAX_CONCURRENT (default 4) parallel OpenRouter calls. Refuses
to exceed MAX_CALLS (default 200) entries to cap cost (~$2 at $3/$15 per
1M tokens for Sonnet 4.6).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from typing import Any

import urllib.error
import urllib.request

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'
SONNET_MODEL = 'anthropic/claude-sonnet-4.6'
MAX_CONCURRENT = int(os.environ.get('SONNET_REJUDGE_CONCURRENCY', '4'))
MAX_CALLS = int(os.environ.get('SONNET_REJUDGE_MAX_CALLS', '200'))
REQUEST_TIMEOUT = float(os.environ.get('SONNET_REJUDGE_TIMEOUT', '60'))

PRICE_IN_PER_TOK = 3.0e-6     # $/token, Claude Sonnet 4.6 input
PRICE_OUT_PER_TOK = 15.0e-6   # $/token, Claude Sonnet 4.6 output


def build_prompt(question: str, a_truth: str, predicted: str,
                 source_pair: dict[str, Any] | None = None) -> str:
    """Mirror weighted_compact.recon_qa.judge.llm_judge prompt exactly."""
    source_block = ''
    if source_pair:
        src_p = str(source_pair.get('premise_text', '')).strip()[:1500]
        src_c = str(source_pair.get('correction_text', '')).strip()[:1500]
        source_block = (
            '\n\nSOURCE DIALOG (for verification — REFERENCE was extracted from here):'
            f'\nPREMISE: {src_p}'
            f'\nCORRECTION: {src_c}\n'
        )

    return (
        'You are a judge for a memory-compaction system. A question\n'
        'was generated from a source dialog fragment. Another LLM produced\n'
        'SYSTEM ANSWER trying to reconstruct the original information. Decide\n'
        'whether SYSTEM ANSWER preserves the information.\n'
        '\n'
        f'QUESTION: {question}\n'
        f'REFERENCE ANSWER (extracted from source): {a_truth}\n'
        f'SYSTEM ANSWER: {predicted}{source_block}\n'
        '\n'
        'Evaluate on TWO axes:\n'
        '- Vector match: does SYSTEM ANSWER point in the same semantic\n'
        '  direction as REFERENCE? Synonyms, paraphrase, reordering — all OK\n'
        '  if the direction holds.\n'
        '- Anchor match: does SYSTEM ANSWER contain enough of the specific\n'
        '  information (entity, number, delta, constraint) that a reader\n'
        '  could act on it? Vague gesturing in the right direction without\n'
        '  the specific anchor — that is NOT a pass.\n'
        '\n'
        'Verdict policy:\n'
        '- "yes" — both vector AND anchor match\n'
        '- "no" — wrong vector, OR right vector but no anchor (vague paraphrase\n'
        '  without the concrete information), OR explicit "I don\'t know"\n'
        '- "other" — when REFERENCE itself looks underspecified or noisy,\n'
        '  OR you would need to consult the source dialog to be sure. Choosing\n'
        '  "other" because you are uncertain is BETTER than guessing "yes" to\n'
        '  the nearest semantic centroid.\n'
        '\n'
        'Reply in this format:\n'
        'VERDICT: yes\n'
        'REASON: one short phrase naming what matched / what is missing.\n'
        '\n'
        'Only one verdict (yes/no/other) and one reason.'
    )


def parse_verdict(text: str) -> str:
    import re
    m = re.search(r'VERDICT:\s*(yes|no|other)', text, re.IGNORECASE)
    return m.group(1).lower() if m else 'other'


def call_sonnet_sync(api_key: str, prompt: str) -> dict[str, Any]:
    payload = json.dumps({
        'model': SONNET_MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': 0.0,
        'max_tokens': 200,
    }).encode()
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com/zzallirog/weighted-compact',
            'X-Title': 'weighted-compact bench cross-judge',
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
        body = json.loads(r.read())
    text = body['choices'][0]['message']['content']
    usage = body.get('usage', {}) or {}
    return {
        'text': text,
        'verdict': parse_verdict(text),
        'prompt_tokens': int(usage.get('prompt_tokens', 0) or 0),
        'completion_tokens': int(usage.get('completion_tokens', 0) or 0),
    }


async def judge_one(api_key: str, sem: asyncio.Semaphore, row: dict[str, Any]) -> dict[str, Any]:
    prompt = build_prompt(row.get('q', ''), row.get('a_truth', ''),
                          row.get('predicted', ''), row.get('source_pair'))
    out = dict(row)
    last_err = None
    for attempt in range(3):
        try:
            async with sem:
                # urllib is sync; offload so the semaphore actually gates wallclock
                res = await asyncio.to_thread(call_sonnet_sync, api_key, prompt)
            out['sonnet_verdict'] = res['verdict']
            out['sonnet_reasoning'] = res['text']
            out['sonnet_model'] = SONNET_MODEL
            out['sonnet_usage'] = {
                'prompt_tokens': res['prompt_tokens'],
                'completion_tokens': res['completion_tokens'],
            }
            gv = row.get('gemma_verdict')
            out['agreement'] = (gv == res['verdict']) if gv else None
            return out
        except urllib.error.HTTPError as e:
            last_err = f'HTTP {e.code}: {e.reason}'
            # Backoff on 429 / 5xx
            if e.code in (429, 500, 502, 503, 504):
                await asyncio.sleep(2 ** attempt)
                continue
            break
        except Exception as e:
            last_err = f'{type(e).__name__}: {e}'
            await asyncio.sleep(2 ** attempt)
    out['sonnet_verdict'] = 'other'
    out['sonnet_reasoning'] = f'<sonnet_error: {last_err}>'
    out['sonnet_model'] = SONNET_MODEL
    out['sonnet_usage'] = {'prompt_tokens': 0, 'completion_tokens': 0}
    gv = row.get('gemma_verdict')
    out['agreement'] = (gv == 'other') if gv else None
    return out


def cohens_kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa across categorical labels in `pairs`."""
    if not pairs:
        return float('nan')
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    # marginal probs
    marg_a = {lab: 0 for lab in labels}
    marg_b = {lab: 0 for lab in labels}
    for a, b in pairs:
        marg_a[a] += 1
        marg_b[b] += 1
    pe = sum((marg_a[lab] / n) * (marg_b[lab] / n) for lab in labels)
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1.0 - pe)


def summarize(rows: list[dict[str, Any]]) -> str:
    by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_method[r.get('method', '?')].append(r)

    lines = []
    lines.append('')
    lines.append('=== Per-method judge_yes / n ===')
    lines.append(f'{"method":<32} {"n":>4} {"gemma_yes":>10} {"gemma_frac":>12} '
                 f'{"sonnet_yes":>11} {"sonnet_frac":>13}')
    for m, rs in sorted(by_method.items()):
        n = len(rs)
        gy = sum(1 for r in rs if r.get('gemma_verdict') == 'yes')
        sy = sum(1 for r in rs if r.get('sonnet_verdict') == 'yes')
        lines.append(f'{m:<32} {n:>4} {gy:>10} {gy/n:>12.3f} {sy:>11} {sy/n:>13.3f}')

    lines.append('')
    lines.append('=== Cross-judge agreement (all entries) ===')
    pairs_all = [(r.get('gemma_verdict', 'other'), r.get('sonnet_verdict', 'other')) for r in rows]
    n = len(pairs_all)
    raw_agree = sum(1 for a, b in pairs_all if a == b) / n if n else float('nan')
    kappa = cohens_kappa(pairs_all)
    lines.append(f'n_total       = {n}')
    lines.append(f'raw_agreement = {raw_agree:.3f}')
    lines.append(f'cohens_kappa  = {kappa:.3f}')

    lines.append('')
    lines.append('=== Cross-judge confusion (gemma rows × sonnet cols) ===')
    labels = ['yes', 'no', 'other']
    counts = {(g, s): 0 for g in labels for s in labels}
    for g, s in pairs_all:
        if g not in labels:
            g = 'other'
        if s not in labels:
            s = 'other'
        counts[(g, s)] += 1
    header = ' ' * 12 + ' '.join(f'{s:>8}' for s in labels)
    lines.append(header)
    for g in labels:
        row = f'gemma {g:>5} ' + ' '.join(f'{counts[(g, s)]:>8}' for s in labels)
        lines.append(row)

    lines.append('')
    lines.append('=== Cohen kappa per method ===')
    for m, rs in sorted(by_method.items()):
        pairs_m = [(r.get('gemma_verdict', 'other'), r.get('sonnet_verdict', 'other')) for r in rs]
        k = cohens_kappa(pairs_m)
        n_m = len(pairs_m)
        ra = sum(1 for a, b in pairs_m if a == b) / n_m if n_m else float('nan')
        lines.append(f'{m:<32} n={n_m:>4} raw_agree={ra:.3f}  kappa={k:.3f}')

    lines.append('')
    lines.append('=== Cost ===')
    in_tok = sum((r.get('sonnet_usage') or {}).get('prompt_tokens', 0) for r in rows)
    out_tok = sum((r.get('sonnet_usage') or {}).get('completion_tokens', 0) for r in rows)
    cost = in_tok * PRICE_IN_PER_TOK + out_tok * PRICE_OUT_PER_TOK
    lines.append(f'input_tokens  = {in_tok}')
    lines.append(f'output_tokens = {out_tok}')
    lines.append(f'cost_usd      = ${cost:.4f}')
    return '\n'.join(lines)


async def main_async(rows: list[dict[str, Any]], api_key: str) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    print(f'[sonnet_rejudge] {len(rows)} entries  concurrency={MAX_CONCURRENT}',
          file=sys.stderr, flush=True)

    done_count = 0
    results: list[dict[str, Any]] = [None] * len(rows)  # type: ignore

    async def run_one(i: int, row: dict[str, Any]):
        nonlocal done_count
        out = await judge_one(api_key, sem, row)
        results[i] = out
        done_count += 1
        if done_count % 10 == 0 or done_count == len(rows):
            print(f'[sonnet_rejudge] {done_count}/{len(rows)} done', file=sys.stderr, flush=True)
        # emit incrementally to stdout
        sys.stdout.write(json.dumps(out, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    await asyncio.gather(*(run_one(i, r) for i, r in enumerate(rows)))
    return results  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description='Rejudge bench per-entry rows with Sonnet 4.6.')
    parser.add_argument('input', help='Per-entry JSONL path.')
    args = parser.parse_args()

    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        print('FATAL: OPENROUTER_API_KEY not set in env', file=sys.stderr)
        return 2

    rows: list[dict[str, Any]] = []
    with open(args.input, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f'WARN: skipping malformed line: {e}', file=sys.stderr)

    if not rows:
        print('FATAL: input has no rows', file=sys.stderr)
        return 2

    if len(rows) > MAX_CALLS:
        print(f'FATAL: {len(rows)} rows exceeds cost cap MAX_CALLS={MAX_CALLS}. '
              f'Bump SONNET_REJUDGE_MAX_CALLS env if you really want it.',
              file=sys.stderr)
        return 3

    results = asyncio.run(main_async(rows, api_key))
    print(summarize(results), file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
