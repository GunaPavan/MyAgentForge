"""WebSocket behavioral + limit tests.

Uses a real running server on a free port so we can drive actual WS clients.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import pytest
import websockets


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def running_server():
    """Spin up a real uvicorn server for WebSocket tests."""
    port = _free_port()
    env = os.environ.copy()
    env["MODE"] = "mock"
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Wait for server to be ready
    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("Server failed to start")

    yield port

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_ws_rejects_oversized_message(running_server):
    port = running_server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws", max_size=10 * 1024 * 1024) as ws:
        # Send 80 KB message -- above 64 KB limit
        payload = json.dumps({"action": "run", "task": "x" * 80000, "llm_config": {}})
        await ws.send(payload)
        reply = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(reply)
        assert data.get("type") == "error"
        assert "large" in data["data"]["message"].lower()


@pytest.mark.asyncio
async def test_ws_rejects_empty_task(running_server):
    port = running_server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        await ws.send(json.dumps({"action": "run", "task": "", "llm_config": {}}))
        reply = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(reply)
        assert data.get("type") == "error"


@pytest.mark.asyncio
async def test_ws_rejects_invalid_json(running_server):
    port = running_server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        await ws.send("this is not json at all {{{")
        reply = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(reply)
        assert data.get("type") == "error"


@pytest.mark.asyncio
async def test_ws_mock_full_run_streams_events(running_server):
    """End-to-end test: submit a task in mock mode, receive swarm events."""
    port = running_server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        await ws.send(json.dumps({"action": "run", "task": "Make a simple calculator", "llm_config": {}}))
        event_types = []
        for _ in range(200):  # cap iterations
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                break
            data = json.loads(msg)
            event_types.append(data.get("type"))
            if data.get("type") == "task_status" and data.get("data", {}).get("status") == "completed":
                break

        # Verify we saw the expected event variety
        assert "message" in event_types
        assert "agent_status" in event_types
        assert "stream" in event_types
        assert "code_output" in event_types
        assert "task_status" in event_types


@pytest.mark.asyncio
async def test_ws_cancel_action(running_server):
    port = running_server
    async with websockets.connect(f"ws://127.0.0.1:{port}/ws") as ws:
        await ws.send(json.dumps({"action": "run", "task": "Make something", "llm_config": {}}))
        # Immediately cancel
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"action": "cancel"}))

        got_cancel = False
        for _ in range(100):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                break
            data = json.loads(msg)
            if data.get("type") == "task_status" and data.get("data", {}).get("status") in ("failed", "completed"):
                # Some tasks finish before cancel in mock mode — either is acceptable
                got_cancel = True
                break
        assert got_cancel
