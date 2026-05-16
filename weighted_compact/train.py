"""Phase 2 bootstrap training loop.

Train 3-tier classifier (drop/maybe/keep) using bootstrap strategy:
- iter 0: train on gold (36 user labels)
- iter N: predict on pseudo (435 claude_auto), retain agreements, retrain
- stop on convergence (disagreement < 5% or kappa > 0.9 vs prev)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import f1_score, confusion_matrix, cohen_kappa_score

from weighted_compact import config
from weighted_compact.model import WeightedCompactClassifier

WORKDIR = config.workdir()
FEATURES = config.features_path()
MODEL_OUT = config.classifier_path()
BOOTSTRAP_LOG = config.bootstrap_log_path()
DISAGREEMENT_QUEUE = config.disagreement_queue_path()

MAX_ITERS = 5
EPOCHS_PER_ITER = 20
LR = 1e-3
BATCH = 16
SEED = 42
EARLY_STOP_DISAGREE_PCT = 0.05
EARLY_STOP_KAPPA = 0.9


def load_features():
    f = np.load(FEATURES)
    return {
        'windows': torch.from_numpy(f['windows']).float(),
        'labels': torch.from_numpy(f['labels_3tier']).long(),
        'pair_indices': f['pair_indices'],
        'confidence': f['confidence'],
        'labeled_by': f['labeled_by'],
    }


def split_gold_pseudo(data):
    labeled_by = np.array([s.decode() if isinstance(s, bytes) else s for s in data['labeled_by']])
    is_gold = labeled_by == 'user'
    return {
        'gold_idx': np.where(is_gold)[0],
        'pseudo_idx': np.where(~is_gold)[0],
    }


def train_classifier(windows, labels, epochs, lr, batch, device, verbose=False):
    model = WeightedCompactClassifier().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    class_counts = torch.bincount(labels, minlength=3).float()
    inv = 1.0 / (class_counts + 1e-6)
    class_weights = (inv / inv.sum() * 3).to(device)
    loss_fn = nn.CrossEntropyLoss(weight=class_weights)

    ds = TensorDataset(windows.to(device), labels.to(device))
    dl = DataLoader(ds, batch_size=batch, shuffle=True)

    for ep in range(epochs):
        model.train()
        total_loss = 0.0
        for x, y in dl:
            opt.zero_grad()
            logits = model(x)
            loss = loss_fn(logits, y)
            loss.backward()
            opt.step()
            total_loss += loss.item()
        if verbose and (ep == 0 or ep == epochs - 1):
            print(f'    epoch {ep}: loss {total_loss/len(dl):.4f}')
    return model


def evaluate(model, windows, labels, device):
    model.eval()
    with torch.no_grad():
        logits = model(windows.to(device))
        preds = logits.argmax(dim=-1).cpu().numpy()
    actual = labels.numpy()
    macro_f1 = f1_score(actual, preds, average='macro', zero_division=0)
    cm = confusion_matrix(actual, preds, labels=[0, 1, 2])
    return {'macro_f1': float(macro_f1), 'confusion': cm.tolist(), 'preds': preds}


def loo_validate_gold(windows, labels, device, epochs=15):
    n = len(labels)
    correct = 0
    for i in range(n):
        idx = np.delete(np.arange(n), i)
        m = train_classifier(windows[idx], labels[idx], epochs, LR, BATCH, device)
        m.eval()
        with torch.no_grad():
            pred = m(windows[i:i+1].to(device)).argmax(-1).item()
        if pred == labels[i].item():
            correct += 1
    return correct / n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-loo', action='store_true', help='skip leave-one-out CV on gold')
    parser.add_argument('--max-iters', type=int, default=MAX_ITERS)
    args = parser.parse_args()

    torch.manual_seed(SEED)
    np.random.seed(SEED)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'Device: {device}')

    if not FEATURES.exists():
        print(f'ERROR: {FEATURES} not found. Run feature_extract.py first.')
        sys.exit(1)

    data = load_features()
    splits = split_gold_pseudo(data)

    print(f'\nTotal: {len(data["windows"])} | gold: {len(splits["gold_idx"])} | pseudo: {len(splits["pseudo_idx"])}')

    gold_W = data['windows'][splits['gold_idx']]
    gold_y = data['labels'][splits['gold_idx']]
    pseudo_W = data['windows'][splits['pseudo_idx']]
    pseudo_y = data['labels'][splits['pseudo_idx']]

    print(f'Gold label dist: {torch.bincount(gold_y, minlength=3).tolist()} [drop, maybe, keep]')

    if not args.skip_loo:
        print('\nRunning LOO CV on gold (slow)...')
        loo_acc = loo_validate_gold(gold_W, gold_y, device)
        print(f'  LOO accuracy: {loo_acc:.3f}')
        if loo_acc < 0.5:
            print('  WARN: LOO accuracy < 0.5 — overfit risk high or attention pool not learning')
    else:
        loo_acc = None

    train_W = gold_W
    train_y = gold_y
    prev_preds = None
    bootstrap_log = []
    model = None

    for it in range(args.max_iters):
        print(f'\n=== iter {it} ===')
        print(f'  train_set: {len(train_y)} (gold={len(gold_y)} + retained={len(train_y)-len(gold_y)})')

        model = train_classifier(train_W, train_y, EPOCHS_PER_ITER, LR, BATCH, device, verbose=True)

        eval_pseudo = evaluate(model, pseudo_W, pseudo_y, device)
        preds = eval_pseudo['preds']

        eval_gold = evaluate(model, gold_W, gold_y, device)

        retained_mask = preds == pseudo_y.numpy()
        n_retained = int(retained_mask.sum())
        n_disagreed = len(preds) - n_retained
        disagree_pct = n_disagreed / len(preds)

        kappa = float(cohen_kappa_score(preds, prev_preds)) if prev_preds is not None else None

        log = {
            'iter': it,
            'train_size': int(len(train_y)),
            'n_retained': n_retained,
            'n_disagreed': n_disagreed,
            'disagree_pct': float(disagree_pct),
            'kappa_vs_prev': kappa,
            'gold_f1': float(eval_gold['macro_f1']),
            'pseudo_f1': float(eval_pseudo['macro_f1']),
            'confusion_gold': eval_gold['confusion'],
            'loo_acc': float(loo_acc) if loo_acc is not None else None,
        }
        bootstrap_log.append(log)
        print(f'  retained: {n_retained}/{len(preds)} ({(1-disagree_pct)*100:.1f}%)')
        print(f'  gold F1: {eval_gold["macro_f1"]:.3f} | pseudo F1: {eval_pseudo["macro_f1"]:.3f}')
        if kappa is not None:
            print(f'  kappa vs prev: {kappa:.3f}')

        converged = it > 0 and (disagree_pct < EARLY_STOP_DISAGREE_PCT or (kappa is not None and kappa > EARLY_STOP_KAPPA))
        if converged:
            print('  CONVERGED.')
            break

        retained_pseudo_idx = splits['pseudo_idx'][retained_mask]
        combined_idx = np.concatenate([splits['gold_idx'], retained_pseudo_idx])
        train_W = data['windows'][combined_idx]
        train_y = data['labels'][combined_idx]
        prev_preds = preds

    torch.save(model.state_dict(), MODEL_OUT)
    print(f'\nModel saved: {MODEL_OUT}')

    with open(BOOTSTRAP_LOG, 'w') as f:
        for entry in bootstrap_log:
            f.write(json.dumps(entry) + '\n')
    print(f'Log saved: {BOOTSTRAP_LOG}')

    final_disagree_mask = preds != pseudo_y.numpy()
    final_disagree_idx = splits['pseudo_idx'][final_disagree_mask]
    queue_rows = []
    for k, (pi, pp, pl) in enumerate(zip(
        data['pair_indices'][final_disagree_idx].tolist(),
        preds[final_disagree_mask].tolist(),
        pseudo_y[final_disagree_mask].tolist(),
    )):
        queue_rows.append({
            'pair_idx': int(pi),
            'predicted_tier': int(pp),
            'pseudo_tier': int(pl),
            'reason': 'bootstrap_disagreement',
        })
    with open(DISAGREEMENT_QUEUE, 'w') as f:
        for r in queue_rows:
            f.write(json.dumps(r) + '\n')
    print(f'Disagreement queue: {DISAGREEMENT_QUEUE} ({len(queue_rows)} entries)')

    print('\nDone. Phase 2 secondary gate (macro-F1 ≥ 0.55):',
          'PASS' if bootstrap_log[-1]['gold_f1'] >= 0.55 else 'FAIL')


if __name__ == '__main__':
    main()
