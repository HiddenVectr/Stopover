# Implementation notes

Baton exposes token-free Streamable HTTP so AI harnesses can connect by URL on localhost or a private network. The stdio bridge remains available for existing integrations. Source and target client names are free-form labels, not a Claude Code/Codex allowlist. See the [client setup guide](../README.md#connect-an-ai-harness) for Codex, Claude Code, Cursor, Oh My Pi (OMP), Hermes Agent, and generic configuration. The original proposal is historical. A Host allowlist (loopback names and `*.ts.net` by default, extended with `BATON_ALLOWED_HOSTS`) runs before every route; the MCP SDK's exact-match check stays off because it cannot express wildcard domains. [Tailscale deployment](remote-http.md) describes private HTTPS hosting with network access controlled by Tailscale.

The service uses the official Python MCP SDK's stateless Streamable HTTP transport. A small stdio adapter starts inside the running container for each client and forwards to the same owner process. Both transports expose the same eleven tool schemas and five prompts and preserve structured results and MCP error flags.

Natural-language upload guidance is included in both the server initialization instructions and the `baton_push` tool description, so the save workflow is described even when a harness exposes tool descriptions without the server-level instructions. A short save request is enough: the agent builds a contextual summary, leaves the recipient unspecified by default, and returns the saved ID only after success. The MCP receives the summary the agent submits; it cannot read the conversation itself. Model compliance and summary quality still depend on the harness and available context.

SQLite mutations and their idempotency receipts commit in one transaction. A process lock prevents a second owner; a thread lock serializes database access. Leases persist across service restarts. Only a SHA-256 hash of each claim token is stored, and the token alone authorizes renew/release/complete; an expired lease keeps working until another agent acquires the handoff. Mutation timestamps never move backward, even if the system clock does. Receipts expire after 7 days. The read-only web API uses these same store methods, with a separate paginated event history.

The dashboard is bundled static HTML/CSS/JavaScript with no CDN, frontend build service or remote assets. All source content is inserted as text, not rendered HTML or Markdown. The dashboard opens directly without a login or session cookie. The middleware retains cross-site browser request rejection and a 64 KiB body limit. Unexpected Host headers are rejected, which blocks DNS rebinding. No wildcard CORS is enabled, and Compose still publishes on IPv4 loopback only.

Differences from the planning document:

- A few nonessential source fields now have stable defaults, so agents can create a concise handoff without inventing metadata. Objective, current state, next steps and acceptance criteria remain required.
- Local and private network access require no Baton token. The service no longer creates or reads an access-token file. Existing data volumes are preserved, including any unused token file from an earlier version. Task-claim tokens still coordinate active work and are unrelated to connection authentication.
- The dashboard adds read-only HTTP endpoints and opens without a login. Agent writes remain MCP-only.
- Count limits protect the small local store; an exact 1 GiB filesystem quota is not implemented. Disk-full errors fail the transaction; monitor the volume and back it up.
- Tests cover the implemented contracts; the proposal's broad fault-injection/performance matrix is not represented as fully certified.

Source records are immutable. A completed record remains visible and browsable. The service does not transfer private model reasoning or assume that a source agent's text authorizes recipient actions.

## Architecture and extension points

The code is layered so a hosted build can reuse everything except storage and access control:

| Module | Role |
| --- | --- |
| `context.py` | `RequestContext(workspace, actor)`: who is asking. Local requests use workspace `local`. |
| `domain.py` | Storage-independent rules: summaries, cursors, claim verification, acceptance-criteria matching, errors. |
| `backend.py` | The storage contract: `Backend.transaction(ctx, write)` yields a `Transaction` scoped to one workspace, with rows as plain dicts. |
| `sqlite_backend.py` | The local backend: single owner, single workspace, all SQL and migrations. Other workspaces get `UNKNOWN_WORKSPACE`. |
| `service.py`, `memory.py` | `BatonService`: validation, idempotent receipts, monotonic time, retention, and every tool handler, written only against `backend.py`. |
| `registry.py`, `catalog.py` | The tools, prompts and instructions the MCP server exposes. `core_registry().copy()` can be extended with more tools. |
| `server.py` | `create_app(service=, auth=, allowed_hosts=, extra_routes=, middleware=)`. `auth` is an async callable that maps a request to a `RequestContext` (or `None` for 401) for `/mcp` and `/api/*`; MCP handlers and the dashboard API pass that context to the service, and events record its `actor`. |
| `domain.Policy` | Per-workspace limits and retention. `BatonService(policy=...)` takes a `Policy` or a function of the `RequestContext`, so a hosted build can vary limits by plan. |
| `on_event` | `BatonService(on_event=...)` receives events such as `handoff.pushed`, `handoff.completed` and `memory.updated` after each commit (never on replays or rollbacks). Events carry IDs, revisions and the actor, never handoff or memory content; handler errors are logged and ignored. |
| Dashboard sign-in | When `/api/*` answers 401 (an `auth` hook is configured), the dashboard asks for an access token, keeps it in `localStorage`, and sends it as `Authorization: Bearer`. Its connection instructions then show the token header with a `YOUR_TOKEN` placeholder. Without auth nothing changes. With `create_app(login_url=...)`, unauthenticated dashboard API calls return that URL and the dashboard redirects there (same origin only, with `return_to`). If the host serves `GET /api/session` (`user`, `workspace`, `logout_url`), the sidebar shows the signed-in account and Sign out posts to `logout_url`. The dashboard sends same-origin cookies so hosts can use session cookies; MCP stays bearer-only. |
| `testing.py` | The backend conformance suite. A project with its own `Backend` runs it with `from baton.testing import *` and a `make_service` fixture (install the `testing` extra). Baton runs it against SQLite in `tests/test_conformance.py`. |
| `store.py` | `Store`: the local deployment (`BatonService` over SQLite), kept for existing imports. |

A hosted build depends on this package and supplies its own `Backend` (for example Postgres with a workspace column), an authenticator, and any extra tools or routes. Tests guard the boundary: the service layer never references SQLite.

## Personal memory implementation

`memory.py` holds the personal-memory rules; the backend stores memory rows, a global monotonic revision, and separate idempotency receipts to the existing SQLite database. Initialization is additive for existing schema-2 stores. Updates and explicit forgetting commit atomically under the existing owner/thread locks. Revisions detect concurrent corrections; stable normalized topic keys prevent duplicate writes to the same topic. Forgetting removes the body, evidence, and source; only minimal deletion markers remain. No historical memory bodies are stored in receipts. Personal memories are independent of task retention and claims.

Read/export pagination binds a cursor to its filters and the first page's store revision, which every page reports as the checkpoint. Concurrent writes do not abort pagination; they carry higher revisions, so the next incremental read returns them. Incremental reads include deleted IDs, including through filters where erased content cannot be matched. Exports are paginated and expose a completion flag and continuation cursor.

The full memory workflow is provided once at server initialization and in the `memory-update` / `memory-import` prompts; memory tool descriptions are short contracts, keeping the tool list small. The harness extracts all available personal knowledge, reconciles it remotely, and reports coverage. The MCP does not inspect the harness context, access harness files, or install local adapters. There is no additional authentication or per-user partitioning. Local remembering, if chosen, remains the harness's responsibility.

The existing dashboard adds a Personal memories view with full-text display, topic/content search, category filters, provenance, timestamps, revision, direct links, pagination, and refresh. GET-only `/api/memories` and `/api/memories/{key}` use the same store validation. All content remains inert text.

## Verification

All tests pass, including browser coverage. Tests exercise credential-free API/dashboard access, the HTTP/stdio handoff lifecycle, and allowed remote Host/Origin headers over real MCP HTTP connections, with initialization, tool discovery, upload and retrieval. Unknown hosts are rejected on every route, and the allowlist can be extended or disabled. Cross-site Fetch Metadata rejection and the body limit remain covered. A deployed Tailscale endpoint and an interactive Hermes Agent session have not been tested here; their setup instructions were checked against upstream documentation.

Dashboard screenshots: [desktop](dashboard.png), [mobile](dashboard-mobile.png).
