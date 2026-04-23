---
title: MyAgentForge
emoji: 🤖
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: AI agent swarm for software engineering tasks
---

# MyAgentForge

An AI multi-agent system where specialized agents collaborate to solve software engineering tasks in real-time — with a live streaming dashboard, **zero server-side storage**, and support for any OpenAI-compatible LLM provider.

### 🚀 [**Try the live demo →**](https://gunapavan-myagentforge.hf.space/)

[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen?style=for-the-badge&logo=huggingface&logoColor=white)](https://gunapavan-myagentforge.hf.space/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](./Dockerfile)
[![License](https://img.shields.io/badge/License-MIT-yellow)](./LICENSE)
[![CI](https://github.com/GunaPavan/MyAgentForge/actions/workflows/ci.yml/badge.svg)](https://github.com/GunaPavan/MyAgentForge/actions/workflows/ci.yml)

> **Bring your own API key.** Keys stay in your browser — never stored on our server. Deploy is stateless by design.

## Overview

MyAgentForge orchestrates 6 specialized AI agents that work together like a software engineering team. Submit a task, watch the agents communicate live, see the generated code with syntax highlighting, and preview web apps instantly — all in one dashboard.

```
User Task -> Orchestrator -> Planner -> Coder -> Reviewer -> Tester -> Done
                                         ^          |
                                         |__________|
                                       (fix code if needed)
```

| Agent | Role |
|-------|------|
| **Orchestrator** | Analyzes tasks, creates structured briefs |
| **Planner** | Designs implementation plans with file structures |
| **Coder** | Writes production-quality code |
| **Reviewer** | Reviews for bugs, security, best practices |
| **Tester** | Generates test cases |
| **Debugger** | Traces errors and proposes fixes |

## Privacy & Security

**Your API keys never touch our server.** MyAgentForge is built privacy-first:

- API keys live only in your browser's localStorage (optionally sessionStorage for "clear on close")
- Keys are passed per-request to the server, used once, and never persisted or logged
- All project history is stored in your browser's IndexedDB — no database, no user accounts, no login
- Strict Content Security Policy, Subresource Integrity on all CDN assets, rate limiting, key redaction in error messages
- iframe-sandboxed preview (can't escape to parent page)

The server is fully stateless — nothing to steal, nothing to leak.

## Features

- **Real-time streaming** — Agent output appears token-by-token (like ChatGPT)
- **Live HTML preview** — Instant preview of generated web apps in a sandboxed iframe
- **Syntax highlighting** — Python, JS, HTML, CSS, JSON, Bash via Prism.js (with SRI)
- **Task templates** — One-click quick-starts
- **ZIP download** — Grab generated files per-project or for the current task
- **Stop/cancel** — Kill a running task mid-way
- **Storage meter** — See live localStorage + IndexedDB usage
- **Session-only key mode** — Auto-clear your key when the tab closes
- **Three run modes** — `mock` (zero cost), `dev` (minimal tokens), `prod` (full quality)
- **Any OpenAI-compatible provider** — Cerebras, Groq, OpenAI, Gemini, Mistral, OpenRouter, DeepSeek, Ollama, etc.

## Quick Start

### Option A: Local Python

```bash
git clone https://github.com/GunaPavan/MyAgentForge.git
cd MyAgentForge
pip install -r requirements.txt
python main.py
```

Open **http://localhost:8000**. Click the robot badge in the top-right to paste your API key (stored only in your browser). Run a task.

### Option B: Docker

```bash
docker build -t myagentforge .
docker run -p 8000:8000 myagentforge
```

### Option C: Mock mode (no LLM provider needed)

Set `MODE=mock` in your environment — everything works with canned responses. Perfect for UI exploration without any API cost.

```bash
MODE=mock python main.py
```

## Supported LLM Providers

All OpenAI-compatible APIs work out of the box. Click the gear icon in the web UI to see all options and auto-fill the base URL:

| Provider | Tier | Notes |
|----------|------|-------|
| [Cerebras](https://cloud.cerebras.ai/) | Free | Fastest inference |
| [Groq](https://console.groq.com/) | Free | Daily token limit |
| [Google Gemini](https://aistudio.google.com/apikey) | Free | 1500 req/day on 2.0 Flash |
| [OpenRouter](https://openrouter.ai/) | Free tier | Many models, some marked :free |
| [Mistral](https://console.mistral.ai/) | Free tier | |
| [Together AI](https://api.together.xyz/) | $25 credit | |
| [SambaNova](https://cloud.sambanova.ai/) | Free tier | |
| [DeepSeek](https://platform.deepseek.com/) | Cheap | ~$0.14/1M tokens |
| [OpenAI](https://platform.openai.com/) | Paid | |
| [Ollama](https://ollama.com/) | Local | Run models on your own machine |

## Configuration

All via `.env` (all optional — mock mode works with no config):

| Variable | Default | Description |
|----------|---------|-------------|
| `MODE` | `prod` | `mock`, `dev`, or `prod` |
| `PORT` | `8000` | HTTP port |
| `MAX_REVIEW_ITERATIONS` | `1` | Code-review fix loops |
| `SKIP_TESTER` | mode-based | Skip Tester agent |
| `COMBINE_ORCHESTRATOR` | `true` | Merge Orchestrator+Planner |
| `MAX_TOKENS` | mode-based | 0 = model default |
| `LLM_TIMEOUT` | `60` | Per-request timeout (seconds) |

Run modes set sensible defaults:

| Mode | Review iter | Skip Tester | Max tokens |
|------|:-----------:|:-----------:|:----------:|
| `mock` | 0 | yes | 256 |
| `dev`  | 0 | yes | 1024 |
| `prod` | 1 | no  | unlimited |

## Architecture

```
myagentforge/
├── main.py               # FastAPI + WebSocket + security middleware
├── Dockerfile            # Multi-stage, non-root, healthcheck
├── railway.json          # Railway deploy config
├── docker-compose.yml    # Local Docker dev
├── agents/
│   ├── base.py           # Base agent with streaming support
│   ├── orchestrator.py   # Task decomposition
│   ├── planner.py        # Implementation planning
│   ├── coder.py          # JSON-formatted code generation
│   ├── reviewer.py       # Code review with APPROVED/NEEDS_FIXES
│   ├── tester.py         # Test case generation
│   └── debugger.py       # Error analysis
├── core/
│   ├── swarm.py          # Orchestration engine (streaming events)
│   ├── models.py         # Pydantic data models
│   └── config.py         # Per-request LLM config via contextvars
├── static/               # Frontend (vanilla JS + Prism.js with SRI)
│   ├── index.html
│   ├── styles.css
│   ├── app.js            # WebSocket client + UI logic
│   └── db.js             # IndexedDB project store
└── examples/demo.py      # CLI demo script
```

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for detailed guides. Short version:

- **Railway** (recommended): push to GitHub, click Deploy from GitHub on Railway, done
- **Fly.io**: `fly launch && fly deploy`
- **Docker anywhere**: the image works on any Docker host

## Tech Stack

- **Backend**: Python 3.11, FastAPI, WebSockets, OpenAI SDK, Pydantic, slowapi
- **Frontend**: Vanilla HTML/CSS/JS, Prism.js (syntax highlighting)
- **Storage**: Browser-side only — IndexedDB + localStorage
- **No build step**, no React, no heavy dependencies

## License

MIT
