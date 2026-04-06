# Deployment Guide

Full step-by-step guide to deploy the AI Dev Team system on a server and
understand how it interacts with the outside world.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [External Interaction Map](#2-external-interaction-map)
3. [Prerequisites](#3-prerequisites)
4. [Option A: Docker Compose (Recommended)](#4-option-a-docker-compose)
5. [Option B: Bare Metal / VM](#5-option-b-bare-metal--vm)
6. [Option C: Cloud Deployment](#6-option-c-cloud-deployment)
7. [Post-Deployment Verification](#7-post-deployment-verification)
8. [Security Hardening](#8-security-hardening)
9. [Monitoring and Observability](#9-monitoring-and-observability)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. System Overview

The AI Dev Team is a multi-process system with three runtime components:

```
┌────────────────────────────────────────────────────────────────────┐
│                        YOUR SERVER                                 │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Nginx (reverse proxy)               :80 / :443            │   │
│  │  ─ TLS termination                                         │   │
│  │  ─ Rate limiting                                           │   │
│  │  ─ WebSocket upgrade                                       │   │
│  └────────────────────┬────────────────────────────────────────┘   │
│                       │                                            │
│  ┌────────────────────▼────────────────────────────────────────┐   │
│  │  API Server (Node.js/Express)        :8080 (internal)      │   │
│  │  ─ REST API      POST /api/tasks                           │   │
│  │  ─ A2A endpoint  POST /a2a (JSON-RPC 2.0)                 │   │
│  │  ─ WebSocket     ws://…/ws                                 │   │
│  │  ─ Agent Card    GET /a2a/.well-known/agent-card.json      │   │
│  └────────────────────┬────────────────────────────────────────┘   │
│                       │ spawns / calls                              │
│  ┌────────────────────▼────────────────────────────────────────┐   │
│  │  Python Agent Core                                         │   │
│  │  ─ Orchestrator → Planner → Coder → Reviewer → Tester     │   │
│  │  ─ MCP Tool Server (stdio)                                 │   │
│  │  ─ SQLite (./data/state.db)                                │   │
│  │  ─ ChromaDB (./data/chroma/)                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Jaeger (optional)                   :16686 (UI)           │   │
│  │  ─ Receives OTLP traces on :4317                           │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────┘
```

### What runs where

| Component | Runtime | Exposed Port | Purpose |
|-----------|---------|-------------|---------|
| Nginx | Container | 80, 443 | Reverse proxy, TLS, rate limiting |
| API Server | Node.js 22 | 8080 (internal) | REST, A2A, WebSocket |
| Agent Core | Python 3.11+ | None (internal) | LLM agents, tool execution |
| MCP Server | Python (stdio) | None (pipe) | Exposes tools to agents |
| Jaeger | Container | 16686 (UI), 4317 (OTLP) | Trace collection and UI |
| SQLite | File | None | Task state persistence |
| ChromaDB | Embedded | None | Long-term vector memory |

---

## 2. External Interaction Map

The system communicates with the outside world through these channels:

```
                         INBOUND                              OUTBOUND
                    (things calling you)                  (things you call)

    ┌─────────────┐                         ┌────────────────────────┐
    │ Your App /  │──── REST API ──────────>│                        │
    │ Frontend    │<─── JSON responses ─────│                        │
    │             │──── WebSocket ──────────>│                        │
    │             │<─── streaming events ───│                        │
    └─────────────┘                         │                        │
                                            │    AI Dev Team         │
    ┌─────────────┐                         │    Server              │───> OpenAI API
    │ Other AI    │──── A2A JSON-RPC ──────>│                        │───> Anthropic API
    │ Agents      │<─── A2A responses ──────│    :80/:443            │───> (OTLP endpoint)
    └─────────────┘                         │                        │
                                            │                        │
    ┌─────────────┐                         │                        │
    │ CLI         │──── REST API ──────────>│                        │
    │ (remote)    │<─── JSON + WebSocket ───│                        │
    └─────────────┘                         └────────────────────────┘
```

### 2.1 Inbound connections (what calls your server)

| Interface | Protocol | Path | Auth | Purpose |
|-----------|----------|------|------|---------|
| REST API | HTTP/JSON | `POST /api/tasks` | API key (Bearer / X-Api-Key) | Submit development tasks |
| REST API | HTTP/JSON | `GET /api/tasks` | API key | List all tasks |
| REST API | HTTP/JSON | `GET /api/tasks/:id` | API key | Get task status |
| REST API | HTTP/JSON | `DELETE /api/tasks/:id` | API key | Delete a task |
| REST API | HTTP/JSON | `POST /api/tasks/:id/cancel` | API key | Cancel a running task |
| A2A | JSON-RPC 2.0 | `POST /a2a` | None (add your own) | Agent-to-agent communication |
| Agent Card | HTTP/JSON | `GET /a2a/.well-known/agent-card.json` | None | Agent discovery (A2A spec) |
| WebSocket | WS/WSS | `ws://…/ws` | None (add your own) | Real-time task streaming |
| Health | HTTP | `GET /health` | None | Load balancer health checks |

### 2.2 Outbound connections (what your server calls)

| Destination | Protocol | When | Configurable via |
|-------------|----------|------|------------------|
| OpenAI API (`api.openai.com`) | HTTPS | Every LLM call when provider=openai | `OPENAI_API_KEY` |
| Anthropic API (`api.anthropic.com`) | HTTPS | Every LLM call when provider=anthropic | `ANTHROPIC_API_KEY` |
| OTLP Collector (`localhost:4317`) | gRPC | Every traced operation | `OTEL_EXPORTER_OTLP_ENDPOINT` |

### 2.3 Local I/O (on-disk)

| Path | Type | Purpose |
|------|------|---------|
| `./data/state.db` | SQLite file | Task state, events, agent logs |
| `./data/chroma/` | Directory | ChromaDB vector embeddings |
| Shell commands | Subprocess | Coder/Tester agents run shell via `asyncio.create_subprocess_shell` |
| Filesystem | Direct I/O | Coder agent reads/writes project files |
| Git | Subprocess | Coder agent runs git commands |

### 2.4 How a task flows through the system

```
1. Client sends POST /api/tasks {"description": "Add login page"}
                │
2. API Server creates task record, returns task ID
                │
3. API Server spawns Python agent pipeline:
                │
    ┌───────────▼──────────────┐
    │  Orchestrator            │
    │  "I need to plan this"   │
    │          │                │
    │  ┌───────▼─────────┐     │
    │  │ Planner          │    │──── LLM call (OpenAI/Anthropic) ────> Internet
    │  │ Creates plan     │    │<─── structured plan response ────────
    │  └───────┬─────────┘     │
    │          │                │
    │  ┌───────▼─────────┐     │
    │  │ Coder            │    │──── LLM call ────> Internet
    │  │ Writes code      │    │──── filesystem.write("login.tsx") ──> Disk
    │  │ Runs commands    │    │──── shell("npm test") ──────────────> Subprocess
    │  └───────┬─────────┘     │
    │          │                │
    │  ┌───────▼─────────┐     │
    │  │ Reviewer         │    │──── LLM call ────> Internet
    │  │ Reviews diff     │    │──── git diff ────> Subprocess
    │  │ APPROVED/CHANGES │    │──── search("pattern") ─────────────> ripgrep
    │  └───────┬─────────┘     │
    │          │                │
    │  ┌───────▼─────────┐     │
    │  │ Tester           │    │──── LLM call ────> Internet
    │  │ Writes tests     │    │──── shell("pytest") ───────────────> Subprocess
    │  │ Reports results  │    │
    │  └───────┬─────────┘     │
    │          │                │
    │  Result returned         │
    └──────────────────────────┘
                │
4. Task state updated in SQLite
                │
5. WebSocket broadcasts {"type":"task_update","data":{"state":"completed"}}
                │
6. Client polls GET /api/tasks/:id or receives WebSocket event
```

---

## 3. Prerequisites

On the target server:

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| OS | Ubuntu 22.04 / Debian 12 / macOS 14 | Ubuntu 24.04 |
| CPU | 2 cores | 4+ cores |
| RAM | 2 GB | 4+ GB |
| Disk | 10 GB | 20+ GB (for ChromaDB embeddings) |
| Docker | 24.0+ | Latest |
| Docker Compose | v2.20+ | Latest |

If deploying bare metal (no Docker):

| Requirement | Version |
|------------|---------|
| Python | 3.11+ |
| Node.js | 20+ |
| npm | 10+ |
| ripgrep | 14+ |
| git | 2.30+ |

You also need:
- An **OpenAI API key** and/or **Anthropic API key**
- A **domain name** (for production TLS)
- Outbound HTTPS access to `api.openai.com` and/or `api.anthropic.com`

---

## 4. Option A: Docker Compose

The recommended deployment method. Everything runs in containers.

### Step 1: Clone and configure

```bash
# On your server
git clone git@github.com:projectsofadi/ai_dev_team.git
cd ai_dev_team

# Create environment config
cp .env.example .env
```

### Step 2: Edit `.env`

```bash
nano .env
```

Set at minimum:

```
OPENAI_API_KEY=sk-your-real-key-here
API_KEY=a-strong-random-string-for-api-auth
API_PORT=8080
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

Generate a strong API key:

```bash
openssl rand -hex 32
```

### Step 3: Start services (development mode)

```bash
docker compose up -d
```

This starts:
- **API server** on port 8080
- **Jaeger** UI on port 16686

### Step 4: Start with Nginx (production mode)

```bash
docker compose --profile production up -d
```

This adds Nginx on ports 80/443 in front of the API.

### Step 5: Verify

```bash
# Health check
curl http://localhost:8080/health

# Submit a task
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"description": "Create a hello world Python script"}'

# Check Jaeger traces
open http://localhost:16686
```

### Step 6: Set up TLS (production)

Using Let's Encrypt with certbot:

```bash
# Install certbot on host
sudo apt install certbot

# Get certificate
sudo certbot certonly --standalone -d your-domain.com

# Copy certs to project
mkdir -p certs
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem certs/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem certs/

# Edit nginx.conf: uncomment the HTTPS server block, set server_name
# Edit nginx.conf: uncomment the HTTP->HTTPS redirect

# Restart
docker compose --profile production restart nginx
```

### Step 7: Auto-renew certs

```bash
# Add to crontab
echo "0 3 * * * certbot renew --quiet && docker compose --profile production restart nginx" | sudo tee -a /etc/cron.d/certbot-renew
```

---

## 5. Option B: Bare Metal / VM

For when you want to run directly on the OS without Docker.

### Step 1: Install system dependencies

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  nodejs npm \
  ripgrep git curl

# macOS
brew install python@3.11 node ripgrep git
```

### Step 2: Clone and set up

```bash
git clone git@github.com:projectsofadi/ai_dev_team.git
cd ai_dev_team

cp .env.example .env
nano .env  # fill in API keys
```

### Step 3: Create Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 4: Install packages

```bash
# Python core
cd packages/core
pip install -e .
cd ../..

# API server
cd packages/server
npm install
cd ../..

# CLI (optional)
cd packages/cli
npm install
cd ../..
```

### Step 5: Create data directory

```bash
mkdir -p data
```

### Step 6: Start the API server

```bash
source .venv/bin/activate
cd packages/server
npm run dev
```

Or for production:

```bash
cd packages/server
npm run build
node dist/index.js
```

### Step 7: Run as a systemd service (Linux)

Create `/etc/systemd/system/ai-dev-team.service`:

```ini
[Unit]
Description=AI Dev Team API Server
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/ai_dev_team/packages/server
EnvironmentFile=/opt/ai_dev_team/.env
ExecStart=/usr/bin/node dist/index.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-dev-team
sudo systemctl start ai-dev-team
sudo systemctl status ai-dev-team
```

### Step 8: Put Nginx in front

```bash
sudo apt install nginx

# Copy the provided nginx.conf or create a site config
sudo cp nginx.conf /etc/nginx/nginx.conf
sudo nginx -t
sudo systemctl restart nginx
```

---

## 6. Option C: Cloud Deployment

### AWS (EC2 + Docker)

```bash
# 1. Launch an EC2 instance (t3.medium or larger, Ubuntu 24.04)
# 2. Open security group ports: 80, 443, 22
# 3. SSH in and install Docker:
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Log out and back in

# 4. Follow Docker Compose steps above (Option A)
```

### DigitalOcean (Droplet + Docker)

```bash
# 1. Create a Droplet (4GB RAM, Ubuntu 24.04, Docker pre-installed)
# 2. SSH in
# 3. Follow Docker Compose steps above (Option A)
```

### Railway / Render / Fly.io

These platforms can deploy the server directly:

```bash
# Fly.io example
fly launch --dockerfile packages/server/Dockerfile
fly secrets set OPENAI_API_KEY=sk-...
fly secrets set API_KEY=$(openssl rand -hex 32)
fly secrets set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
fly deploy
```

### Key cloud considerations

- Set `API_HOST=0.0.0.0` (already the default)
- Ensure outbound HTTPS is allowed (for OpenAI/Anthropic API calls)
- Mount a persistent volume for `./data/` (SQLite + ChromaDB)
- Set `API_KEY` to a strong random value
- Use the cloud provider's managed TLS/load balancer instead of Nginx

---

## 7. Post-Deployment Verification

Run through this checklist after deploying:

### 7.1 Health check

```bash
curl https://your-domain.com/health
# Expected: {"status":"ok","service":"ai-dev-team","version":"0.1.0"}
```

### 7.2 Auth works

```bash
# Should fail without key
curl -s https://your-domain.com/api/tasks | jq
# Expected: {"error":"Unauthorized: invalid or missing API key"}

# Should succeed with key
curl -s https://your-domain.com/api/tasks \
  -H "Authorization: Bearer YOUR_API_KEY" | jq
# Expected: {"tasks":[],"total":0}
```

### 7.3 Task submission

```bash
TASK=$(curl -s -X POST https://your-domain.com/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"description": "Print hello world"}')
echo $TASK | jq
TASK_ID=$(echo $TASK | jq -r '.id')
```

### 7.4 A2A agent discovery

```bash
curl -s https://your-domain.com/a2a/.well-known/agent-card.json | jq
# Expected: Agent Card with name, skills, supportedInterfaces
```

### 7.5 A2A message

```bash
curl -s -X POST https://your-domain.com/a2a \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "test-001",
        "role": "ROLE_USER",
        "parts": [{"text": "Build a calculator"}]
      }
    }
  }' | jq
```

### 7.6 WebSocket

```bash
# Using websocat (install: cargo install websocat)
echo '{"type":"ping"}' | websocat ws://your-domain.com/ws
# Expected: {"type":"pong","data":{"timestamp":...},...}
```

### 7.7 Jaeger traces

Open `http://your-server:16686` in a browser. Select service "ai-dev-team"
from the dropdown and search for traces.

---

## 8. Security Hardening

### 8.1 Required for production

| Action | How |
|--------|-----|
| Set a strong API key | `API_KEY=$(openssl rand -hex 32)` in `.env` |
| Enable TLS | See Step 6 in Docker Compose section |
| Restrict Jaeger access | Remove `16686:16686` from docker-compose ports or firewall it |
| Restrict OTLP port | Remove `4317:4317` and `4318:4318` from public access |
| Set file permissions | `chmod 600 .env` |
| Use non-root user | Already handled in Docker; for bare metal, create a `deploy` user |

### 8.2 Firewall rules (ufw)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable
```

### 8.3 API key rotation

```bash
# Generate new key
NEW_KEY=$(openssl rand -hex 32)

# Update .env
sed -i "s/^API_KEY=.*/API_KEY=$NEW_KEY/" .env

# Restart
docker compose restart api
```

### 8.4 LLM key security

- Never commit `.env` to git (already in `.gitignore`)
- Use Docker secrets or a vault (HashiCorp Vault, AWS Secrets Manager) in production
- Rotate API keys periodically
- The guardrails module scans outputs for leaked keys before returning them

### 8.5 Shell execution safety

The Coder and Tester agents can execute shell commands. In production:

```bash
# In .env — require human approval for shell commands
REQUIRE_APPROVAL_FOR_SHELL=true
REQUIRE_APPROVAL_FOR_WRITES=true
```

You can also restrict allowed commands by configuring `ShellTool(allowed_commands=[...])`.

---

## 9. Monitoring and Observability

### 9.1 Traces (Jaeger)

Every agent run produces OpenTelemetry spans:

```
agent.run orchestrator
├── chat gpt-4o                   ← LLM call with token usage
├── execute_tool transfer_to_planner
│   └── agent.run planner
│       ├── chat gpt-4o
│       └── execute_tool create_plan
├── execute_tool transfer_to_coder
│   └── agent.run coder
│       ├── chat gpt-4o
│       ├── execute_tool filesystem   ← file write
│       ├── chat gpt-4o
│       └── execute_tool shell        ← command execution
...
```

Access Jaeger at `http://your-server:16686`.

### 9.2 Structured logs

The API server logs every request as JSON:

```json
{
  "trace_id": "abc-123",
  "method": "POST",
  "path": "/api/tasks",
  "status": 201,
  "duration_ms": 45,
  "timestamp": "2026-04-06T12:00:00.000Z"
}
```

View with: `docker compose logs -f api`

### 9.3 Key metrics to watch

| Metric | Where | Alert threshold |
|--------|-------|----------------|
| Task completion rate | SQLite query on tasks table | < 80% |
| Avg tokens per task | Agent logs in SQLite | > 50,000 |
| LLM API latency | Jaeger span durations | > 30s |
| Error rate | API server logs | > 5% |
| Disk usage (ChromaDB) | `du -sh data/chroma/` | > 80% disk |
| Container health | `docker compose ps` | Any unhealthy |

### 9.4 Alerting

For production, pipe logs to your monitoring stack:

```yaml
# docker-compose.override.yml
services:
  api:
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"
```

Or send to Datadog/Grafana Cloud/etc. via the OTLP exporter.

---

## 10. Troubleshooting

### "Connection refused" on port 8080

```bash
# Check if container is running
docker compose ps

# Check logs
docker compose logs api

# Common fix: make sure .env exists and has valid values
```

### LLM calls failing

```bash
# Test API key directly
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"

# Check outbound connectivity
curl -I https://api.openai.com
```

### SQLite "database is locked"

This happens with concurrent writes. The system uses `aiosqlite` which
serializes writes. If you see this:

```bash
# Stop all services
docker compose down

# Remove stale lock
rm -f data/state.db-wal data/state.db-shm

# Restart
docker compose up -d
```

### ChromaDB out of memory

ChromaDB loads embeddings into RAM. If the server runs out:

```bash
# Check memory usage
docker stats

# Increase container memory or clear old embeddings
docker compose exec api python3 -c "
import chromadb
c = chromadb.PersistentClient(path='/app/data/chroma')
# List collections and their sizes
for col in c.list_collections():
    print(f'{col.name}: {col.count()} documents')
"
```

### WebSocket connections dropping

```bash
# Check Nginx timeout (should be high for long-running tasks)
# In nginx.conf, verify:
#   proxy_read_timeout 86400s;

# Test WebSocket connectivity
websocat ws://localhost:8080/ws
```

### Container won't build

```bash
# Clean Docker cache
docker compose build --no-cache

# Check Dockerfile syntax
docker build -f packages/server/Dockerfile .
```

---

## Quick Reference

### Start everything
```bash
docker compose --profile production up -d
```

### Stop everything
```bash
docker compose --profile production down
```

### View logs
```bash
docker compose logs -f api          # API server
docker compose logs -f jaeger       # Jaeger
docker compose logs -f nginx        # Nginx
```

### Submit a task
```bash
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"description": "Your task here"}'
```

### Run Python agents directly (without API server)
```bash
source .venv/bin/activate
ai-dev-team "Your task description here"
```

### Run MCP tool server (for external MCP clients)
```bash
source .venv/bin/activate
python -m ai_dev_team.tools.mcp_server
```

### Update to latest version
```bash
git pull
docker compose build
docker compose --profile production up -d
```
