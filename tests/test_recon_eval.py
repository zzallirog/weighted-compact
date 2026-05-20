"""/api/recon/eval accounting (C1 regression).

Pre-v0.2.0-beta.2: the endpoint computed `passed = sum(r.get('pass'))` against
a key `run_eval` never produced — so passed/accuracy were silently 0 for
every caller. Fix reads `judge.verdict` (LLM verdict) and exposes the cheap
`substring_pass` signal separately. `passed` (back-compat key) now reflects
judge verdicts.
"""

from __future__ import annotations

import importlib


def test_recon_eval_uses_judge_verdict_and_exposes_substring(monkeypatch, tmp_path):
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    from weighted_compact import config, recon_qa, tool

    importlib.reload(config)
    importlib.reload(tool)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    config.pairs_path().write_text("")
    tool.reload_state()

    fake_results = [
        {"predicted": "a", "substring_pass": True,
         "judge": {"verdict": "yes", "reasoning": "match", "model": "x"}},
        {"predicted": "b", "substring_pass": False,
         "judge": {"verdict": "yes", "reasoning": "semantic", "model": "x"}},
        {"predicted": "c", "substring_pass": True,
         "judge": {"verdict": "no", "reasoning": "wrong", "model": "x"}},
        {"predicted": "d", "substring_pass": False,
         "judge": {"verdict": "other", "reasoning": "ambiguous", "model": "x"}},
        # judge field absent — must not crash; counted as not-yes.
        {"predicted": "e", "substring_pass": False},
    ]

    monkeypatch.setattr(
        recon_qa, "run_eval",
        lambda **kwargs: fake_results,
    )
    # tool.py captured `recon_qa` at import; the attribute swap above lives
    # on the module recon_qa, and tool.py calls `recon_qa.run_eval` via
    # attribute access, so the patched version is what fires.

    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.post(
            "/api/recon/eval",
            headers={
                "Host": "localhost",
                "Authorization": f"Bearer {tool.AUTH_TOKEN}",
            },
            json={"k_drop": 0.5, "ranker": "importance", "topic_decay": 0.5},
        )
        assert r.status_code == 200, r.text
        body = r.json()

    assert body["ok"] is True
    assert body["total"] == 5
    # 2 verdict='yes' entries → passed (back-compat) + passed_judge.
    assert body["passed"] == 2
    assert body["passed_judge"] == 2
    # 2 substring_pass=True entries (independent of judge).
    assert body["passed_substring"] == 2
    # accuracy is judge-based, not substring-based (C1: substring was the trap).
    assert body["accuracy"] == 2 / 5


def test_recon_eval_empty_results(monkeypatch, tmp_path):
    """Empty corpus: accuracy stays 0.0, no zero-division."""
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    from weighted_compact import config, recon_qa, tool

    importlib.reload(config)
    importlib.reload(tool)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    config.pairs_path().write_text("")
    tool.reload_state()

    monkeypatch.setattr(recon_qa, "run_eval", lambda **kwargs: [])

    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.post(
            "/api/recon/eval",
            headers={
                "Host": "localhost",
                "Authorization": f"Bearer {tool.AUTH_TOKEN}",
            },
            json={},
        )
        assert r.status_code == 200, r.text
        body = r.json()

    assert body["total"] == 0
    assert body["passed"] == 0
    assert body["passed_judge"] == 0
    assert body["passed_substring"] == 0
    assert body["accuracy"] == 0.0
