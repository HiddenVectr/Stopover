# Stopover

**Hand work between AI coding agents, and give every agent the same picture of you.**

Stopover is a small, self-hosted server with a web dashboard. Agents connect to it through MCP, the protocol they use to call external tools. It gives them two separate features:

- **Handoffs:** save a task in one agent (its goal, decisions, progress and next steps) and continue it in another.
- **Personal memory:** one shared set of your preferences, habits and ongoing context that every connected agent can read and update.

![Claude Code saves a handoff; Codex resumes its goal, decisions, progress, and next steps](docs/images/how-it-works.svg)

Run Stopover on your computer for local use, or share it privately across your devices with Tailscale. It has no accounts or built-in authentication: anyone who can reach it shares access to all handoffs and personal memories.

## Quickstart

You need Git and Docker Engine 28+ with Compose v2, or current Docker Desktop. Docker is needed only on the machine running Stopover.

```sh
git clone https://github.com/HiddenVectr/Stopover.git
cd Stopover
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
```

Open **http://127.0.0.1:8765**. The start command waits for the service to become healthy. The dashboard starts empty. If it does not open, check `docker compose logs --tail=50 stopover`.

## Connect your agent

Choose the command for your agent:

```sh
# Claude Code
claude mcp add --scope user --transport http stopover http://127.0.0.1:8765/mcp

# Codex
codex mcp add stopover --url http://127.0.0.1:8765/mcp
```

Start a fresh agent session. Ask it:

> List my Stopover handoffs without claiming any.

An empty successful result confirms the connection. For Cursor, OMP, Hermes, Muse Code, and other MCP clients, see [client setup](docs/clients.md). The dashboard's **Connect your agents** button also shows the server URL and setup commands.

## Save and resume

In your connected agent, say:

> Save a handoff so I can continue this conversation later.

The agent saves a summary and gives you a prompt such as `Resume Handoff <id>`. Claude Code and Codex can install [short commands](docs/usage.md#short-commands) such as `/stopover-save` and `$stopover-resume`.

Connect your other agent to the same Stopover server, start a fresh session, and paste the prompt. It claims the handoff and continues using the saved context. You can also copy the prompt from the dashboard.

![A handoff in the Stopover dashboard, showing its objective, current state, and next steps](docs/images/handoff-detail.png)

The receiving agent needs access to the project files. Stopover saves summaries rather than full transcripts, does not transfer files, and does not start agents for you. A claim helps coordinate work; it cannot prevent an agent from editing files after its claim expires.

## Personal memory

Handoffs carry one task. Personal memory carries what your agents know about *you*, such as “prefers concise answers” or “uses pnpm, not npm”, so a new agent doesn't start from zero. Memories last until you ask an agent to forget them.

To save what an agent knows about you, say:

> Update my Stopover memory.

In another connected agent, say:

> Import my Stopover memory.

Browse saved memories in **Personal memories** on the dashboard, and ask any agent to correct or forget one. See [personal memory](docs/memory.md) for what is saved and how forgetting works.

## Keep your data private

The supplied Compose file publishes Stopover on localhost. **Do not expose this deployment to the public internet.** For access from your other devices, use [Tailscale Serve with restricted access rules](docs/remote-http.md).

Do not save credentials or secrets. Context an agent reads may be sent to that agent's model provider.

Handoffs and memories survive container restarts in the Docker volume. **`docker compose down -v` deletes that volume.** See [operations](docs/operations.md) for backups, restore, and updates.

## More information

- [Using Stopover](docs/usage.md): saving, finding and resuming handoffs.
- [Personal memory](docs/memory.md): sharing your preferences and context between agents.
- [Client setup](docs/clients.md): commands and configuration for each agent.
- [API reference](docs/api.md): tool contracts, retries, claims, and pagination.
- [Operations](docs/operations.md): storage, configuration, backups, and retention.
- [Tailscale deployment](docs/remote-http.md): private access across devices.
- [Implementation](docs/implementation.md): how Stopover works inside.
- [Changelog](CHANGELOG.md): changes and upgrade notes.
- [Security policy](SECURITY.md): how to report a vulnerability privately, and what Stopover does and doesn't protect.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

On Windows, use executables in `.venv\Scripts\`. See [local development](docs/implementation.md#local-development) for running without Docker and regenerating screenshots.

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Stopover is pre-1.0: a minor release can include breaking changes, always marked in the [changelog](CHANGELOG.md), and only the latest release gets fixes.

## License

[Apache License 2.0](LICENSE).
