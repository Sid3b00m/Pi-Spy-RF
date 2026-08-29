"""Login, session handling, and the auth middleware gate."""
from __future__ import annotations

from app.core import auth as auth_mod
from app.core.auth import (
    COOKIE,
    create_session,
    drop_session,
    public_path,
    session_valid,
    verify_login,
)


def test_auth_disabled_by_default(client):
    assert client.get("/").status_code == 200


def test_public_paths():
    assert public_path("/login")
    assert public_path("/static/js/app.js")
    assert public_path("/api/health")
    assert not public_path("/")
    assert not public_path("/api/devices")


def test_session_lifecycle():
    token = create_session()
    assert session_valid(token)
    drop_session(token)
    assert not session_valid(token)


def test_session_rejects_unknown_and_empty_tokens():
    assert not session_valid(None)
    assert not session_valid("")
    assert not session_valid("forged-token")


def test_expired_session_rejected(monkeypatch):
    from datetime import datetime, timedelta, timezone

    token = create_session()
    auth_mod._sessions[token] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not session_valid(token)


def test_expired_sessions_are_reaped(monkeypatch):
    """Sessions live in a module dict; stale tokens must not accumulate forever."""
    from datetime import datetime, timedelta, timezone

    auth_mod._sessions.clear()
    for _ in range(50):
        tok = create_session()
        auth_mod._sessions[tok] = datetime.now(timezone.utc) - timedelta(hours=1)
    create_session()
    assert len(auth_mod._sessions) < 51, (
        f"{len(auth_mod._sessions)} sessions retained; expired entries are only "
        "evicted when that exact token is presented again"
    )


def test_verify_login_requires_password_configured(monkeypatch):
    monkeypatch.delenv("PI_SPY_PASSWORD", raising=False)
    from app.core.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.auth, "password", "")
    assert not verify_login("ops", "anything")


def test_verify_login_accepts_correct_and_rejects_wrong(monkeypatch):
    monkeypatch.setenv("PI_SPY_PASSWORD", "s3cret")
    auth_mod.login_limiter._hits.clear()
    assert verify_login("ops", "s3cret")
    assert not verify_login("ops", "wrong")
    assert not verify_login("intruder", "s3cret")


def test_login_rate_limit_blocks_brute_force(monkeypatch):
    monkeypatch.setenv("PI_SPY_PASSWORD", "s3cret")
    auth_mod.login_limiter._hits.clear()
    for _ in range(auth_mod.login_limiter.max_attempts):
        verify_login("ops", "wrong", client_key="9.9.9.9")
    assert not verify_login("ops", "s3cret", client_key="9.9.9.9"), (
        "correct password should still be refused while rate-limited"
    )


def test_protected_page_redirects_when_unauthenticated(auth_client):
    resp = auth_client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


def test_protected_api_returns_401_not_redirect(auth_client):
    resp = auth_client.get("/api/devices", follow_redirects=False)
    assert resp.status_code == 401


def test_health_stays_public_when_auth_on(auth_client):
    assert auth_client.get("/api/health").status_code == 200


def test_login_flow_grants_access(auth_client):
    resp = auth_client.post(
        "/login",
        data={"username": "ops", "password": "test-secret"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert COOKIE in resp.cookies or auth_client.cookies.get(COOKIE)
    assert auth_client.get("/").status_code == 200


def test_bad_login_does_not_grant_access(auth_client):
    resp = auth_client.post(
        "/login",
        data={"username": "ops", "password": "nope"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error" in resp.headers["location"]
    assert auth_client.get("/", follow_redirects=False).status_code == 302


def test_session_cookie_is_httponly(auth_client):
    resp = auth_client.post(
        "/login",
        data={"username": "ops", "password": "test-secret"},
        follow_redirects=False,
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "httponly" in set_cookie.lower()
    assert "samesite" in set_cookie.lower()


def test_logout_revokes_session(auth_client):
    auth_client.post("/login", data={"username": "ops", "password": "test-secret"})
    assert auth_client.get("/").status_code == 200
    auth_client.get("/logout", follow_redirects=False)
    assert auth_client.get("/", follow_redirects=False).status_code == 302


def test_security_headers_present_on_redirects(auth_client):
    resp = auth_client.get("/", follow_redirects=False)
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "default-src 'self'" in resp.headers.get("Content-Security-Policy", "")
