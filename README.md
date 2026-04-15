# MyAgentForge

An AI multi-agent system where specialized agents collaborate to solve software engineering tasks in real-time — with a live dashboard showing agents streaming their thoughts as they work.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Overview

MyAgentForge orchestrates 6 specialized AI agents that work together like a software engineering team. Submit a task, watch the agents communicate live, see the generated code with syntax highlighting, and preview HTML apps instantly — all in one dashboard.

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
| **Tester** | Generates test cases and validates logic |
| **Debugger** | Traces errors and proposes fixes |

## Features

- **Real-time Streaming** — Watch agents generate output token-by-token (like ChatGPT)
- **Live Web Dashboard** — WebSocket-powered UI with agent avatars, status indicators, and message stream
- **Live HTML Preview** — For web projects, see the running app in a sandboxed iframe
- **Syntax Highlighting** — Color-coded code with Prism.js for Python, JS, HTML, CSS, JSON, Bash
- **Task Templates** — One-click quick-starts: Tic-tac-toe, Landing page, REST API, CLI tool, Snake game
- **ZIP Download** — One-click download of all generated files
- **Stop / Cancel** — Kill a running task mid-way to save API calls
- **Auto-save to Disk** — Files saved to `output/<task-id>/` after every task
- **Universal LLM Support** — Works with any OpenAI-compatible API (Cerebras, Groq, OpenAI, Gemini, Mistral, OpenRouter, DeepSeek, Ollama, etc.)
- **API Cost Optimization** — Configurable flags to skip agents, combine roles, limit review loops

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/GunaPavan/myagentforge.git
cd myagentforge
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your preferred LLM provider's API key
```

**Recommended: Cerebras (free, fast)**
```env
LLM_API_KEY=csk-...
LLM_BASE_URL=https://api.cerebras.ai/v1
MODEL_NAME=<pick-from-models-link>
```

Supported providers (all OpenAI-compatible APIs) — click "Browse Models" to pick the exact model you want:

| Provider | Tier | Get Key | Browse Models |
|----------|------|---------|---------------|
| Cerebras | Free | [Keys](https://cloud.cerebras.ai/platform/api-keys) | [Models](https://inference-docs.cerebras.ai/introduction) |
| Groq | Free | [Keys](https://console.groq.com/keys) | [Models](https://console.groq.com/docs/models) |
| Google Gemini | Free | [Keys](https://aistudio.google.com/apikey) | [Models](https://ai.google.dev/gemini-api/docs/models/gemini) |
| OpenRouter | Free tier | [Keys](https://openrouter.ai/keys) | [Models](https://openrouter.ai/models) |
| Mistral | Free tier | [Keys](https://console.mistral.ai/api-keys/) | [Models](https://docs.mistral.ai/getting-started/models/models_overview/) |
| Together AI | $25 credit | [Keys](https://api.together.xyz/settings/api-keys) | [Models](https://docs.together.ai/docs/serverless-models) |
| SambaNova | Free tier | [Keys](https://cloud.sambanova.ai/apis) | [Models](https://docs.sambanova.ai/cloud/docs/get-started/supported-models) |
| DeepSeek | Cheap | [Keys](https://platform.deepseek.com/api_keys) | [Models](https://api-docs.deepseek.com/quick_start/pricing) |
| OpenAI | Paid | [Keys](https://platform.openai.com/api-keys) | [Models](https://platform.openai.com/docs/models) |
| Ollama | Local | [Install](https://ollama.com/download) | [Library](https://ollama.com/library) |

You can also access this provider list directly in the **web dashboard** — click the gear icon in the top-right to see all providers with one-click "Copy .env" buttons.

### 3. Run

```bash
python main.py
```

Open **http://localhost:8000**. Click a template button or type your own task and hit **Run Swarm**.

### CLI Mode

```bash
python examples/demo.py "Create a Python REST API for a todo app"
```

## Configuration

All in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | API key for your chosen provider |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `MODEL_NAME` | `gpt-4o-mini` | Model to use (browse the provider's model catalog to pick) |
| `MAX_TOKENS` | `0` | Max output tokens per agent call (0 = model default) |
| `LLM_TIMEOUT` | `60` | Per-request timeout in seconds |
| `MAX_REVIEW_ITERATIONS` | `1` | Max code-review fix loops |
| `SKIP_TESTER` | `false` | Skip Tester agent to save 1 API call/task |
| `COMBINE_ORCHESTRATOR` | `true` | Merge Orchestrator+Planner into 1 call |

### Minimizing API Costs

Default = ~4 API calls per task. Set `SKIP_TESTER=true` to get down to **3 calls per task**.

## Architecture

```
myagentforge/
├── main.py               # FastAPI server, WebSocket, ZIP endpoint
├── agents/
│   ├── base.py           # Base agent with streaming support
│   ├── orchestrator.py   # Task decomposition
│   ├── planner.py        # Implementation planning
│   ├── coder.py          # Code generation (JSON-formatted output)
│   ├── reviewer.py       # Code review with APPROVE/NEEDS_FIXES verdict
│   ├── tester.py         # Test case generation
│   └── debugger.py       # Error analysis (used on failures)
├── core/
│   ├── swarm.py          # Orchestration engine with streaming events
│   ├── models.py         # Pydantic data models
│   └── config.py         # LLM client setup (OpenAI-compatible)
├── static/               # Dashboard UI (vanilla JS, Prism.js)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── examples/
│   └── demo.py           # CLI demo script
└── output/               # Generated files saved here (gitignored)
```

## How Streaming Works

Each agent call streams token-by-token via the OpenAI SDK's `stream=True`. The swarm pushes `stream_start`, `stream`, and `stream_end` events to the frontend via WebSocket. The dashboard renders them live with a blinking cursor — same UX as ChatGPT.

## Tech Stack

- **Backend**: Python, FastAPI, WebSockets, OpenAI SDK, Pydantic
- **Frontend**: Vanilla HTML/CSS/JS, Prism.js (syntax highlighting)
- **No build step**, no React, no heavyweight dependencies

## License

MIT
