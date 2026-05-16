#!/usr/bin/env python3
"""Weighted-Compact Phase 1 — interactive labeling CLI.

Usage: python3 label_pairs.py
- Resumable: quit with q anytime, progress saved per-label
- Default goal: 100 labels
- Calibration: 3 demo pairs on first run
"""
import json
import random
import sys

from weighted_compact import config
from weighted_compact.config import LABEL_KEY_MAP as KEY_MAP

WORKDIR = config.workdir()
PAIRS = config.pairs_path()
LABELS = config.labels_path()
QUEUE = config.queue_path()
TARGET = 100

# Synthetic calibration pairs. NOT real conversation excerpts — these are
# illustrative examples showing the four tier semantics. The real labeler
# bootstrap pulls live pairs from ~/.claude/projects/.
CALIBRATION = [
    {
        'premise': "I'll set the timeout to 30 seconds, which should cover most cases.",
        'correction': "no, our SLA requires 8 seconds — anything above 10 is a hard fail.",
        'marker': 'regex_neg "no"',
        'answer': 'k',
        'why': 'Direct factual correction. The assistant proposed a wrong number; the user supplied the correct constraint. Premise is load-bearing — without it future turns would inherit the wrong timeout. Keep verbatim.',
    },
    {
        'premise': 'We could extend the dashboard with cache hit ratio and burst-event metrics. Want me to scaffold that?',
        'correction': 'interesting (mark — later) but not the priority right now.',
        'marker': 'explicit_tag "(mark — later)"',
        'answer': 'm',
        'why': 'User explicitly defers the idea. Premise is relevant — it captures a proposed feature — but not peak importance. Cluster gist is enough. Keep as "maybe".',
    },
    {
        'premise': 'Tell me more about how the analysis went.',
        'correction': 'maybe you would like the idea of building a session-narrative module that surfaces the highlights — look at how the philosophy discussion turned out.',
        'marker': 'regex_pos "look"',
        'answer': 'x',
        'why': 'False positive. "look" here is a discourse particle ("for example, look at how X went"), not a correction marker. This pair should be excluded — the regex matched on the surface form, not the meaning. Mark as "x".',
    },
]


def clear():
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()


def load_pairs():
    with open(PAIRS) as f:
        return [json.loads(line) for line in f]


def load_labels():
    if not LABELS.exists():
        return set()
    seen = set()
    with open(LABELS) as f:
        for line in f:
            d = json.loads(line)
            seen.add(d['pair_idx'])
    return seen


def trim(text, n=1500):
    text = text.replace('\n\n', '\n').strip()
    if len(text) <= n:
        return text
    return text[:n] + f'\n... [+{len(text)-n} chars truncated]'


def show_pair(pair, count, total_to_go, idx, source=None):
    clear()
    bar = '═' * 76
    print(bar)
    print(f'  Pair {count} of {total_to_go}     [global idx {idx}]     session {pair["session_id"][:8]}')
    print(f'  Marker: [{pair["marker_type"]}] "{pair["marker_match"]}"')
    if source:
        print(f'  Source: {source}')
    print(bar)
    print()
    print('PREMISE (что assistant сказал до):')
    print('─' * 76)
    print(trim(pair['premise_text']))
    print()
    print('CORRECTION (твой ответ на это):')
    print('─' * 76)
    print(trim(pair['correction_text']))
    print()
    print('─' * 76)
    print('  k = KEEP        premise is load-bearing — ground truth, important fact')
    print('  m = MAYBE       mid-importance — a gist is enough')
    print('  s = SKIP        scaffolding/filler — a pointer is enough')
    print('  x = FALSE POS   this pair is not a correction at all (regex misfire)')
    print('  q = QUIT        save and exit')
    print('  ? = repeat help')
    print()


def run_calibration():
    clear()
    print('═' * 76)
    print('  CALIBRATION (3 examples with correct answers)')
    print('═' * 76)
    print()
    print('Goal: show how to discriminate tiers. These 3 are not saved to the dataset.')
    print()
    input('[Enter to start]')

    for i, ex in enumerate(CALIBRATION):
        clear()
        bar = '═' * 76
        print(bar)
        print(f'  CALIBRATION {i+1}/3     marker: {ex["marker"]}')
        print(bar)
        print()
        print('PREMISE:')
        print('─' * 76)
        print(ex['premise'])
        print()
        print('CORRECTION:')
        print('─' * 76)
        print(ex['correction'])
        print()
        print('─' * 76)
        print(f'  Correct answer: {ex["answer"].upper()}')
        print()
        print('Why:')
        for line in ex['why'].split('. '):
            print(f'  {line.strip()}{"." if not line.endswith(".") else ""}')
        print()
        input('[Enter to continue]')


def save_label(idx, label, pair, labeled_via=None):
    rec = {
        'pair_idx': idx,
        'label': label,
        'marker_match': pair['marker_match'],
        'marker_type': pair['marker_type'],
        'session_id': pair['session_id'],
    }
    if labeled_via:
        rec['labeled_via'] = labeled_via
    with open(LABELS, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def main():
    use_queue = '--queue' in sys.argv

    if not PAIRS.exists():
        print(f'error: {PAIRS} not found. Run extract_pairs.py first.')
        sys.exit(1)

    pairs = load_pairs()
    labeled = load_labels()

    if use_queue and QUEUE.exists():
        with open(QUEUE) as f:
            queue_entries = [json.loads(line) for line in f if line.strip()]
        # Filter already-labeled; keep source metadata alongside pair data
        pairs_by_idx = {i: p for i, p in enumerate(pairs)}
        unlabeled = []
        for entry in queue_entries:
            idx = entry['pair_idx']
            if idx not in labeled and idx in pairs_by_idx:
                p = dict(pairs_by_idx[idx])
                p['_queue_source'] = entry.get('source')
                unlabeled.append((idx, p))
    else:
        if use_queue:
            print('  [--queue] queue.jsonl not found, falling back to random shuffle')
        unlabeled = [(i, p) for i, p in enumerate(pairs) if i not in labeled]
        random.seed(42)
        random.shuffle(unlabeled)

    clear()
    print('═' * 76)
    print('  Weighted-Compact Phase 1 — manual labeling')
    print('═' * 76)
    print()
    print(f'  Corpus total:       {len(pairs)} pairs')
    print(f'  Already labeled:    {len(labeled)}')
    print(f'  Remaining to goal:  {max(0, TARGET - len(labeled))}')
    print()

    first_run = len(labeled) == 0
    if first_run:
        print('First run — starting with 3 calibration examples (not saved).')
        print()
        input('[Enter to start calibration]')
        run_calibration()

    remaining = TARGET - len(labeled)
    if remaining <= 0:
        clear()
        print(f'✓ Already labeled {len(labeled)} pairs. Phase 1 corpus is ready.')
        print(f'  labels.jsonl: {LABELS}')
        return

    clear()
    print(f"Today's target: {min(remaining, len(unlabeled))} pairs.")
    print("Tip: 'q' saves and exits — you can resume any time; progress is per-label.")
    print()
    input('[Enter to start labeling]')

    done_this_run = 0
    try:
        for idx, pair in unlabeled[:remaining]:
            while True:
                show_pair(pair, len(labeled) + done_this_run + 1, TARGET, idx)
                ans = input('> ').strip().lower()
                if ans == 'q':
                    raise KeyboardInterrupt
                if ans == '?':
                    continue
                if ans not in KEY_MAP:
                    print(f'  unknown: "{ans}" — use k/m/s/x/q/?')
                    input('  [Enter retry]')
                    continue
                save_label(idx, KEY_MAP[ans], pair)
                done_this_run += 1
                break
    except (KeyboardInterrupt, EOFError):
        pass

    clear()
    total = len(labeled) + done_this_run
    print(f'Saved. This session: {done_this_run}. Total: {total} / {TARGET}.')
    if total >= TARGET:
        print(f'✓ Goal of {TARGET} reached. Phase 2 is unblocked.')
    else:
        print(f'Remaining: {TARGET - total}. Run the script again when you have time.')


if __name__ == '__main__':
    main()
