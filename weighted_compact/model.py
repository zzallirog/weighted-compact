"""Weighted-Compact 3-tier classifier — scaled dot-product attention over 3-turn window.

Window: (premise_minus_1, premise, correction) → tier (drop / maybe / keep)
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class WeightedCompactClassifier(nn.Module):
    """Attention-pool classifier.

    Query = correction embedding, Keys=Values = all 3 turn embeddings.
    Output: 3-tier logits via softmax(QK^T/√d)·V → MLP head.
    """

    def __init__(self, dim: int = 384, hidden: int = 128, n_classes: int = 3, dropout: float = 0.1):
        super().__init__()
        self.dim = dim
        self.scale = 1.0 / math.sqrt(dim)
        self.W_q = nn.Linear(dim, dim, bias=False)
        self.W_k = nn.Linear(dim, dim, bias=False)
        self.W_v = nn.Linear(dim, dim, bias=False)
        self.head = nn.Sequential(
            nn.LayerNorm(dim),
            nn.Linear(dim, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, n_classes),
        )

    def forward(self, windows: torch.Tensor) -> torch.Tensor:
        """windows: (B, 3, dim) — [premise_minus_1, premise, correction]
        returns: (B, n_classes) logits
        """
        correction = windows[:, 2, :]
        Q = self.W_q(correction).unsqueeze(1)
        K = self.W_k(windows)
        V = self.W_v(windows)
        scores = torch.matmul(Q, K.transpose(-2, -1)) * self.scale
        attn = F.softmax(scores, dim=-1)
        context = torch.matmul(attn, V).squeeze(1)
        return self.head(context)

    @torch.no_grad()
    def predict(self, windows: torch.Tensor, return_confidence: bool = False):
        self.eval()
        logits = self.forward(windows)
        probs = F.softmax(logits, dim=-1)
        labels = probs.argmax(dim=-1)
        if return_confidence:
            conf = probs.max(dim=-1).values
            return labels, conf
        return labels


def aggregate_predictions(probs: torch.Tensor, group_ids: torch.Tensor, strategy: str = 'max') -> tuple:
    """Group N candidate windows per original correction → single prediction.

    probs: (N, n_classes)
    group_ids: (N,) integer correction-IDs
    strategy: 'max' (winner-take-all per class), 'mean' (avg probabilities)
    returns: (unique_group_ids, aggregated_labels, aggregated_confidence)
    """
    unique = torch.unique(group_ids, sorted=False)
    out_labels = []
    out_conf = []
    for g in unique:
        mask = group_ids == g
        sub = probs[mask]
        if strategy == 'max':
            # per-class max across candidates, then argmax
            agg = sub.max(dim=0).values
        elif strategy == 'mean':
            agg = sub.mean(dim=0)
        else:
            raise ValueError(f'unknown strategy: {strategy}')
        out_labels.append(agg.argmax())
        out_conf.append(agg.max())
    return unique, torch.stack(out_labels), torch.stack(out_conf)


if __name__ == '__main__':
    m = WeightedCompactClassifier()
    n_params = sum(p.numel() for p in m.parameters())
    print(f'WeightedCompactClassifier: {n_params:,} params')
    x = torch.randn(4, 3, 384)
    y = m(x)
    print(f'forward: in {tuple(x.shape)} → out {tuple(y.shape)}')
    labels, conf = m.predict(x, return_confidence=True)
    print(f'predict: labels {tuple(labels.shape)} {labels.tolist()}, conf {[f"{c:.3f}" for c in conf.tolist()]}')
    # multi-marker aggregation test
    probs = torch.softmax(torch.randn(6, 3), dim=-1)
    group_ids = torch.tensor([0, 0, 1, 1, 1, 2])
    g, lbls, cf = aggregate_predictions(probs, group_ids, 'max')
    print(f'aggregate: groups {g.tolist()} → labels {lbls.tolist()}')
