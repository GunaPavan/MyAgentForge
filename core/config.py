"""Per-request LLM configuration.

Keys are NEVER stored server-side. Each WebSocket request supplies the user's
API key + base URL + model. We set it on a contextvar for the duration of
the request and a fresh AsyncOpenAI client is created per LLM call.

For local dev you may set LLM_API_KEY / LLM_BASE_URL / MODEL_NAME in .env as
a fallback, but in production no server-side key is required.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import re
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()


# ===== Execution Mode =====
MODE = os.getenv("MODE", "prod").lower().strip()
if MODE not in {"mock", "dev", "prod"}:
    MODE = "prod"


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


# Mode-driven defaults
if MODE == "dev":
    _d_review, _d_skip_tester, _d_combine, _d_max_tokens = 0, True, True, 1024
elif MODE == "mock":
    _d_review, _d_skip_tester, _d_combine, _d_max_tokens = 0, True, True, 256
else:  # prod
    _d_review, _d_skip_tester, _d_combine, _d_max_tokens = 1, False, True, 0

MAX_REVIEW_ITERATIONS = _env_int("MAX_REVIEW_ITERATIONS", _d_review)
SKIP_TESTER = _env_bool("SKIP_TESTER", _d_skip_tester)
COMBINE_ORCHESTRATOR = _env_bool("COMBINE_ORCHESTRATOR", _d_combine)
MAX_TOKENS = _env_int("MAX_TOKENS", _d_max_tokens)
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

# Optional server-side fallback for local dev — NOT required in production.
_FALLBACK_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
_FALLBACK_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
_FALLBACK_MODEL = os.getenv("MODEL_NAME", "gpt-4o-mini")


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str


_current_config: contextvars.ContextVar[Optional[LLMConfig]] = contextvars.ContextVar(
    "llm_config", default=None
)


def set_request_config(api_key: str, base_url: str, model: str):
    """Called by the WS handler at the start of each swarm run.

    Returns a token — pass it to reset_request_config() in a finally block
    to explicitly scrub the key when the run completes.
    """
    token = _current_config.set(
        LLMConfig(api_key=api_key.strip(), base_url=base_url.strip(), model=model.strip())
    )
    return token


def reset_request_config(token) -> None:
    """Reset the per-request config to its previous state (typically None)."""
    try:
        _current_config.reset(token)
    except (LookupError, ValueError):
        # Token from different context; clear best-effort.
        _current_config.set(None)


def get_request_config() -> LLMConfig:
    cfg = _current_config.get()
    if cfg and cfg.api_key:
        return cfg
    # Fallback to env (dev only)
    if _FALLBACK_API_KEY:
        return LLMConfig(api_key=_FALLBACK_API_KEY, base_url=_FALLBACK_BASE_URL, model=_FALLBACK_MODEL)
    # No key available — mock mode is OK; real mode returns an error
    return LLMConfig(api_key="", base_url=_FALLBACK_BASE_URL, model=_FALLBACK_MODEL)


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


class KeyRedactingFilter:
    """Filter that strips API keys out of strings (best-effort)."""

    PATTERNS = [
        # Order matters: longer/prefixed tokens first so they don't get half-matched
        re.compile(r"\b(csk-[A-Za-z0-9_\-]{10,})"),
        re.compile(r"\b(gsk_[A-Za-z0-9_\-]{10,})"),
        re.compile(r"\b(sk-[A-Za-z0-9_\-]{10,})"),
        re.compile(r"\b(sk_[A-Za-z0-9_\-]{10,})"),
        re.compile(r"Bearer\s+([A-Za-z0-9_\-\.]{10,})"),
    ]

    @classmethod
    def redact(cls, s: str) -> str:
        if not isinstance(s, str):
            return s
        out = s
        for pat in cls.PATTERNS:
            out = pat.sub("[REDACTED_KEY]", out)
        return out


# ============================================================
# Mock responses (used when MODE=mock)
# ============================================================
_MOCK_RESPONSES = {
    "orchestrator": (
        "Summary: Build the requested feature.\n"
        "Requirements: 1. Core functionality 2. Clean structure 3. Error handling\n"
        "Expected files: index.html, styles.css, script.js\n"
        "Success criteria: Working demo."
    ),
    "planner": (
        "Architecture: Simple 3-file static web app.\n"
        "Files to create:\n1. index.html - UI layout\n2. styles.css - styling\n3. script.js - interactivity\n"
        "Implementation order: HTML first, then CSS, then JS."
    ),
    "coder": (
        '{"index.html": "<!DOCTYPE html>\\n<html><head><meta charset=\\"utf-8\\">'
        '<link rel=\\"stylesheet\\" href=\\"styles.css\\"><title>Mock App</title></head>'
        '<body><h1 id=\\"t\\">Mock App</h1><button id=\\"b\\">Click</button>'
        '<script src=\\"script.js\\"></script></body></html>", '
        '"styles.css": "body{font-family:sans-serif;text-align:center;padding:40px;background:#0a0a0f;color:#e8e8ed}'
        'h1{color:#6c63ff}button{padding:10px 20px;background:#6c63ff;color:white;border:none;border-radius:6px;cursor:pointer}", '
        '"script.js": "document.getElementById(\'b\').addEventListener(\'click\', () => {'
        'document.getElementById(\'t\').textContent = \'Clicked!\';});"}'
    ),
    "reviewer": (
        "Review notes:\n- Code is clean and functional\n- Minor: could add aria-labels for accessibility\n"
        "Overall: Production-ready.\n\nVERDICT: APPROVED"
    ),
    "tester": (
        "Unit tests:\n1. test_button_click\n2. test_initial_state\n"
        "Edge cases: double-click handled, empty state OK.\nCoverage: ~90%."
    ),
    "debugger": "Error analysis: No errors detected in mock mode.\nRoot cause: N/A\nFix: N/A",
}


def _mock_response_for(system_prompt: str) -> str:
    first_line = (system_prompt or "").split(".")[0].lower()
    for key in _MOCK_RESPONSES:
        if key in first_line:
            return _MOCK_RESPONSES[key]
    return "[mock response]"


def _build_params(system_prompt: str, user_prompt: str, model: str, stream: bool = False) -> dict:
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    if MAX_TOKENS > 0:
        params["max_tokens"] = MAX_TOKENS
    if stream:
        params["stream"] = True
    return params


def _make_client(cfg: LLMConfig) -> AsyncOpenAI:
    return AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=LLM_TIMEOUT)


class MissingAPIKey(Exception):
    pass


async def llm_call(system_prompt: str, user_prompt: str) -> str:
    if MODE == "mock":
        await asyncio.sleep(0.3)
        return _mock_response_for(system_prompt)
    cfg = get_request_config()
    if not cfg.api_key:
        return "[Error: No API key configured. Click the gear icon to set your key.]"
    try:
        client = _make_client(cfg)
        response = await asyncio.wait_for(
            client.chat.completions.create(**_build_params(system_prompt, user_prompt, cfg.model)),
            timeout=LLM_TIMEOUT,
        )
        return response.choices[0].message.content or ""
    except asyncio.TimeoutError:
        return f"[LLM call timed out after {LLM_TIMEOUT}s]"
    except Exception as e:
        msg = KeyRedactingFilter.redact(str(e))[:200]
        return f"[LLM error: {type(e).__name__}: {msg}]"


async def llm_stream(system_prompt: str, user_prompt: str):
    if MODE == "mock":
        text = _mock_response_for(system_prompt)
        for i in range(0, len(text), 20):
            await asyncio.sleep(0.02)
            yield text[i : i + 20]
        return
    cfg = get_request_config()
    if not cfg.api_key:
        yield "[Error: No API key configured. Click the gear icon to set your key.]"
        return
    try:
        client = _make_client(cfg)
        stream = await client.chat.completions.create(
            **_build_params(system_prompt, user_prompt, cfg.model, stream=True)
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except Exception as e:
        msg = KeyRedactingFilter.redact(str(e))[:200]
        yield f"[LLM error: {type(e).__name__}: {msg}]"
