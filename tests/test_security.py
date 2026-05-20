"""Security middlewares — regression-guard for V1 + V2 (review 2026-05-20).

V1 — Host-header allowlist: non-loopback Host: → 403 (DNS-rebinding defence).
V2 — Bearer token on /api/*: missing/wrong → 401, correct → 200. HTML pages
     (non-/api/) carry no bearer check (token is delivered via `?t=` on first
     load, then stripped).

Token-on-disk hygiene: $XDG_RUNTIME_DIR/weighted-compact/token created with
mode 0600; existing token re-read on next import (not regenerated).
"""

from __future__ import annotations

import importlib
import stat


def _reload_with_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("WEIGHTED_COMPACT_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("WEIGHTED_COMPACT_CLAUDE_SOURCES", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    from weighted_compact import config, tool

    importlib.reload(config)
    importlib.reload(tool)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    config.pairs_path().write_text("")
    tool.reload_state()
    return tool


def test_token_file_created_with_0600(monkeypatch, tmp_path):
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    tok_path = tool._runtime_dir() / "token"
    assert tok_path.exists(), "token file must be created at import"
    mode = stat.S_IMODE(tok_path.stat().st_mode)
    assert mode == 0o600, f"token must be 0600, got {oct(mode)}"
    assert tok_path.read_text().strip() == tool.AUTH_TOKEN
    assert len(tool.AUTH_TOKEN) >= 32, "token_urlsafe(32) → ≥ 32 chars"


def test_token_persisted_across_reload(monkeypatch, tmp_path):
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    first = tool.AUTH_TOKEN

    from weighted_compact import tool as tool_mod
    importlib.reload(tool_mod)
    assert tool_mod.AUTH_TOKEN == first, "existing token must be re-read, not regenerated"


def test_host_header_allowlist_rejects_non_loopback(monkeypatch, tmp_path):
    """V1 — non-loopback Host rejected. The bearer middleware runs in front
    (last `@app.middleware` decorator = outermost), so we attach a valid
    token; we want to assert the V1 check still fires past V2."""
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.get(
            "/api/markers",
            headers={
                "Host": "evil.example",
                "Authorization": f"Bearer {tool.AUTH_TOKEN}",
            },
        )
        assert r.status_code == 403
        assert r.json()["error"] == "non-loopback host rejected"


def test_host_header_allowlist_accepts_loopback(monkeypatch, tmp_path):
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.get(
            "/api/markers",
            headers={
                "Host": "127.0.0.1",
                "Authorization": f"Bearer {tool.AUTH_TOKEN}",
            },
        )
        assert r.status_code == 200, r.text


def test_api_requires_bearer_token(monkeypatch, tmp_path):
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.get("/api/markers", headers={"Host": "localhost"})
        assert r.status_code == 401
        assert r.json()["error"] == "missing or invalid token"


def test_api_rejects_wrong_bearer_token(monkeypatch, tmp_path):
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.get(
            "/api/markers",
            headers={
                "Host": "localhost",
                "Authorization": "Bearer not-the-real-token",
            },
        )
        assert r.status_code == 401


def test_html_root_does_not_require_bearer(monkeypatch, tmp_path):
    """The HTML page receives the token via `?t=` and strips it; the GET on
    `/` itself must not be blocked by V2 (otherwise the page can never
    bootstrap)."""
    tool = _reload_with_runtime(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    with TestClient(tool.app) as client:
        r = client.get("/", headers={"Host": "localhost"})
        # V2 only guards /api/*; root may 200 or 404 depending on route table,
        # but it must NOT 401.
        assert r.status_code != 401
