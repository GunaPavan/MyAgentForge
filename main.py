"""MyAgentForge server.

Stateless, privacy-first:
- No user accounts, no login.
- User API keys are passed per-request via WebSocket and are NEVER stored.
- All project history lives in the user's browser.

Security:
- Strict Content Security Policy + standard security headers
- IP-based rate limiting on mutation endpoints
- Key-redacting exception filter
- Max WebSocket message size
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import zipfile
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from core.swarm import Swarm
from core.config import (
    MODE, MAX_REVIEW_ITERATIONS, SKIP_TESTER, MAX_TOKENS,
    set_request_config, reset_request_config, KeyRedactingFilter,
)


# ---------- Rate limiter ----------
limiter = Limiter(key_func=get_remote_address)


# ---------- Security headers ----------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Standard security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # CSP: allow Prism CDN and Google Fonts (already used), inline styles for dynamic content
        csp = (
            "default-src 'self'; "
            "script-src 'self' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-src blob:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers["Content-Security-Policy"] = csp
        return response


app = FastAPI(title="MyAgentForge", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SecurityHeadersMiddleware)

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/config")
async def get_config():
    """Return server-side config (no secrets, no keys). Used by frontend for display only."""
    return {
        "mode": MODE,
        "skip_tester": SKIP_TESTER,
        "max_review_iterations": MAX_REVIEW_ITERATIONS,
        "max_tokens": MAX_TOKENS,
    }


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": MODE}


# Max 20MB zip request; harder stops come via Railway/reverse-proxy if deployed
@app.post("/download-zip")
@limiter.limit("30/minute")
async def download_zip(request: Request):
    data = await request.json()
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 100:
        raise HTTPException(400, "Too many files")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        total = 0
        for fname, content in files.items():
            safe_name = os.path.basename(str(fname))
            if not safe_name:
                continue
            content_s = str(content)
            total += len(content_s)
            if total > 10 * 1024 * 1024:  # 10MB cap
                raise HTTPException(400, "Archive too large")
            zf.writestr(safe_name, content_s)

    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=myagentforge-output.zip"},
    )


MAX_TASK_LENGTH = 8000  # characters
MAX_WS_MSG = 64 * 1024  # 64KB


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    current_swarm = None
    runner_task = None

    async def send_error(message: str):
        try:
            await ws.send_text(json.dumps({"type": "error", "data": {"message": message}}))
        except Exception:
            pass

    async def run_swarm(task: str, llm_config: dict):
        nonlocal current_swarm
        # Set per-request LLM config in contextvar (never touches DB/logs)
        token = set_request_config(
            api_key=llm_config.get("api_key", ""),
            base_url=llm_config.get("base_url", ""),
            model=llm_config.get("model", ""),
        )
        current_swarm = Swarm()
        try:
            async for event in current_swarm.run(task):
                await ws.send_text(event.model_dump_json())
        except Exception as e:
            msg = KeyRedactingFilter.redact(str(e))
            await send_error(msg[:500])
        finally:
            # Explicitly scrub the per-request key from the contextvar
            reset_request_config(token)

    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_WS_MSG:
                await send_error("Message too large")
                continue

            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await send_error("Invalid JSON")
                continue

            action = payload.get("action", "run")

            if action == "cancel":
                if current_swarm:
                    current_swarm.cancel()
                continue

            if action == "run":
                task = (payload.get("task") or "").strip()
                if not task:
                    await send_error("No task provided")
                    continue
                if len(task) > MAX_TASK_LENGTH:
                    await send_error(f"Task too long (max {MAX_TASK_LENGTH} chars)")
                    continue

                llm_config = payload.get("llm_config") or {}
                if MODE != "mock":
                    if not isinstance(llm_config, dict) or not llm_config.get("api_key"):
                        await send_error(
                            "No API key provided. Click the gear icon to set your LLM API key "
                            "(stored only in your browser)."
                        )
                        continue

                # Cancel any in-flight swarm
                if current_swarm:
                    current_swarm.cancel()
                if runner_task and not runner_task.done():
                    runner_task.cancel()

                runner_task = asyncio.create_task(run_swarm(task, llm_config))

    except WebSocketDisconnect:
        if current_swarm:
            current_swarm.cancel()
    except Exception as e:
        msg = KeyRedactingFilter.redact(str(e))
        await send_error(msg[:500])


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    # reload only in local dev (set DEV_RELOAD=1); production should not reload
    reload = os.getenv("DEV_RELOAD", "0") == "1"
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=reload)
