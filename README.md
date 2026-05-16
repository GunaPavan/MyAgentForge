---
title: MyAgentForge
emoji: 🤖
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: AI agents that build software, privately
---

<div align="center">

# MyAgentForge

**AI agents that build software, privately.**

A swarm of six specialized AI agents collaborates in real time to plan, code, review, and execute software. Bring your own LLM key. We store nothing.

[![Try the live demo](https://img.shields.io/badge/Try_the_live_demo-→-6c63ff?style=for-the-badge)](https://gunapavan-myagentforge.hf.space/)
[![CI](https://github.com/GunaPavan/MyAgentForge/actions/workflows/ci.yml/badge.svg)](https://github.com/GunaPavan/MyAgentForge/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](Dockerfile)

</div>

---

## What it is

MyAgentForge orchestrates six specialized AI agents — Orchestrator, Planner, Coder, Reviewer, Tester, and Debugger — that communicate via a structured message bus to solve software engineering tasks. The Tester doesn't just describe tests — it *executes* the generated code in a real sandbox and reports actual pass/fail.

```
You → Orchestrator → Planner → Coder ⇄ Reviewer → Tester (executes) → Done
```

## Why it exists

Most AI coding tools either:
1. Run on someone else's infrastructure (and read all your keys + prompts), or
2. Are stateful black boxes you can't introspect.

MyAgentForge is the opposite — the server has no database, no user accounts, no telemetry. Your API keys live in your browser's localStorage and are passed per-request to whichever LLM provider you choose. We literally cannot leak data we don't have.

## Key features

- **Privacy by design** — server is fully stateless. API keys never persisted, never logged.
- **Six specialized agents** — each with its own system prompt, communicating over a typed event bus
- **Real-time streaming** — token-by-token agent output over WebSocket, like ChatGPT
- **Real code execution** — Tester runs generated code in a sandboxed subprocess with CPU, memory, file-size, and process limits
- **Bring any LLM** — Cerebras, Groq, Gemini, OpenAI, Mistral, OpenRouter, DeepSeek, Ollama, or any OpenAI-compatible endpoint
- **Iterative refinement** — generate a project, then ask for changes; the swarm modifies existing code surgically
- **Live HTML preview** — generated web apps render instantly in a sandboxed iframe

## Quick start

### Use the hosted demo
[gunapavan-myagentforge.hf.space](https://gunapavan-myagentforge.hf.space/) — paste your API key, type a task.

### Self-host with Docker
```bash
git clone https://github.com/GunaPavan/MyAgentForge.git
cd MyAgentForge
docker build -t myagentforge .
docker run -p 7860:7860 -e MODE=prod myagentforge
```

### Run from source
```bash
pip install -r requirements.txt
python main.py
# open http://localhost:8000
```

### Try without an LLM key (mock mode)
```bash
MODE=mock python main.py
```

## Architecture

```
myagentforge/
├── main.py                    # FastAPI server, WebSocket endpoint, security middleware
├── Dockerfile                 # Multi-stage, non-root, healthcheck
├── core/
│   ├── swarm.py               # Orchestration engine (event queue, streaming)
│   ├── sandbox.py             # Subprocess + Docker code execution backends
│   ├── config.py              # Per-request LLM config via contextvars
│   └── models.py              # Pydantic data models
├── agents/
│   ├── base.py                # BaseAgent with streaming support
│   ├── orchestrator.py        # Task analysis
│   ├── planner.py             # Architectural planning (handles follow-ups)
│   ├── coder.py               # JSON-formatted file generation
│   ├── reviewer.py            # Code review with APPROVED / NEEDS_FIXES verdict
│   ├── tester.py              # Generates AND executes test code
│   └── debugger.py            # Error analysis
├── static/
│   ├── index.html             # Landing page
│   ├── app.html               # Dashboard
│   ├── landing.css, app.js, db.js, styles.css
│   └── favicon.svg
├── tests/                     # 50 automated tests
└── .github/workflows/ci.yml   # Tests + security scan + Docker build on every push
```

## Security posture

| Layer | Defense |
|-------|---------|
| Server data | Zero — no DB, no user accounts, no telemetry |
| API keys | Browser localStorage only, passed per-request, never persisted server-side |
| HTTP | Strict CSP (no `unsafe-inline`), X-Frame-Options, Referrer-Policy, Permissions-Policy |
| CDN | Subresource Integrity hashes on all 8 Prism assets |
| Code execution | Subprocess sandbox with POSIX setrlimit caps (CPU/RAM/files/procs) + 10s wallclock timeout |
| Rate limiting | slowapi on mutation endpoints |
| Logging | Key-redacting filter on every error message |
| Dependencies | All pinned, pip-audit on every CI run — currently 0 known CVEs |

## Configuration

All optional. The app runs in mock mode without any config.

| Variable | Default | Notes |
|----------|---------|-------|
| `MODE` | `prod` | `mock` / `dev` / `prod` |
| `PORT` | `7860` | HF Spaces standard; Docker injects this |
| `MAX_REVIEW_ITERATIONS` | mode-driven | Code review fix loops |
| `SKIP_TESTER` | mode-driven | Skip Tester agent (cheaper) |
| `COMBINE_ORCHESTRATOR` | `true` | Merge Orchestrator+Planner into one call |
| `MAX_TOKENS` | mode-driven | `0` = model default |
| `LLM_TIMEOUT` | `60` | Seconds |

## Supported LLM providers

| Provider | Free tier | Get a key |
|----------|-----------|-----------|
| Cerebras | ✅ Fastest | [cloud.cerebras.ai](https://cloud.cerebras.ai/platform/api-keys) |
| Groq | ✅ Daily limit | [console.groq.com](https://console.groq.com/keys) |
| Google Gemini | ✅ 1500/day | [aistudio.google.com](https://aistudio.google.com/apikey) |
| OpenRouter | ✅ Some free models | [openrouter.ai](https://openrouter.ai/keys) |
| Mistral | ✅ Free tier | [console.mistral.ai](https://console.mistral.ai/api-keys/) |
| Together AI | $25 credit | [api.together.xyz](https://api.together.xyz/settings/api-keys) |
| SambaNova | ✅ Free tier | [cloud.sambanova.ai](https://cloud.sambanova.ai/apis) |
| DeepSeek | Cheap (~$0.14/M) | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| OpenAI | Paid | [platform.openai.com](https://platform.openai.com/api-keys) |
| Ollama | Free, local | [ollama.com](https://ollama.com/download) |

## Tests & CI

50 automated tests run on every push:

```
tests/
├── test_endpoints.py     # HTTP routes, security headers, path traversal, ZIP limits
├── test_websocket.py     # WS limits, full mock run, follow-up mode, cancel
├── test_rate_limiting.py # 429 enforcement
├── test_sandbox.py       # Sandbox security: timeouts, resource limits, fs isolation, network blocks
└── test_security.py      # SRI, XSS defenses, secret scan, Dockerfile, CVE audit
```

Run locally:
```bash
pip install -r requirements-dev.txt
pytest -v
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for full guides. Quick options:

- **Hugging Face Spaces** (free, what we use) — push to a Docker Space and set `MODE` to `prod`
- **Fly.io** — `fly launch && fly deploy`
- **Railway** — connect the GitHub repo, click deploy
- **Docker anywhere** — `docker build -t myagentforge . && docker run -p 7860:7860 myagentforge`

## License

MIT. See [LICENSE](LICENSE).

## Acknowledgements

Built with FastAPI, Pydantic, OpenAI SDK, Prism.js, and several free LLM providers' generosity. UI is vanilla JS — no frameworks, no build step, no bloat.
