"""Pytest fixtures shared by all tests.

Starts the FastAPI app in a background asyncio task using httpx's ASGITransport
so we don't actually bind a port. Forces MODE=mock for deterministic LLM replies.
"""
import os
os.environ.setdefault("MODE", "mock")

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    # Import lazily so MODE env var takes effect first
    from main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
