# Implementation notes

Stopover exposes token-free Streamable HTTP so AI harnesses can connect by URL on localhost or a private network. The stdio bridge remains available for existing integrations. Source and target client names are free-form labels, not a Claude Code/Codex allowlist. See the [API reference](api.md) for tool contracts and the [client setup guide](clients.md) for Codex, Claude Code, Cursor, Oh My Pi (OMP), Hermes Agent, and generic configuration. A Host allowlist (loopback names and `*.ts.net` by default, extended with `STOPOVER_ALLOWED_HOSTS`) runs before every route; the MCP SDK's exact-match check stays off because it cannot express wildcard domains. [Tailscale deployment](remote-http.md) describes private HTTPS hosting with network access controlled by Tailscale.

The service uses the official Python MCP SDK's stateless Streamable HTTP transport. A small stdio adapter starts inside the running container for each client and forwards to the same owner process. Both transports expose the same eleven tool schemas and five prompts and preserve structured results and MCP error flags.

Natural-language save guidance is included in both the server initialization instructions and the `stopover_save` tool description, so the save workflow is described even when a harness exposes tool descriptions without the server-level instructions. A short save request is enough: the agent builds a contextual summary, leaves the recipient unspecified by default, and returns the saved ID only after success. The MCP receives the summary the agent submits; it cannot read the conversation itself. Model compliance and summary quality still depend on the harness and available context.

SQLite mutations and their idempotency receipts commit in one transaction. A process lock prevents a second owner; a thread lock serializes database access. Leases persist across service restarts. Only a SHA-256 hash of each claim token is stored, and the token alone authorizes renew/release/complete; an expired lease keeps working until another agent acquires the handoff. Mutation timestamps never move backward, even if the system clock does. Receipts expire after 7 days. The read-only web API uses these same store methods, with a separate paginated event history.

The dashboard is bundled static HTML/CSS/JavaScript with no CDN, frontend build service or remote assets. All source content is inserted as text, not rendered HTML or Markdown. The dashboard opens directly without a login or session cookie. The middleware retains cross-site browser request rejection and a 64 KiB body limit. Unexpected Host headers are rejected; this is an additional request boundary, not authentication. No wildcard CORS is enabled, and Compose still publishes on IPv4 loopback only.

Design notes:

- Nonessential source fields have stable defaults, so agents can save a concise handoff without inventing metadata. Objective, current state, next steps and acceptance criteria are required.
- Connections need no Stopover token. Claim tokens coordinate who is working on a handoff; they are unrelated to connection authentication.
- The dashboard reads through GET-only HTTP endpoints and opens without a login. Agents make every change through MCP.
- Count limits protect the small local store; there is no filesystem quota. A full disk fails the transaction, so monitor the volume and back it up.
- Tests cover the implemented contracts; there is no broad fault-injection or performance test matrix yet.

Source records are immutable. A completed record remains visible and browsable. The service does not transfer private model reasoning or assume that a source agent's text authorizes recipient actions.

## Architecture

| Module | Role |
| --- | --- |
| `domain.py` | Storage-independent rules: summaries, cursors, claim verification, acceptance-criteria matching, errors. |
| `sqlite_backend.py` | The SQLite store: single owner, all SQL and migrations. |
| `service.py`, `memory.py` | Validation, idempotent receipts, monotonic time, retention, and every tool handler. |
| `registry.py`, `catalog.py` | The tools, prompts and instructions the MCP server exposes. |
| `server.py` | The HTTP app: the MCP endpoint, the read-only dashboard API, the dashboard page, and the request checks (Host allowlist, Origin, Fetch Metadata, body limit). |
| `bridge.py` | The stdio bridge, which forwards to the running server. |
| `models.py` | The input models, from which the committed JSON schemas are generated. |

## Personal memory implementation

Personal memory is a separate feature from handoffs (see the [user guide](memory.md)), sharing only the database and request handling. `memory.py` holds its rules; the database stores memory rows, a store-wide monotonic revision, and the memory idempotency receipts in the same SQLite database. Updates and explicit forgetting commit atomically under the existing owner/thread locks. Revisions detect concurrent corrections; stable normalized topic keys prevent duplicate writes to the same topic. Forgetting removes the body, evidence, and source; only minimal deletion markers remain. No historical memory bodies are stored in receipts. Personal memories are independent of task retention and claims.

Read/export pagination binds a cursor to its filters and the first page's store revision, which every page reports as the checkpoint. Concurrent writes do not abort pagination; they carry higher revisions, so the next incremental read returns them. Incremental reads include deleted IDs, including through filters where erased content cannot be matched. Exports are paginated and expose a completion flag and continuation cursor.

The full memory workflow is provided once at server initialization and in the `memory-update` / `memory-import` prompts; memory tool descriptions are short contracts, keeping the tool list small. The harness extracts all available personal knowledge, reconciles it remotely, and reports coverage. The MCP does not inspect the harness context, access harness files, or install local adapters. There is no additional authentication or per-user partitioning. Local remembering, if chosen, remains the harness's responsibility.

The dashboard's Personal memories view has with full-text display, topic/content search, category filters, provenance, timestamps, revision, direct links, pagination, and refresh. GET-only `/api/memories` and `/api/memories/{key}` use the same store validation. All content remains inert text.

## Tests

The test suite includes browser tests of the dashboard. It exercises credential-free API/dashboard access, the HTTP/stdio handoff lifecycle, and allowed remote Host/Origin headers over real MCP HTTP connections, with initialization, tool discovery, saving and retrieval. Unknown and malformed hosts are rejected on every route (malformed ones even when the allowlist is `*`), and the allowlist can be extended. Foreign, invalid and `null` `Origin` headers are rejected for MCP and the API; requests without `Origin` (native clients) are accepted. Cross-site Fetch Metadata rejection and the body limit remain covered. The Tailscale, Hermes Agent and Muse Code setup instructions follow upstream documentation but are not covered by automated tests.

Dashboard screenshots: [desktop](images/dashboard.png), [mobile](images/dashboard-mobile.png). Regenerate all images with `.venv/bin/python scripts/screenshots.py`.

## Local development

Install the development dependencies using the [README instructions](../README.md#development). Run without Docker:

```sh
.venv/bin/python -m stopover --data-dir ./data serve --host 127.0.0.1 --port 8765
```

Never run two servers against the same data directory. Production packages are pinned in `requirements.lock` and the Docker base image by digest. The server uses the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

Regenerate the documentation screenshots with `.venv/bin/python scripts/screenshots.py`. It starts a throwaway server and fills it with synthetic data.
