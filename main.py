import asyncio
import io
import json
import sys
import os
import zipfile

sys.path.insert(0, os.path.dirname(__file__))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from core.swarm import Swarm

app = FastAPI(title="MyAgentForge", version="1.0.0")

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "index.html"))


@app.get("/api/config")
async def get_config():
    """Return the currently-configured model + provider (no API key exposed)."""
    from core.config import MODEL_NAME, BASE_URL
    url_l = BASE_URL.lower()
    provider = "Custom"
    if "cerebras" in url_l: provider = "Cerebras"
    elif "groq" in url_l: provider = "Groq"
    elif "openai" in url_l: provider = "OpenAI"
    elif "googleapis" in url_l or "gemini" in url_l: provider = "Google Gemini"
    elif "mistral" in url_l: provider = "Mistral"
    elif "deepseek" in url_l: provider = "DeepSeek"
    elif "openrouter" in url_l: provider = "OpenRouter"
    elif "together" in url_l: provider = "Together AI"
    elif "sambanova" in url_l: provider = "SambaNova"
    elif "hyperbolic" in url_l: provider = "Hyperbolic"
    elif "localhost" in url_l or "127.0.0.1" in url_l: provider = "Local (Ollama)"
    return {"model": MODEL_NAME, "provider": provider}


@app.post("/download-zip")
async def download_zip(files: dict):
    """Package the given files dict into a ZIP and return it."""
    if not isinstance(files, dict) or not files:
        raise HTTPException(400, "No files provided")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            safe_name = os.path.basename(str(fname))
            if safe_name:
                zf.writestr(safe_name, str(content))

    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=myagentforge-output.zip"},
    )


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    current_swarm = None
    runner_task = None

    async def run_swarm(task: str):
        nonlocal current_swarm
        current_swarm = Swarm()
        try:
            async for event in current_swarm.run(task):
                await ws.send_text(event.model_dump_json())
        except Exception as e:
            try:
                await ws.send_text(json.dumps({"type": "error", "data": {"message": str(e)}}))
            except Exception:
                pass

    try:
        while True:
            data = await ws.receive_text()
            payload = json.loads(data)
            action = payload.get("action", "run")

            if action == "cancel":
                if current_swarm:
                    current_swarm.cancel()
                continue

            if action == "run":
                task = payload.get("task", "")
                if not task:
                    await ws.send_text(json.dumps({"type": "error", "data": {"message": "No task provided"}}))
                    continue

                # Cancel any existing swarm
                if current_swarm:
                    current_swarm.cancel()
                if runner_task and not runner_task.done():
                    runner_task.cancel()

                runner_task = asyncio.create_task(run_swarm(task))

    except WebSocketDisconnect:
        if current_swarm:
            current_swarm.cancel()
    except Exception as e:
        try:
            await ws.send_text(json.dumps({"type": "error", "data": {"message": str(e)}}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
