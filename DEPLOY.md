# Docker Demo Guide

This repository is an experimental reference implementation. The included
Docker Compose file is for a local, disposable demonstration only. It is not a
production deployment recipe.

## Safety boundary

The HTTP gateway deliberately forces write and shell approvals on for every
Python child. Because the gateway does not yet implement an interactive
approval transport, REST and A2A tasks cannot approve filesystem mutations,
Git operations, or shell execution. They can still call an external model and
return planning/review output.

Do not mount a personal checkout, credential directory, home directory, Docker
socket, production repository, or host root into `/workspace`.

## Components

```text
host 127.0.0.1:8080 -> Node API (REST/A2A/WebSocket)
                    |
                    | isolated Python subprocess, one at a time
                    v
              Python agent core -> model provider API
                    |
                    v
             named /workspace volume
```

Task records are in memory. Restarting the API loses them. This demo does not
provide a durable queue, transactional rollback, multi-tenant isolation,
horizontal scaling, or a production authorization model.

## Start the demo

Create `.env` at the repository root:

```dotenv
API_KEY=replace-with-a-long-random-value
A2A_PUBLIC_URL=http://127.0.0.1:8080/a2a
OPENAI_API_KEY=replace-with-a-provider-key
DEFAULT_PROVIDER=openai
CORS_ORIGINS=http://localhost:3000
TASK_TIMEOUT_MS=300000
```

Generate `API_KEY` with a password manager or `openssl rand -hex 32`. Never
commit `.env`.

Then run:

```bash
docker compose up --build
```

Verify the unauthenticated liveness endpoint:

```bash
curl http://127.0.0.1:8080/health
```

Submit an authenticated read-only task:

```bash
curl -X POST http://127.0.0.1:8080/api/tasks \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"description":"Summarize the architecture and its limitations"}'
```

## Enforced controls

- Startup fails when `API_KEY` is absent or still the placeholder.
- REST, POST `/a2a`, and WebSocket require the API key. The public
  `/.well-known/agent-card.json` discovery document contains no credential or
  private task data and explicitly advertises an experimental, non-v1 `0.0`
  protocol surface.
- Browser origins are denied unless listed exactly in `CORS_ORIGINS`.
- WebSocket frames and per-client subscriptions are bounded.
- One Python task may use the shared workspace at a time.
- Each child has a server deadline and bounded captured output.
- Task descriptions travel over stdin, not process arguments.
- Python isolated mode and a trusted working directory prevent workspace module
  shadowing before the bridge starts.
- The child receives a curated environment without the server API key.
- Tool subprocesses receive a further reduced environment without model keys.
- Workspace path checks use resolved path containment rather than string
  prefixes.

These are defense-in-depth controls, not a sandbox certification.

Task descriptions and any workspace content selected by an agent may be sent to
the configured model provider. Use only non-sensitive, disposable material and
review the provider's data-handling terms before running the demo.

## Stop and remove demo state

```bash
docker compose down
```

Docker named volumes are retained by default. Review them yourself before using
`docker compose down -v`; `-v` deletes the demo workspace and trace data.

## What is intentionally absent

There is deliberately no reverse-proxy service in the Compose file. There are
no instructions here for public ingress, TLS termination, cloud
deployment, systemd, production secrets, or disabling approval gates. Those
require a different architecture with durable task storage, isolated workspace
per task, an approval protocol, audit records, stronger process containment,
and an explicit threat model.
