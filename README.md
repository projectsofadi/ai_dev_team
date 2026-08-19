# AI Dev Team

An experimental reference implementation of a multi-agent software-development
workflow. It contains Planner, Coder, Reviewer, Tester, and Orchestrator agents,
a Python runtime, and a TypeScript REST/A2A/WebSocket gateway.

> **Status: prototype, not production-ready.** Run it only against a dedicated,
> disposable workspace. The tool controls are guardrails, not a hermetic sandbox;
> an approved interpreter or build tool can execute arbitrary project code.

## What works today

- The Python CLI runs the multi-agent orchestrator against OpenAI or Anthropic.
- REST and A2A submissions dispatch to the Python core through a no-shell
  subprocess bridge.
- REST, A2A task methods, and WebSocket interfaces share API-key
  authentication; the discovery card is intentionally public.
- REST/A2A task transitions are broadcast to subscribed WebSocket clients.
- Filesystem tools resolve paths inside a configured workspace and reject sibling
  prefix/path-traversal escapes.
- Tool arguments and outputs are validated; likely secret-bearing output is
  blocked before it is returned to the model.
- Write and shell approvals fail closed by default when no approval callback is
  available.
- The agent loop tracks token, iteration, wall-clock, and estimated-cost budgets
  and refuses another provider call once measured usage reaches a limit.

## Known limitations

- Task records are held in memory and are lost when the API process restarts.
- The HTTP gateway permits one local Python subprocess in the shared workspace;
  concurrent submissions fail rather than queue. There is no distributed queue,
  retry worker, or multi-node coordination.
- Cancellation waits for process exit and escalates from `SIGTERM` to `SIGKILL`,
  but it is not a transactional rollback of changes an approved tool may already
  have made.
- A2A support is a deliberately small, experimental JSON-RPC subset. Its card
  advertises protocol version `0.0`, not A2A v1 conformance, because mandatory
  v1 operations such as `ListTasks` are not implemented.
- The approval callback is available in the Python core, but the HTTP API does
  not yet expose an interactive approval UI/transport. With safe defaults,
  the gateway forces write and shell approvals on, so HTTP-submitted mutations
  are refused in this release.
- OpenTelemetry helpers and storage components exist, but coverage is incomplete
  across the full Node-to-Python path.
- Model output is nondeterministic and must be reviewed like any other generated
  code.
- Token and cost limits are post-response safeguards, not billing guarantees. A
  single in-flight provider call can overshoot them, and cost figures use static
  estimates rather than provider invoices.
- Task descriptions and workspace content selected by an agent can be sent to
  the configured model provider. Use only non-sensitive, disposable material
  and review that provider's data-handling terms.

## Architecture

```text
CLI / REST / A2A
        |
        v
TypeScript API -- authenticated WebSocket updates
        |
        | spawn(argv), never a shell
        v
Python bridge -> Orchestrator -> Planner / Coder / Reviewer / Tester
                                      |
                                      v
                         dedicated workspace tools
```

The REST and A2A adapters share the same in-memory task registry. The gateway
passes the task ID as an argument, sends the description over stdin, starts
Python in isolated import mode from a trusted directory, and accepts only a
matching terminal result from the bridge.

Direct CLI task descriptions are ordinary process arguments and may be visible
to other local users through process inspection. Never place credentials or
private source text in a CLI argument.

## Prerequisites

- Python 3.11+
- Node.js 22+
- An OpenAI or Anthropic API key
- A dedicated directory that the agents are allowed to inspect

## Local setup

```bash
git clone git@github.com:projectsofadi/ai_dev_team.git
cd ai_dev_team

python3 -m venv .venv
. .venv/bin/activate
pip install -e "packages/core[dev]"
npm ci --prefix packages/server
npm ci --prefix packages/cli

mkdir -p workspace
export API_KEY="$(openssl rand -hex 32)"
export AGENT_WORKSPACE="$PWD/workspace"
export OPENAI_API_KEY="your-provider-key"
export DEFAULT_PROVIDER="openai"

npm run dev --prefix packages/server
```

The API listens on `127.0.0.1:8080` unless `API_HOST` is set. Cross-origin browser
requests are denied unless their exact origins are listed in the comma-separated
`CORS_ORIGINS` variable.

Submit a task:

```bash
curl -X POST http://127.0.0.1:8080/api/tasks \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"description":"Explain the files in this workspace"}'
```

Or use the TypeScript CLI:

```bash
export AI_DEV_TEAM_API_KEY="$API_KEY"
npm run dev --prefix packages/cli -- \
  run --watch "Explain the files in this workspace"
```

## Approval behavior

These defaults are intentional:

```dotenv
REQUIRE_APPROVAL_FOR_WRITES=true
REQUIRE_APPROVAL_FOR_SHELL=true
```

Without an approval callback, relevant calls are denied and never executed. The
HTTP bridge always enforces both settings and currently has no approval
transport. Library users can embed the Python agents with an explicit approval
callback, but that capability is intentionally not exposed by the server.

## API surface

All stateful endpoints require `Authorization: Bearer <API_KEY>` or an
`X-Api-Key` header. WebSocket authentication uses the Authorization header.
`/health` and the discovery card are public; the card contains no credential or
private task data.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/api/tasks` | Submit and dispatch a task |
| `GET` | `/api/tasks` | List in-memory task records |
| `GET` | `/api/tasks/:id` | Read task status |
| `DELETE` | `/api/tasks/:id` | Delete a non-running record |
| `POST` | `/api/tasks/:id/cancel` | Terminate a running subprocess |
| `GET` | `/.well-known/agent-card.json` | Public experimental discovery card |
| `POST` | `/a2a` | Authenticated JSON-RPC subset |
| `WS` | `/ws` | Authenticated task subscriptions |

## Verification

```bash
pytest -q packages/core/tests
ruff check packages/core/src packages/core/tests
ruff format --check packages/core/src packages/core/tests
mypy --config-file packages/core/pyproject.toml packages/core/src/ai_dev_team
npm test --prefix packages/server
npm test --prefix packages/cli
python -m build packages/core
```

CI runs the same Python and TypeScript gates. See [DEPLOY.md](DEPLOY.md) for the
Docker prototype and its security constraints.

## Project layout

```text
packages/core/    Python agents, providers, tools, memory, guardrails, bridge
packages/server/  REST, A2A, WebSocket gateway and subprocess task runner
packages/cli/     TypeScript client
```

## Security reporting

Do not include real credentials, private source code, or production data in an
issue. Rotate any credential that may have been exposed and provide a minimal,
redacted reproduction.

## License

MIT — see [LICENSE](LICENSE).
