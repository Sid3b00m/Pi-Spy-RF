"""The version is declared once in app/__init__.py; nothing may drift from it."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import __version__

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")


def test_version_is_sane():
    assert VERSION_RE.fullmatch(__version__), __version__


def test_fastapi_app_reports_the_declared_version():
    from app.main import app

    assert app.version == __version__


def test_health_endpoint_reports_the_declared_version(client):
    assert client.get("/api/health").json()["version"] == __version__


def test_no_hardcoded_version_left_in_source():
    """Source must read app.__version__ rather than repeating the literal."""
    offenders = []
    for py in (ROOT / "app").rglob("*.py"):
        if py.name == "__init__.py" and py.parent.name == "app":
            continue
        for num, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(rf"[\"']{re.escape(__version__)}[\"']", line):
                offenders.append(f"{py.relative_to(ROOT)}:{num}")
    assert not offenders, f"hardcoded version literal in {offenders}"


@pytest.mark.parametrize(
    ("doc", "pattern"),
    [
        ("README.md", r"\*\*Version:\*\*\s*(\d+\.\d+\.\d+)"),
        ("docs/platforms.md", r"\"version\":\s*\"(\d+\.\d+\.\d+)\""),
    ],
)
def test_docs_quote_the_current_version(doc, pattern):
    path = ROOT / doc
    found = re.findall(pattern, path.read_text(encoding="utf-8"))
    assert found, f"no version reference found in {doc} - did the format change?"
    stale = sorted({v for v in found if v != __version__})
    assert not stale, f"{doc} mentions {stale}, expected {__version__}"
