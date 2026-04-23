"""Rate-limit enforcement tests."""
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_download_zip_rate_limit(app):
    """Hit /download-zip aggressively — should get 429s after ~30/minute."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Send 40 requests as fast as possible
        async def hit():
            return await client.post("/download-zip", json={"files": {"a.py": "x"}})

        responses = await asyncio.gather(*[hit() for _ in range(40)], return_exceptions=True)

    statuses = [r.status_code for r in responses if hasattr(r, "status_code")]
    assert 200 in statuses
    assert 429 in statuses, f"Expected some 429 responses, got: {set(statuses)}"
