"""Reconstruction-QA eval loop + qa_set journal accessors.

Black box:
  input — k_drop, ranker, topic_decay (defaults preserve old behavior).
  output — list of result dicts per QA entry: {predicted, substring_pass, judge,
          context_chars} merged with the entry. Persists nothing — caller
          owns the journal.
  entry — `run_eval` is the entry point; iterates over `load_qa_set()`
          and calls `build_compacted_context` → `ask_ollama` → `score` +
          `llm_judge`. qa_set helpers (load/used/sample/save_qa_entry) live
          here as the natural neighbours of run_eval.

This module is the orchestrator: it imports from context/generator/judge and
glues them together. The four black boxes themselves are pure.

Pre-flight: `run_eval` probes ollama once before the per-entry loop. If
ollama is unreachable, the judge silently returns `other` verdicts and
the eval inflates `judge_yes_fraction` against bogus denominators —
fail loud at the top instead. Bypass with `preflight=False` only when
deliberately exercising the failure mode.
"""
import datetime
import json
import random
from collections import Counter
from urllib.parse import urlparse, urlunparse

import click

from ._constants import JUDGE_MODEL, MODEL, OLLAMA_URL, RECON_SET, _requests
from .context import (
    build_compacted_context,
    load_baseline_random,
    load_baseline_recency,
    load_rem_decay,
    load_density,
    load_importance,
    load_pairs,
    load_topic_map,
)
from .generator import ask_ollama
from .judge import llm_judge, score


def _ollama_base_url() -> str:
    """Derive the ollama base URL from OLLAMA_URL (which points at /api/generate).

    Returns the scheme://host:port root without any path so we can hit /api/tags.
    """
    parsed = urlparse(OLLAMA_URL)
    return urlunparse((parsed.scheme, parsed.netloc, '', '', '', ''))


def _preflight_ollama() -> None:
    """Probe ollama once before the eval loop; raise ClickException on failure.

    Two checks:
      1. `GET <base>/api/tags` with 2s timeout — proves the daemon is up.
      2. The configured `MODEL` and `JUDGE_MODEL` are in the installed list.

    Either failure raises `click.ClickException` with a directive the user
    can paste into a shell. The judge silently returning `other` when ollama
    is down would otherwise inflate `judge_yes_fraction` against a bogus
    denominator (judge=='yes' rows / all rows).
    """
    base = _ollama_base_url()
    tags_url = f"{base}/api/tags"
    try:
        r = _requests().get(tags_url, timeout=2)
    except Exception as exc:
        raise click.ClickException(
            f"ollama is not reachable at {base} ({exc}). "
            f"Start it with: ollama serve"
        ) from exc
    if r.status_code != 200:
        raise click.ClickException(
            f"ollama at {base} returned HTTP {r.status_code} for /api/tags. "
            f"Start it with: ollama serve"
        )
    try:
        installed = {m.get('name', '') for m in r.json().get('models', [])}
    except (ValueError, AttributeError) as exc:
        raise click.ClickException(
            f"ollama /api/tags response is not valid JSON ({exc}). "
            f"Restart with: ollama serve"
        ) from exc
    # Tags may carry version suffixes (e.g. `qwen2.5:7b` vs `qwen2.5:7b-instruct`).
    # Accept exact match OR prefix match on the configured name.
    def _has_model(want: str) -> bool:
        if want in installed:
            return True
        return any(name.startswith(want) for name in installed if name)

    for label, model in (('MODEL', MODEL), ('JUDGE_MODEL', JUDGE_MODEL)):
        if not _has_model(model):
            raise click.ClickException(
                f"{label}={model!r} is not installed in ollama. "
                f"Pull it with: ollama pull {model}"
            )


def load_qa_set():
    """Read recon_qa_set.jsonl, return list of entry dicts.

    Tolerant to corrupted lines: this file is human-readable and frequently
    edited by hand, so an unterminated last line or a saved-while-writing
    partial record must not blow up downstream eval.
    """
    if not RECON_SET.exists():
        return []
    out = []
    with open(RECON_SET, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def used_pair_idxs():
    return {e['source_pair_idx'] for e in load_qa_set()}


def sample_for_build(pairs, used_idxs):
    """Pick a random pair_idx not in used_idxs, prefer sessions with >=3 pairs."""
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
    """Append entry to recon_qa_set.jsonl; created_at stamped here."""
    entry['created_at'] = datetime.datetime.now().isoformat()
    with open(RECON_SET, 'a') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _load_cosine_ranker():
    """Lazy: import only when cosine is requested (pulls sentence-transformers)."""
    from weighted_compact.baselines.cosine_ranker import CosineRanker
    return CosineRanker()


def _load_bm25_ranker():
    """Lazy: import only when bm25 is requested (pulls rank-bm25)."""
    from weighted_compact.baselines.bm25_ranker import Bm25Ranker
    return Bm25Ranker()


def _load_compact_qwen():
    """Lazy: local Ollama qwen2.5:7b summarizer."""
    from weighted_compact.baselines.compact_simulator import build_qwen
    return build_qwen()


def _load_compact_sonnet():
    """Lazy: Anthropic API Sonnet summarizer (requires ANTHROPIC_API_KEY)."""
    from weighted_compact.baselines.compact_simulator import build_sonnet
    return build_sonnet()


# Ship the eight built-in rankers through the public registry. External
# packages register their own via `weighted_compact.ranker.register(...)`
# — the registry is the single source of truth; `_RANKER_LOADERS` below
# is a thin compatibility view that points at it.
from weighted_compact.ranker import RANKER_REGISTRY

RANKER_REGISTRY.add(
    'importance', load_importance,
    description='Seven-signal mixture (misstep+density+labels+spans). Default.',
    query_aware=False,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'density', load_density,
    description='Legacy fallback — mean of 16 density features only.',
    query_aware=False,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'random', load_baseline_random,
    description='Phase 1 baseline: uniform random scores per pair_idx (seeded).',
    query_aware=False,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'recency', load_baseline_recency,
    description='Phase 1 baseline: rank by within-session position (most recent wins).',
    query_aware=False,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'cosine', _load_cosine_ranker,
    description='Phase 2 baseline: e5 dense cosine similarity to the query.',
    requires_extras=('baselines',),
    query_aware=True,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'bm25', _load_bm25_ranker,
    description='Phase 2 baseline: BM25 lexical relevance to the query.',
    requires_extras=('baselines',),
    query_aware=True,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'compact_qwen', _load_compact_qwen,
    description='/compact-style: local Ollama qwen2.5:7b summary replaces selection.',
    query_aware=True,
    since_version='0.1.0',
)
RANKER_REGISTRY.add(
    'compact_sonnet', _load_compact_sonnet,
    description='/compact-style: Anthropic API Sonnet summary (requires API key).',
    requires_extras=('baselines-cloud',),
    query_aware=True,
    since_version='0.1.0',
)

# Backward-compatible dict view: pre-existing call sites
# (cli.baseline_run_all, tests) import `_RANKER_LOADERS` from this module.
# Keep it as a live mapping name → loader so those still work unchanged.
# This is intentionally a property of the registry, not a snapshot — if a
# plugin registers a new ranker after import, it shows up here too.
class _RankerLoadersView:
    """dict-like view over RANKER_REGISTRY exposing just name → loader.

    Preserves the pre-registry call sites (`name in _RANKER_LOADERS`,
    `list(_RANKER_LOADERS)`, `_RANKER_LOADERS[name]`) without forcing a
    static snapshot. Read-only.
    """
    def __contains__(self, key):
        return key in RANKER_REGISTRY
    def __getitem__(self, key):
        return RANKER_REGISTRY[key].loader
    def __iter__(self):
        return iter(RANKER_REGISTRY)
    def __len__(self):
        return len(RANKER_REGISTRY)
    def get(self, key, default=None):
        spec = RANKER_REGISTRY.get(key)
        return spec.loader if spec is not None else default
    def keys(self):
        return RANKER_REGISTRY.keys()
    def values(self):
        return [s.loader for s in RANKER_REGISTRY.values()]
    def items(self):
        return [(n, s.loader) for n, s in RANKER_REGISTRY.items()]

_RANKER_LOADERS = _RankerLoadersView()


def run_eval(k_drop=0.5, ranker='importance', topic_decay=0.5, rem_decay=False,
             preflight=True):
    """Evaluate all Q&A entries: build context, query ollama, score with substring + LLM judge.

    ranker: one of the registered ranker names —
        - 'importance' (Phase 4C mixture, default static)
        - 'density' (legacy fallback static)
        - 'random' / 'recency' (Phase 1 baseline static)
        - 'cosine' / 'bm25' (Phase 2 baseline, query-aware — context
          per Q rather than fixed per source_pair)
        New rankers register via :mod:`weighted_compact.ranker` —
        ``@register("name", ...)`` or ``RANKER_REGISTRY.add(...)``.
        See ``docs/extension-recipe.md`` for a worked example.
    topic_decay: float ∈ (0, 1]. 1.0 = disabled; 0.5 = halve per topic step;
        0.0 = drop everything outside current topic.
    rem_decay: bool. When True, load `rem_decay.npz` (produced by
        `weighted-compact rem-pass`) and multiply each candidate score by its
        wall-clock half-life factor before ranking. Silently no-ops if the
        REM pass has never been run.
    preflight: bool. When True (default), probe ollama once at the top
        and raise `click.ClickException` if unreachable or required models
        are missing. Pass False only to deliberately exercise the silent-
        failure mode (e.g. for reproducing the historical inflation bug).

    Fairness note: static rankers see same context for all Qs under a
    source_pair; query-aware rankers see per-Q context. This asymmetry
    is the paradigm comparison the baseline table exposes.
    """
    if preflight:
        _preflight_ollama()
    pairs = load_pairs()
    loader = _RANKER_LOADERS.get(ranker)
    if loader is None:
        raise ValueError(
            f'unknown ranker {ranker!r}; '
            f'known: {sorted(_RANKER_LOADERS)}',
        )
    scoring = loader()  # dict (static), callable (query-aware), or summarizer
    is_compact_bypass = getattr(scoring, 'is_compact_bypass', False)
    topic_map = load_topic_map() if (topic_decay < 1.0 and not is_compact_bypass) else None
    rem_decay_map = load_rem_decay() if (rem_decay and not is_compact_bypass) else None
    qa_set = load_qa_set()
    results = []
    for entry in qa_set:
        if is_compact_bypass:
            # /compact-style: bypass pair selection, replace context with
            # full-history LLM summary. k_drop and topic_decay are ignored
            # — the summary IS the context.
            ctx = scoring.summarize_excluding(
                entry['source_pair_idx'], pairs, query=entry.get('q'),
            )
        else:
            ctx = build_compacted_context(
                entry['source_pair_idx'], pairs, scoring, k_drop,
                topic_decay=topic_decay, topic_map=topic_map,
                query=entry.get('q'),
                rem_decay_map=rem_decay_map,
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
        src_pair = (
            pairs[entry['source_pair_idx']]
            if 0 <= entry['source_pair_idx'] < len(pairs)
            else None
        )
        judge = llm_judge(entry['q'], entry['a_truth'], pred, source_pair=src_pair)
        results.append({
            **entry,
            'predicted': pred,
            'substring_pass': sub_pass,
            'judge': judge,
            'context_chars': len(ctx),
        })
    return results
