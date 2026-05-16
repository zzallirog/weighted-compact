#!/usr/bin/env python3
"""Weighted-Compact Phase 1 — interactive labeling CLI.

Usage: python3 label_pairs.py
- Resumable: quit with q anytime, progress saved per-label
- Default goal: 100 labels
- Calibration: 3 demo pairs on first run
"""
import json
import os
import random
import sys

from weighted_compact import config

WORKDIR = config.workdir()
PAIRS = config.pairs_path()
LABELS = config.labels_path()
QUEUE = config.queue_path()
TARGET = 100

KEY_MAP = {
    'k': 'keep',
    'm': 'maybe',
    's': 'skip',
    'x': 'false_positive',
}

CALIBRATION = [
    {
        'premise': 'Думаю ты родился где-то в начале 1999 года, судя по нумерологии. Это даёт определённую конфигурацию карт.',
        'correction': 'не то, декабрь 28 1998 примерно в ночь 3-5',
        'marker': 'regex_neg "не то"',
        'answer': 'k',
        'why': 'Прямая фактическая коррекция. Premise (assistant\'s guess) был неверный, correction предоставляет ground truth. Premise — load-bearing: без него я бы продолжала строить выводы на неверной дате. Сохраняем verbatim.',
    },
    {
        'premise': 'Можем расширить дашборд метриками cache hit ratio и сессионных burst-ивентов. Хочешь?',
        'correction': 'интересно (маркер - подумать) но сейчас не до этого',
        'marker': 'explicit_tag "(маркер - подумать)"',
        'answer': 'm',
        'why': 'Юзер явно помечает как deferred. Premise релевантный — это была предложенная фича — но не peak importance. Cluster gist достаточно. Сохраняем как "maybe".',
    },
    {
        'premise': 'Расскажи подробнее как тебе разговор о философии и физике',
        'correction': 'а может быть тебе понравится идея создать себе улучшенную версию получение нарратива из любой сессии? и мы бы помечали более важные — как вот общение про философию и физику. хороший был диалог.',
        'marker': 'regex_pos "вот"',
        'answer': 'x',
        'why': 'False positive. "вот" здесь — discourse particle ("например, для иллюстрации"), не correction marker. Эта пара не должна быть в датасете — regex поймал по букве, не по смыслу. Помечаем "x" чтобы исключить.',
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
    print('  k = KEEP        premise — load-bearing, ground truth, важный facto')
    print('  m = MAYBE       средняя важность — gist подойдёт')
    print('  s = SKIP        scaffolding/filler — pointer-only хватит')
    print('  x = FALSE POS   эта пара вообще не correction (regex попал ложно)')
    print('  q = QUIT        сохранить и выйти')
    print('  ? = repeat help')
    print()


def run_calibration():
    clear()
    print('═' * 76)
    print('  CALIBRATION (3 примера с правильными ответами)')
    print('═' * 76)
    print()
    print('Цель: показать как различать tiers. Эти 3 не сохраняются в датасете.')
    print()
    input('[Enter чтобы начать]')

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
        print(f'  Правильный ответ: {ex["answer"].upper()}')
        print()
        print('Почему:')
        for line in ex['why'].split('. '):
            print(f'  {line.strip()}{"." if not line.endswith(".") else ""}')
        print()
        input('[Enter дальше]')


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
        labeled_via = 'queue'
    else:
        if use_queue:
            print(f'  [--queue] queue.jsonl not found, falling back to random shuffle')
        unlabeled = [(i, p) for i, p in enumerate(pairs) if i not in labeled]
        random.seed(42)
        random.shuffle(unlabeled)
        labeled_via = None

    clear()
    print('═' * 76)
    print('  Weighted-Compact Phase 1 — manual labeling')
    print('═' * 76)
    print()
    print(f'  Корпус всего:       {len(pairs)} пар')
    print(f'  Уже размечено:      {len(labeled)}')
    print(f'  Осталось до цели:   {max(0, TARGET - len(labeled))}')
    print()

    first_run = len(labeled) == 0
    if first_run:
        print('Первый запуск — стартуем с 3 calibration примеров (не сохраняются).')
        print()
        input('[Enter чтобы начать calibration]')
        run_calibration()

    remaining = TARGET - len(labeled)
    if remaining <= 0:
        clear()
        print(f'✓ Уже размечено {len(labeled)} пар. Phase 1 корпус готов.')
        print(f'  labels.jsonl: {LABELS}')
        return

    clear()
    print(f'Цель сегодня: {min(remaining, len(unlabeled))} пар.')
    print(f'Tip: q сохраняет и выходит — можешь возвращаться, прогресс по каждому label\'у.')
    print()
    input('[Enter чтобы начать labeling]')

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
    print(f'Сохранено. Этой сессией: {done_this_run}. Всего: {total} / {TARGET}.')
    if total >= TARGET:
        print(f'✓ Цель {TARGET} достигнута. Можешь стартовать Phase 2.')
    else:
        print(f'Осталось: {TARGET - total}. Запусти script снова когда будет время.')


if __name__ == '__main__':
    main()
