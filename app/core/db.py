from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from app.core.config import db_path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_roles (
                device_id TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT,
                freq_hz REAL,
                mode TEXT,
                summary TEXT,
                meta_json TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
            """
        )


def set_device_role(device_id: str, role: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO device_roles(device_id, role, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                role = excluded.role,
                updated_at = excluded.updated_at
            """,
            (device_id, role, now),
        )


def get_device_roles() -> dict[str, str]:
    with get_db() as conn:
        rows = conn.execute("SELECT device_id, role FROM device_roles").fetchall()
    return {r["device_id"]: r["role"] for r in rows}


def add_event(
    kind: str,
    summary: str,
    *,
    source: str | None = None,
    freq_hz: float | None = None,
    mode: str | None = None,
    meta: dict[str, Any] | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO events(ts, kind, source, freq_hz, mode, summary, meta_json)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                kind,
                source,
                freq_hz,
                mode,
                summary,
                json.dumps(meta or {}),
            ),
        )
        return int(cur.lastrowid)


def list_events(limit: int = 50) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, ts, kind, source, freq_hz, mode, summary, meta_json
            FROM events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "ts": r["ts"],
                "kind": r["kind"],
                "source": r["source"],
                "freq_hz": r["freq_hz"],
                "mode": r["mode"],
                "summary": r["summary"],
                "meta": json.loads(r["meta_json"] or "{}"),
            }
        )
    return out