"""Test isolation: redirect all on-disk state into a per-test temp directory.

The app resolves its database, OUI table and known-MAC file relative to the
repo root, so every test would otherwise share (and mutate) the real data/
directory. Each module imports those helpers by value, so the patches have to
target the importing module rather than app.core.config.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    from app.core import db as db_mod
    from app.core import mac_db as mac_mod

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(db_mod, "db_path", lambda: data_dir / "test.db")
    monkeypatch.setattr(mac_mod, "ROOT", tmp_path)

    db_mod.init_db()
    from app.core.wireless import init_wireless_tables

    init_wireless_tables()
    yield tmp_path


@pytest.fixture(autouse=True)
def reset_singletons():
    """Workers and the device cache are module-level singletons."""
    from app.core import devices as dev_mod

    dev_mod._device_cache = []
    dev_mod._device_cache_at = 0.0
    yield
    from app.core.decode import decode_worker
    from app.core.spectrum import spectrum_worker
    from app.core.wireless import wireless_worker

    for w in (spectrum_worker, decode_worker, wireless_worker):
        try:
            w.stop()
        except Exception:
            pass
    with decode_worker._lock:
        decode_worker._queue.clear()
        decode_worker._history.clear()
        decode_worker._current = None
        decode_worker._error = None


@pytest.fixture
def client(isolated_state):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(isolated_state, monkeypatch):
    """Client with auth switched on via the documented env-var path."""
    monkeypatch.setenv("PI_SPY_PASSWORD", "test-secret")
    from app.core import auth as auth_mod
    from app.core.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.auth, "enabled", True)
    auth_mod._sessions.clear()
    auth_mod.login_limiter._hits.clear()

    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
