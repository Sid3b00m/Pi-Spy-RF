from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.routes import router as api_router
from app.core.security import SECURITY_HEADERS
from app.core.auth import (
    COOKIE,
    attach_session_cookie,
    auth_enabled,
    create_session,
    drop_session,
    public_path,
    session_valid,
    verify_login,
)
from app.core.bandplan import list_bands
from app.core.config import ROOT, get_config
from app.core.db import init_db, list_events
from app.core.decode import decode_worker
from app.core.devices import VALID_ROLES, host_info, list_radio_devices, list_tools
from app.core.mac_db import ensure_mini_oui, load_known_macs
from app.core.spectrum import spectrum_worker
from app.core.wireless import init_wireless_tables, list_wireless, wireless_worker

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    init_db()
    init_wireless_tables()
    ensure_mini_oui()
    yield


app = FastAPI(title="Pi-Spy-RF", version=__version__, lifespan=lifespan)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled() or public_path(request.url.path):
            return await call_next(request)
        token = request.cookies.get(COOKIE)
        if session_valid(token):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": False, "error": "auth required"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


app.add_middleware(AuthMiddleware)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


app.add_middleware(SecurityHeadersMiddleware)

# The public receiver directory alone is ~700 kB of JSON, and the waterfall
# payloads are not small either. Added last so it wraps everything.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    return templates.TemplateResponse(request, "login.html", {"error": error, "auth_on": auth_enabled()})


@app.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if not auth_enabled():
        return RedirectResponse("/", status_code=302)
    client = request.client.host if request.client else "unknown"
    if not verify_login(username, password, client_key=client):
        return RedirectResponse("/login?error=1", status_code=302)
    token = create_session()
    resp = RedirectResponse("/", status_code=302)
    attach_session_cookie(resp, token)
    return resp


@app.get("/logout")
def logout(request: Request):
    drop_session(request.cookies.get(COOKIE))
    resp = RedirectResponse("/login" if auth_enabled() else "/", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    ctx = {
        "host": host_info(),
        "devices": list_radio_devices(),
        "roles": list(VALID_ROLES),
        "tools": list_tools(),
        "known_macs": load_known_macs(),
        "bands": list_bands(),
        "events": list_events(30),
        "spectrum": spectrum_worker.status(),
        "decode": decode_worker.status(),
        "wireless": wireless_worker.status(),
        "wifi_devices": list_wireless("wifi", 50),
        "bt_devices": list_wireless("bluetooth", 50),
        "auth_on": auth_enabled(),
    }
    return templates.TemplateResponse(request, "index.html", ctx)


def main() -> None:
    import logging
    import os

    cfg = get_config()
    log = logging.getLogger("pi-spy-rf")
    logging.basicConfig(level=logging.INFO)
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    init_db()
    init_wireless_tables()
    ensure_mini_oui()

    host = cfg.server.host
    allow_insecure = os.environ.get("PI_SPY_ALLOW_INSECURE_LAN", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if host in ("0.0.0.0", "::") and not auth_enabled():
        msg = (
            f"Refusing to bind {host}:{cfg.server.port} with auth disabled. "
            "Enable auth (auth.enabled + PI_SPY_PASSWORD), bind 127.0.0.1, "
            "or set PI_SPY_ALLOW_INSECURE_LAN=1 to override."
        )
        if allow_insecure:
            log.warning(msg + " Override accepted.")
        else:
            log.error(msg)
            raise SystemExit(2)
    if os.environ.get("PI_SPY_NO_DEMO") == "1":
        log.info("PI_SPY_NO_DEMO=1 — demo SDR placeholders disabled")

    uvicorn.run(
        app,
        host=host,
        port=cfg.server.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
