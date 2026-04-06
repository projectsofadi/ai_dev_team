# AI Dev Team

A production-grade, polyglot multi-agent development system that simulates a full
software development team: **Planner**, **Coder**, **Reviewer**, **Tester**, and
**Orchestrator** agents working together to plan, implement, review, and test code.

## Architecture

```
                    ┌──────────────────┐
                    │   CLI / API      │  TypeScript
                    └────────┬─────────┘
                             │ A2A / REST / WebSocket
                    ┌────────┴─────────┐
                    │   Orchestrator   │  Python
                    └──┬───┬───┬───┬──┘
          ┌────────────┤   │   │   ├────────────┐
          ▼            ▼   │   ▼   │            ▼
    ┌──────────┐ ┌────────┐│┌──────────┐ ┌──────────┐
    │ Planner  │ │ Coder  │││ Reviewer │ │ Tester   │
    └──────────┘ └────┬───┘│└──────────┘ └────┬─────┘
                      │    │                   │
              ┌───────┴────┴───────────────────┴──┐
              │         Tools via MCP              │
              │  Shell │ Filesystem │ Git │ Search │
              └────────────────────────────────────┘
```

**Key design decisions:**

- **Custom framework-agnostic** — built from primitives, no dependency on LangChain/CrewAI/etc.
- **Polyglot** — Python core (agents, LLM, tools, memory) + TypeScript (API server, CLI)
- **A2A Protocol** — Agent-to-Agent JSON-RPC 2.0 for external interoperability
- **MCP** — Model Context Protocol for tool integration
- **OpenTelemetry** — GenAI semantic conventions for tracing
- **Provider-agnostic** — supports OpenAI and Anthropic with a unified abstraction

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- An OpenAI or Anthropic API key

### Installation

```bash
# Clone the repo
git clone git@github.com:projectsofadi/ai_dev_team.git
cd ai_dev_team

# Copy environment config
cp .env.example .env
# Edit .env with your API keys

# Install everything
make install
```

### Running a Task (Python CLI)

```bash
cd packages/core
ai-dev-team "Create a Python function that sorts a list using merge sort"
```

### Running the API Server

```bash
# Start the API server
make dev-server

# In another terminal, submit a task
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"description": "Add input validation to the user registration endpoint"}'
```

### Using the TypeScript CLI

```bash
cd packages/cli
npx tsx src/index.ts run "Implement a binary search tree with insert, delete, and search"
npx tsx src/index.ts status
```

### Running Tests

```bash
make test          # Full test suite with coverage
make test-unit     # Unit tests only
```

## Project Structure

```
ai_dev_team/
├── packages/
│   ├── core/                    # Python — Agent framework
│   │   ├── src/ai_dev_team/
│   │   │   ├── agents/          # Orchestrator, Planner, Coder, Reviewer, Tester
│   │   │   ├── llm/             # Provider abstraction (OpenAI + Anthropic)
│   │   │   ├── tools/           # Shell, Filesystem, Git, Search + MCP server
│   │   │   ├── memory/          # Working memory, long-term (ChromaDB), SQLite store
│   │   │   ├── orchestration/   # Engine, ExecutionPlan, task state machine
│   │   │   ├── tracing/         # OpenTelemetry + GenAI semantic conventions
│   │   │   ├── guardrails/      # Validation, budget enforcement
│   │   │   └── config.py        # Settings via pydantic-settings
│   │   └── tests/
│   ├── server/                  # TypeScript — REST + WebSocket + A2A
│   └── cli/                     # TypeScript — CLI interface
├── docker-compose.yml           # API + Jaeger for tracing
├── Makefile                     # Common commands
└── .env.example                 # Configuration template
```

## Agent Roles

| Agent | Role | Tools |
|-------|------|-------|
| **Orchestrator** | Coordinator — decomposes tasks, delegates via handoffs, synthesizes results | Handoff tools (transfer_to_*) |
| **Planner** | Breaks high-level tasks into structured ExecutionPlans with steps & dependencies | create_plan |
| **Coder** | Writes production-ready code following project conventions | filesystem, shell, git, search |
| **Reviewer** | Reviews code for correctness, security, style, performance | filesystem, git, search |
| **Tester** | Writes and runs tests, reports coverage gaps | filesystem, shell, search |

## Configuration

All settings are loaded from environment variables or `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `DEFAULT_PROVIDER` | `openai` | LLM provider: `openai` or `anthropic` |
| `DEFAULT_MODEL` | `gpt-4o` | Default model for OpenAI |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Default model for Anthropic |
| `MAX_AGENT_ITERATIONS` | `25` | Max ReAct loop iterations per agent |
| `MAX_TOKENS_PER_TASK` | `100000` | Token budget per task |
| `AGENT_TIMEOUT_SECONDS` | `300` | Wall-clock timeout per agent run |
| `API_PORT` | `8080` | API server port |
| `API_KEY` | — | API authentication key |
| `MAX_COST_PER_TASK_USD` | `5.00` | Cost ceiling per task |

## API Endpoints

### REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/tasks` | Create a new task |
| `GET` | `/api/tasks` | List all tasks |
| `GET` | `/api/tasks/:id` | Get task details |
| `DELETE` | `/api/tasks/:id` | Delete a task |
| `POST` | `/api/tasks/:id/cancel` | Cancel a running task |

### A2A (Agent-to-Agent)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/a2a/.well-known/agent-card.json` | Agent Card discovery |
| `POST` | `/a2a` | JSON-RPC 2.0 endpoint (SendMessage, GetTask, CancelTask) |

### WebSocket

Connect to `ws://localhost:8080/ws` and send:
```json
{"type": "subscribe", "task_id": "<task-id>"}
```

## Observability

The system uses OpenTelemetry with GenAI semantic conventions:

- **Agent spans**: `agent.run {agent_name}` with task/conversation IDs
- **LLM spans**: `chat {model}` with token usage and finish reasons
- **Tool spans**: `execute_tool {tool_name}` with call IDs

Run Jaeger locally for trace visualization:

```bash
make docker-up
# Open http://localhost:16686
```

## Deployment

See **[DEPLOY.md](DEPLOY.md)** for the full step-by-step deployment guide covering:

- Docker Compose deployment (recommended)
- Bare metal / VM deployment
- Cloud deployment (AWS, DigitalOcean, Fly.io)
- TLS setup, security hardening, monitoring
- How the system interacts with external services (OpenAI, Anthropic, OTLP)
- Complete external interaction map and task flow diagrams

## License

MIT
