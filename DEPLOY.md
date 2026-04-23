# Deploying MyAgentForge

MyAgentForge is stateless and keyless on the server side — **no secrets to configure**. Users supply their own API keys in the browser.

## Option 1: Railway (recommended)

### Prerequisites
- A [Railway](https://railway.com) account
- This repo on GitHub

### Steps

1. **Create a new project** on Railway: https://railway.com/new
2. Choose **Deploy from GitHub repo**
3. Select your `MyAgentForge` repo
4. Railway auto-detects the `Dockerfile` and builds it
5. Once deployed, go to **Settings > Networking** and click **Generate Domain**
6. Your app is live at `https://<your-app>.up.railway.app`

### Environment variables (all optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MODE` | `prod` | `mock` / `dev` / `prod` |
| `MAX_REVIEW_ITERATIONS` | `1` | Code review fix loops |
| `SKIP_TESTER` | `false` | Skip the Tester agent |
| `MAX_TOKENS` | `0` | 0 = unlimited |
| `LLM_TIMEOUT` | `60` | Seconds per LLM call |

**No API keys needed** — users bring their own via the UI.

### WebSocket notes

Railway supports WebSockets out of the box. The app auto-detects HTTPS and uses `wss://` for the WebSocket connection.


## Option 2: Docker anywhere

Build and run locally or on any Docker host:

```bash
docker build -t myagentforge .
docker run -p 8000:8000 myagentforge
```

Or with docker-compose:

```bash
docker compose up
```

Works on Fly.io, Render, Google Cloud Run, AWS Fargate, DigitalOcean Apps, etc.

### Fly.io quickstart

```bash
fly launch --no-deploy
fly deploy
```

Fly auto-picks up the `Dockerfile`.


## Option 3: Local Python

```bash
pip install -r requirements.txt
python main.py
```

Then visit http://localhost:8000


## Production checklist

- [x] Dockerfile is multi-stage, non-root user, small image
- [x] Healthcheck endpoint at `/api/health`
- [x] Respects `PORT` env var
- [x] WebSocket uses `--proxy-headers` for accurate IP logging
- [x] Rate limiting enabled (`slowapi`)
- [x] Security headers (CSP, X-Frame-Options, etc.)
- [x] No secrets committed
- [x] `.dockerignore` excludes caches, envs, DBs
- [x] SRI on all CDN scripts


## Custom domain (optional)

On Railway: Settings > Networking > **Add Custom Domain**. Add the CNAME record they give you to your DNS provider. HTTPS is automatic.


## Scaling

The server is **stateless** — you can run multiple instances behind a load balancer with zero coordination. Railway auto-scales within your plan.
