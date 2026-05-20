"""Admission gate: classify QA entries by difficulty under current ranker.

Black box:
  вход — easy_k + hard_k + ranker + signal ('judge' default | 'substring').
  выход — dict with 4 buckets:
            trivial      — pass at both k_drop levels → low signal
            impossible   — fail at both → out of pipeline reach
            informative  — pass easy, fail hard → discriminating
            inverted     — fail easy, pass hard → noise
          Plus per_entry breakdown + signal_disagreement_easy counters.
  как открыт — `classify_difficulty` runs `run_eval` twice (once at each k_drop),
          extracts pass-signal via `_pass_signal`, buckets accordingly.

EvoEnv-style difficulty filter (paper 2605.14392). Cost: O(qa_set × 2) LLM
calls — run sparingly. `signal='judge'` is the recommended axis; 'substring'
left in for fast diagnostics.
"""
from .fidelity import run_eval


def _pass_signal(entry, signal):
    """Extract bool pass-signal from a run_eval record.

    signal='judge'     — verdict == 'yes' (recommended; substring врёт
                          on paraphrase ответах)
    signal='substring' — substring_pass (хрупкое: a_truth обычно короткий
                          rare-term, который solver paraphrase'ит)
    """
    if signal == 'judge':
        return entry.get('judge', {}).get('verdict') == 'yes'
    return bool(entry.get('substring_pass'))


def classify_difficulty(easy_k=0.0, hard_k=0.9, ranker='importance',
                        topic_decay=0.5, signal='judge'):
    """Segment recon-QA set by informativeness under compaction.

    Runs eval twice — weak compaction (easy_k, near-full context) and hard
    (hard_k, only top of ranker survives). Pass-signal difference buckets
    each entry:

      trivial      — pass under both: compaction preserves anyway, gate
                     can't distinguish baseline from treatment, gradient ~ 0
      impossible   — fail under both: beyond what the pipeline can recover
                     even with full context
      informative  — easy pass, hard fail: this is where ablation /
                     label-weight feels the choice
      inverted     — easy fail, hard pass: eval noise (LLM stochasticity,
                     lucky short context without distractors)

    Returns dict with counts, bucket indices, both signals per entry for
    disagreement audit.
    """
    easy = run_eval(k_drop=easy_k, ranker=ranker, topic_decay=topic_decay)
    hard = run_eval(k_drop=hard_k, ranker=ranker, topic_decay=topic_decay)
    buckets = {'trivial': [], 'impossible': [], 'informative': [], 'inverted': []}
    per_entry = []
    sub_only_pass = 0
    judge_only_pass = 0
    for i, (e, h) in enumerate(zip(easy, hard)):
        ep, hp = _pass_signal(e, signal), _pass_signal(h, signal)
        if ep and hp:
            buckets['trivial'].append(i)
        elif not ep and not hp:
            buckets['impossible'].append(i)
        elif ep and not hp:
            buckets['informative'].append(i)
        else:
            buckets['inverted'].append(i)
        e_sub = bool(e.get('substring_pass'))
        e_jud = e.get('judge', {}).get('verdict') == 'yes'
        if e_sub and not e_jud:
            sub_only_pass += 1
        if e_jud and not e_sub:
            judge_only_pass += 1
        per_entry.append({
            'idx': i,
            'easy_substring': e_sub,
            'easy_judge_yes': e_jud,
            'hard_substring': bool(h.get('substring_pass')),
            'hard_judge_yes': h.get('judge', {}).get('verdict') == 'yes',
        })
    return {
        'easy_k': easy_k,
        'hard_k': hard_k,
        'ranker': ranker,
        'signal': signal,
        'total': len(easy),
        'counts': {k: len(v) for k, v in buckets.items()},
        'buckets': buckets,
        'signal_disagreement_easy': {
            'substring_only_pass': sub_only_pass,
            'judge_only_pass': judge_only_pass,
        },
        'per_entry': per_entry,
    }
