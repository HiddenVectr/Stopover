# Handoff

A shared inbox for carrying tasks between **AI harnesses that support MCP**, including Codex, Claude Code, Cursor, Oh My Pi (OMP), and Hermes Agent. One Docker container runs the MCP server and web dashboard, with SQLite stored in a persistent Docker volume.

AI harnesses connect directly to the server URL using **Streamable HTTP**. Connections need no Handoff token or login; remote deployments use Tailscale to control network access. Docker runs on the server; clients do not need Docker, Python, or a process-launch command. Client names are labels, not an allowlist. Handoff stores task context and coordinates ownership; it does not launch agents or copy project files.

## Start the server

These are server administration steps, not client connection steps.

Requires Docker Engine 28+ (or current Docker Desktop) with Compose. Run the following from the Handoff directory containing `compose.yaml`. Use a local Docker context, not a remote daemon.

```sh
docker compose up --build -d
docker compose ps
```

Visit **http://127.0.0.1:8765** (or http://localhost:8765).

The dashboard opens directly. Local MCP clients use the URL below with authentication set to **None**.

### Host on your Tailscale network

Run Docker and Tailscale on the same server. Keep the Compose port mapping on `127.0.0.1:8765:8080`, then publish it privately with:

```sh
sudo tailscale serve --bg http://127.0.0.1:8765
tailscale serve status
```

Follow the HTTPS setup prompt if shown. Use the HTTPS URL printed by Serve for the dashboard, and append `/mcp` for your agents. The service accepts remote Host and Origin headers without an allowlist or hostname configuration. Use Tailscale access rules to restrict who can reach it; anyone with access can read and modify the shared inbox.

See [Tailscale deployment](docs/remote-http.md) for server setup, client connections, verification, and updates. Tailscale Serve keeps access inside your tailnet and applies its access rules ([Tailscale documentation](https://tailscale.com/docs/features/tailscale-serve)).

## Connect an AI harness

Every client uses the same connection details:

| Setting | Value |
| --- | --- |
| Transport | Streamable HTTP (often labeled `http`) |
| Local MCP URL | `http://127.0.0.1:8765/mcp` |
| Tailscale MCP URL | The Serve HTTPS URL plus `/mcp`, for example `https://myserver.example-tailnet.ts.net/mcp` |
| Handoff authentication | None — no token, headers, or environment variables |

For Tailscale hosting, replace `http://127.0.0.1:8765/mcp` in any example below with your Serve HTTPS URL plus `/mcp`. The machine or runtime making the MCP request must be able to reach your tailnet. Docker and Python are needed only on the Handoff server, not on clients.

Choose your client: [Codex](#codex), [Claude Code](#claude-code), [Cursor](#cursor), [OMP / Oh My Pi](#omp--oh-my-pi), [Hermes Agent](#hermes-agent), or [generic MCP client](#generic-mcp-client).

For localhost or Tailscale, provide only the MCP URL. Remove old `bearer_token_env_var` settings and `Authorization` headers from existing Handoff registrations.

Use the add command first where shown below; editing the configuration file is an alternative. Choose one method per client. When editing files, merge the example into existing configuration. Replace any old `handoff` entry using `command` and `args`; do not combine command-based and URL-based settings or create a duplicate registration.

### Codex

**Option 1 — add command (recommended)**

```bash
codex mcp add handoff --url http://127.0.0.1:8765/mcp
codex mcp list
```

If an old registration needs to be removed first, run `codex mcp remove handoff`, then rerun the add command.

**Option 2 — edit TOML**

Merge [clients/codex.toml](clients/codex.toml) into `~/.codex/config.toml`, or `.codex/config.toml` for a trusted project:

```toml
[mcp_servers.handoff]
url = "http://127.0.0.1:8765/mcp"
startup_timeout_sec = 15
tool_timeout_sec = 30
```

Start a fresh Codex session and use `/mcp` in the CLI to check the connection. `codex mcp list` lists registrations. Use the configuration file belonging to the Codex home used by your CLI, desktop app, or IDE extension.

Reference: [OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

### Claude Code

**Option 1 — add command (recommended)**

```bash
claude mcp add --scope user --transport http handoff http://127.0.0.1:8765/mcp
claude mcp list
```

For project scope, replace `--scope user` with `--scope project`. If an old user registration already exists, run `claude mcp remove --scope user handoff` before adding it again; use the matching scope for a project or local registration.

**Option 2 — edit JSON**

Merge [clients/claude-code.json](clients/claude-code.json) into `.mcp.json` at your project's root:

```json
{
  "mcpServers": {
    "handoff": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Open a fresh Claude Code session, approve the project configuration if prompted, and use `/mcp` to check the connection.

Reference: [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

### Cursor

Merge [clients/cursor.json](clients/cursor.json) into `~/.cursor/mcp.json` for your user account, or `.cursor/mcp.json` for a project:

```json
{
  "mcpServers": {
    "handoff": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Reload Cursor if necessary, enable `handoff` in its MCP settings, and check that the tools are available to the agent.

Reference: [Cursor MCP documentation](https://cursor.com/docs/mcp).

### OMP / Oh My Pi

Merge [clients/omp.json](clients/omp.json) into `.omp/mcp.json` for a project or `~/.omp/agent/mcp.json` for your default user profile:

```json
{
  "mcpServers": {
    "handoff": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Named profiles use `~/.omp/profiles/<name>/agent/mcp.json`. In OMP, run:

```text
/mcp reload
/mcp list
/mcp test handoff
```

OMP may discover an existing Handoff entry from another client. Check `/mcp list` for its source and replace any old command-based entry rather than adding a duplicate.

Reference: [Oh My Pi MCP configuration](https://github.com/can1357/oh-my-pi/blob/main/docs/mcp-config.md).

### Hermes Agent

**Option 1 — add command (recommended)**

```bash
hermes mcp add handoff --url http://127.0.0.1:8765/mcp
hermes mcp list
hermes mcp test handoff
```

For a Tailscale server, use its HTTPS endpoint instead:

```bash
hermes mcp add handoff --url https://myserver.example-tailnet.ts.net/mcp
```

Use your actual Serve hostname. If replacing an existing registration, run `hermes mcp remove handoff` first. No `--auth` option or login is needed.

**Option 2 — edit YAML**

Merge [clients/hermes.yaml](clients/hermes.yaml) into `~/.hermes/config.yaml` (or the `config.yaml` in your active `HERMES_HOME`):

```yaml
mcp_servers:
  handoff:
    url: "http://127.0.0.1:8765/mcp"
```

Replace the URL with your Tailscale endpoint when hosting remotely. Start a fresh `hermes chat` session or run `/reload-mcp` in an existing session. Hermes exposes tools with names such as `mcp_handoff_handoff_push`. Ask it to list handoffs to verify a tool call, then use the upload/resume workflow below.

References: [Hermes MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/), [Hermes CLI reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands/).

### Generic MCP client

Add a server named `handoff`, select **Streamable HTTP**, enter `http://127.0.0.1:8765/mcp` or your Tailscale HTTPS endpoint, and leave authentication set to **None**. No command, token, or authorization header is needed.

[clients/generic-http.json](clients/generic-http.json) illustrates a common JSON configuration shape. Adapt its wrapper to your harness; MCP does not define a universal client configuration file. Clients must support Streamable HTTP; legacy SSE-only clients need a compatible adapter.

### Verify a connection

The client should discover all seven tools: `handoff_push`, `handoff_list`, `handoff_get`, `handoff_claim`, `handoff_resume`, `handoff_complete`, and `handoff_delete`, plus three prompts: `save`, `resume`, and `inbox`. Some clients prefix tool names with the server name.

Ask the agent:

> Use Handoff's handoff_list with status="all" and limit=5. Report whether the call succeeds. Do not create or claim a handoff.

An empty successful result is fine. A configured-server listing alone does not prove that tool calls work. After this read-only check, use the workflow below to test a transfer between any two clients.

### Troubleshooting connections

- **Client asks for a token:** remove old `bearer_token_env_var` settings or `Authorization` headers, or remove and re-add the registration using the commands above. If the local server itself still returns 401, rebuild it with `docker compose up --build -d`.
- **Connection refused:** verify the server is running and the URL is reachable from the harness. `127.0.0.1` always refers to the client's own machine or runtime; a remote harness needs a reachable server URL.
- **HTTP 403:** Handoff still rejects browser requests marked `Sec-Fetch-Site: cross-site`. Open the dashboard directly at its Serve URL. Host and Origin headers are not validated. For remote connectivity problems, check Tailscale access rules and `tailscale serve status`.
- **Server registered but tools missing:** reload the MCP configuration or start a fresh client session, check that the server is enabled, and approve project configuration where required.
- **Client still tries to run Docker:** remove the previous `command` and `args` entry and use the HTTP example for that client. The HTTP connection does not execute anything on the client.
- **Server diagnostics:** the operator can run `docker compose ps` and `docker logs --tail 50 handoff` on the server.

## Try it

With Handoff connected and its tools enabled, say:

> Upload a handoff so I can continue this conversation later.

The MCP supplies the agent with upload instructions and the field schema. The agent should summarize the context available to it, choose a useful title, save through `handoff_push`, and return a saved ID with a resume prompt. You do not need to specify JSON, tool arguments, a recipient, or a checklist of fields. Upload saves context; it does not claim or complete the underlying task.

The saved summary should include your goal, requirements and preferences, decisions and their stated reasons, progress, unsuccessful attempts, unresolved questions, useful references, and next steps. For an open-ended conversation, the next step can be to review the context and ask where you want to continue. Unknown or unavailable context should be recorded as missing rather than invented. The handoff is a summary of the context available to the agent, not an automatic export of the entire chat or its attachments.

Unless you name a receiving harness, the agent leaves `target_client` unset so any connected harness can resume. You can optionally say, "Upload a handoff for Cursor" or name Codex, Claude Code, OMP, or another harness. Client labels support filtering; they do not launch an agent or restrict who can claim a handoff.

Later, in a fresh session of any connected harness, paste the returned prompt:

> Resume Handoff `<id>`.

The recipient calls `handoff_resume`, which claims the handoff and returns its saved context in one step, then checks your current instructions and any relevant workspace before continuing work. It records completion only with observed results.

### Prompts

Clients that support MCP prompts show Handoff's prompts as commands. In Claude Code they appear as slash commands:

| Command | What it does |
| --- | --- |
| `/mcp__handoff__save [target] [focus]` | Saves the conversation; optionally names a receiving harness and what to emphasise. |
| `/mcp__handoff__resume <id>` | Claims the handoff and continues it. If it is already claimed or completed, the agent reads and summarises it instead. |
| `/mcp__handoff__inbox` | Lists handoffs that are ready to resume and asks which one to pick. |

Other clients name prompts differently; the plain-language requests above work everywhere.

The receiving agent needs its own access to the project files and tools required for the task. Handoff transfers the saved context, not the workspace.

You can also click **Copy resume prompt** on any dashboard record. The dashboard lists all handoffs with status, project and receiving-agent filters, title/project/ID search, paginated results, and 15-second refreshes. Click a record to see all context, references, metadata, outcome, raw JSON and paginated activity history.

To add a single, clearly labeled welcome example:

```sh
docker exec handoff python -m handoff seed-demo
```

Running that command twice reuses the same saved example. The app never seeds fake work automatically.

## Tool contract

| Tool | Behavior |
| --- | --- |
| `handoff_push` | Validate and save immutable source context. Return an ID and receipt. |
| `handoff_list` | Filter and paginate summaries; defaults to available handoffs. Use `status="all"` for all records. |
| `handoff_get` | Return every record field and the current lifecycle state, without changing anything. |
| `handoff_resume` | Claim a handoff and return its full record plus the claim token, in one call. Fails with `ALREADY_CLAIMED` or `ALREADY_COMPLETED`. |
| `handoff_claim` | Acquire, renew or release a lease. Acquire returns a claim token; renew and release need only the ID and token. |
| `handoff_complete` | Record success, blocked work or abandonment, using the claim token. |
| `handoff_delete` | Permanently delete a handoff and its history (refused while another agent holds an active claim). Agents are told to use it only on explicit request. |

Mutations accept an optional `operation_id` (any UUID, any case). Supply one to make retries safe: after uncertain delivery, retry the **identical request and operation ID**. Changing its arguments returns `IDEMPOTENCY_CONFLICT`. Without an operation ID, a retry creates a second record or action. The `replayed` flag means the receipt is historical: fetch current state before relying on an old claim. Receipts are kept for 7 days; a retry after that is treated as a new request.

Claims default to 1 hour (60–86,400 seconds allowed). An expired claim shows as available, but its holder can still renew, release or complete it until another agent acquires the handoff; the new claim's token fences out the old one. Renewal is therefore only needed to stop someone else taking over during long work. `expected_revision` and `claim_generation` are optional extra checks. A claim coordinates ownership; it does not make external file edits exactly once.

The minimum record requires `title`, `source.client`, and `context` with `objective`, `current_state`, at least one `next_steps` entry (`id`, `action`, `done_when`), and at least one `acceptance_criteria` string. Optional fields have stable defaults. [examples/push.json](examples/push.json) is a complete importable request. The MCP schemas expose all fields and limits.

For `outcome="succeeded"`, completion must report one passing result with nonempty evidence for each original acceptance criterion. Identify each criterion by `index` (0-based, in the record's order) or by its text; text matching ignores case and whitespace. A mismatch error lists the original criteria with their indexes. Use `blocked` or `abandoned` for an unfinished attempt, or release the claim to leave it available. Corrections/continuations use a new push with `parent_id`; source records are never silently rewritten.

## Import and export

The CLI talks to the existing service through MCP. It never writes directly to SQLite.

```sh
# This example is marked manual_import and contains a stable operation ID.
docker exec -i handoff python -m handoff import - < examples/push.json

# An archival envelope, including current metadata and outcome:
docker exec handoff python -m handoff export HANDOFF_ID > handoff-export.json
```

An archival envelope is not a valid push request. To import its source into another store, prepare `{ "operation_id": "NEW-UUIDV4", "record": ... }`, mark `source.transfer_method="manual_import"`, and remove or resolve any parent ID. Exported source context is data, not instructions to execute.

## Storage, restart and backup

The `handoff_handoff_data` local Docker volume contains SQLite. Container replacement preserves the saved handoffs; there is exactly one database owner. Stop with `docker compose stop`, restart with `docker compose up -d`. **Do not use `docker compose down -v` if you want to keep handoffs.**

For a backup, stop the service cleanly, copy the whole volume (including SQLite sidecars) to protected local storage, and restart. Restore into a separate volume while stopped and verify SQLite integrity before using it. Backups include task context. Claim tokens are stored as SHA-256 hashes; the raw token stays in its acquire receipt only while that claim is active, so a lost response can still be retried. An old access-token file may remain from earlier versions; this version does not read or create it. Encrypted database storage is not part of this MVP.

Delete individual handoffs with `handoff_delete`. To delete completed handoffs automatically, set `HANDOFF_RETENTION_DAYS` (for example `90`) in the Compose service's `environment`; completed records older than that are removed, with their history, during later writes. Upgrading from 0.1.x migrates the database in place on first start (schema 2); back up the volume first, because 0.1.x cannot open the migrated store.

The web/API and MCP listener are published only on IPv4 loopback. The service has no outbound API calls, telemetry, URL fetching, project filesystem mount or Docker socket mount. Handoff contents shown to an AI client can still be sent to that client's model provider. Do not put secrets in summaries. The web dashboard is a viewer; agents mutate handoffs through MCP. Handoff requires no authentication and does not validate Host or Origin headers. Keep the published port on loopback and use Tailscale Serve with restricted tailnet access for remote connections. Anyone who can reach the service can access the shared inbox; do not expose this token-free service to the public internet.

## Development and tests

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe`. Tests use isolated temporary stores and subprocesses. They cover retry safety, simultaneous claims, lease fencing, transaction rollback, reopen durability, validation, real HTTP/stdio MCP round trips, token-free local and remote-header access, cross-site browser request rejection, search, filters, deep links, copy actions, mobile overflow and inert rendering of hostile text.

Local development without Docker:

```sh
.venv/bin/python -m handoff --data-dir ./data serve --host 127.0.0.1 --port 8765
```

Never run a second owner against an active data directory. Production packages are pinned in `requirements.lock`; the Docker base is pinned by digest.

## References and scope

The original proposal is retained in [outputs/docs/mvp-v1.md](outputs/docs/mvp-v1.md) as historical planning material. The service exposes a shared MCP inbox for harnesses supporting Streamable HTTP. The older stdio bridge remains a compatibility option; the documented client setup uses direct HTTP. The client instructions above cover Codex, Claude Code, Cursor, OMP, Hermes Agent, and generic clients; they are not an exhaustive compatibility list. Remote HTTPS hosting through Tailscale Serve is described in [Tailscale deployment](docs/remote-http.md). Automatic agent launching, vector search and separate per-user access controls are outside this build. See [docs/implementation.md](docs/implementation.md) for implementation notes and recorded verification; setup examples do not imply every client has been tested end to end.

Client-specific references are linked in each setup section. The server uses the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
