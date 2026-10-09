# Baton

**Pass work between AI coding agents.** Baton is a small, self-hosted MCP server that gives Claude Code, Codex, Cursor, Oh My Pi (OMP), Hermes Agent and any other MCP client one shared inbox. Say "save a handoff" in one agent, then "Resume Handoff `<id>`" in another, and the second agent picks up with your goal, decisions, progress and next steps.

![Claude Code saves a handoff to Baton's inbox; later, Codex resumes it by ID and continues with the goal, decisions and next steps](docs/images/how-it-works.svg)

- **One container, no accounts.** Docker runs the MCP server and a web dashboard, with SQLite in a persistent volume. Clients connect by URL; they need no Docker, Python, token or login.
- **Safe ownership.** Agents claim a handoff before working on it, so two agents don't pick up the same task, and retries never create duplicates.
- **Personal memory that travels.** Ask any agent to "update my Baton memory", then "import my Baton memory" in another, and your preferences and project context come along.
- **Private by default.** Listens on loopback only, makes no outbound calls and sends no telemetry. Share it across devices with Tailscale.

## Quickstart

Requires Docker Engine 28+ (or current Docker Desktop) with Compose.

```sh
git clone https://github.com/HiddenVectr/Baton.git
cd Baton
docker compose up --build -d
```

**1. Open the dashboard** at **http://127.0.0.1:8765**. It's empty until your first handoff.

**2. Connect an agent.** For Claude Code:

```sh
claude mcp add --scope user --transport http baton http://127.0.0.1:8765/mcp
```

The dashboard's **Connect your agents** button shows the commands for each client, with your server's URL filled in. Start a fresh agent session afterwards; in Claude Code, `/mcp` should list `baton` as connected.

**3. Save a handoff.** In that agent, say:

> Save a handoff so I can continue this conversation later.

It saves a summary and replies with a prompt like `Resume Handoff 3f2a9c1e-…`, and the handoff appears in the dashboard.

**4. Resume it anywhere.** Paste that prompt into a fresh session of any connected agent. It claims the task and continues where the last one stopped.

![The Baton dashboard: a list of handoffs with their status, project and agents, and the selected handoff's objective, current state and next steps](docs/images/handoff-detail.png)

## How it works

| Concept | What it is |
| --- | --- |
| **Handoff** | A saved summary of a task: objective, background, requirements, decisions and reasons, progress, failed attempts, open questions, references, next steps and acceptance criteria. The agent builds it from its conversation; you don't fill in fields. Records are immutable; corrections are new handoffs linked by `parent_id`. |
| **Claim** | A lease (1 hour by default) that marks who is working on a handoff. Resuming claims it; completing records `succeeded` (with evidence for each acceptance criterion), `blocked` or `abandoned`. |
| **Personal memory** | One shared collection of facts about you, with topic keys, revisions and provenance, so agents can sync it without overwriting each other. |
| **Prompts** | Optional shortcuts, such as `/mcp__baton__save`, `/mcp__baton__resume <id>` and `/mcp__baton__inbox` in Claude Code. Plain-language requests work everywhere. |
| **Dashboard** | A read-only web view to search and filter handoffs, read their full context and history, browse memories and copy resume prompts. |

Baton transfers context, not the workspace: it does not launch agents, copy project files, or sync agents' own memory files. The receiving agent needs its own access to the project.

Details: [Using Baton](docs/usage.md) covers the workflows, prompts, dashboard and the exact tool contracts.

## Connect your agents

![The Connect your agents dialog in the dashboard, with the MCP URL and ready-to-paste commands for Codex and Claude Code](docs/images/connect-dialog.png)

Every client uses the same settings: transport **Streamable HTTP**, URL **`http://127.0.0.1:8765/mcp`**, authentication **None**.

| Client | Command or config |
| --- | --- |
| Claude Code | `claude mcp add --scope user --transport http baton http://127.0.0.1:8765/mcp` |
| Codex | `codex mcp add baton --url http://127.0.0.1:8765/mcp` |
| Hermes Agent | `hermes mcp add baton --url http://127.0.0.1:8765/mcp` |
| Cursor | Add [clients/cursor.json](clients/cursor.json) to `~/.cursor/mcp.json` |
| OMP | Add [clients/omp.json](clients/omp.json) to `~/.omp/agent/mcp.json` |
| Muse Code (Meta) | Add [clients/muse-code.json](clients/muse-code.json) to `~/.config/muse/settings.json` |
| Other | Add a Streamable HTTP server named `baton` with the URL above ([example](clients/generic-http.json)) |

See [Connect an AI harness](docs/clients.md) for config files, verification and troubleshooting. To use Baton from other devices, publish it on your tailnet with `tailscale serve` and use the HTTPS URL plus `/mcp`; see [Tailscale deployment](docs/remote-http.md).

## Security

Baton has **no authentication**: anyone who can reach it can read and change the shared inbox. It is built for one person or a trusted team on a private network.

- Compose publishes the port on `127.0.0.1` only. For remote access, use Tailscale Serve with restricted access rules. **Do not expose it to the public internet.**
- It only answers requests whose `Host` is `localhost`, `127.0.0.1`, `::1` or a `*.ts.net` name (extend with `BATON_ALLOWED_HOSTS`), and rejects cross-site browser requests, which blocks DNS-rebinding and drive-by attacks from web pages.
- It makes no outbound calls and has no telemetry, filesystem mount or Docker socket.
- Anything an agent reads from Baton can reach that agent's model provider. Don't put secrets in handoffs or memories.

See [Operating Baton](docs/operations.md) for the full security model.

## Documentation

| Guide | Covers |
| --- | --- |
| [Connect an AI harness](docs/clients.md) | Setup for each client, verification, troubleshooting |
| [Using Baton](docs/usage.md) | Handoff and memory workflows, prompts, dashboard, tool contracts |
| [Operating Baton](docs/operations.md) | Configuration, storage, backup, retention, import/export, security model |
| [Tailscale deployment](docs/remote-http.md) | Hosting Baton privately for your other devices |
| [Implementation notes](docs/implementation.md) | Architecture, extension points, verification |
| [CHANGELOG.md](CHANGELOG.md) | Release notes and upgrade steps |

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe`. Tests use isolated temporary stores and cover retry safety, simultaneous claims, lease fencing, rollback, durability, real HTTP and stdio MCP round trips, host and cross-site checks, and the dashboard in a real browser (including mobile layout and hostile text).

Run without Docker:

```sh
.venv/bin/python -m baton --data-dir ./data serve --host 127.0.0.1 --port 8765
```

Regenerate the documentation screenshots with `.venv/bin/python scripts/screenshots.py`, which fills a throwaway server with synthetic data.

Never run two servers against the same data directory. Production packages are pinned in `requirements.lock` and the Docker base image by digest. The server uses the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

## License

Baton is licensed under the [Apache License 2.0](LICENSE).
