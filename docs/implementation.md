# Implementation notes

Handoff exposes token-free Streamable HTTP so AI harnesses can connect by URL on localhost or a private network. The stdio bridge remains available for existing integrations. Source and target client names are free-form labels, not a Claude Code/Codex allowlist. See the [client setup guide](../README.md#connect-an-ai-harness) for Codex, Claude Code, Cursor, Oh My Pi (OMP), Hermes Agent, and generic configuration. The original proposal is historical. Host and Origin validation is disabled in both the HTTP middleware and MCP SDK. [Tailscale deployment](remote-http.md) describes private HTTPS hosting with network access controlled by Tailscale.

The service uses the official Python MCP SDK's stateless Streamable HTTP transport. A small stdio adapter starts inside the running container for each client and forwards to the same owner process. Both transports expose the same five schemas and preserve structured results and MCP error flags.

Natural-language upload guidance is included in both the server initialization instructions and the `handoff_push` tool description, so the save workflow is described even when a harness exposes tool descriptions without the server-level instructions. A short save request is enough: the agent builds a contextual summary, leaves the recipient unspecified by default, and returns the saved ID only after success. The MCP receives the summary the agent submits; it cannot read the conversation itself. Model compliance and summary quality still depend on the harness and available context.

SQLite mutations and their idempotency receipts commit in one transaction. A process lock prevents a second owner; a thread lock serializes database access. Leases persist across service restarts and use revision/generation/token checks. The read-only web API uses these same store methods, with a separate paginated event history.

The dashboard is bundled static HTML/CSS/JavaScript with no CDN, frontend build service or remote assets. All source content is inserted as text, not rendered HTML or Markdown. The dashboard opens directly without a login or session cookie. The middleware retains cross-site browser request rejection and a 64 KiB body limit. Host/Origin validation and the MCP SDK DNS rebinding checks are disabled for direct remote URL access. No wildcard CORS is enabled, and Compose still publishes on IPv4 loopback only.

Differences from the planning document:

- A few nonessential source fields now have stable defaults, so agents can create a concise handoff without inventing metadata. Objective, current state, next steps and acceptance criteria remain required.
- Local and private network access require no Handoff token. The service no longer creates or reads an access-token file. Existing data volumes are preserved, including any unused token file from an earlier version. Task-claim tokens still coordinate active work and are unrelated to connection authentication.
- The dashboard adds read-only HTTP endpoints and opens without a login. Agent writes remain MCP-only.
- Count limits protect the small local store; an exact 1 GiB filesystem quota is not implemented. Disk-full errors fail the transaction; monitor the volume and back it up.
- Tests cover the implemented contracts; the proposal's broad fault-injection/performance matrix is not represented as fully certified.

Source records are immutable. A completed record remains visible and browsable. The service does not transfer private model reasoning or assume that a source agent's text authorizes recipient actions.

## Verification

All 29 tests pass, including browser coverage. Tests exercise credential-free API/dashboard access, the HTTP/stdio handoff lifecycle, and remote Host/Origin headers over real MCP HTTP connections. Remote cases cover a Tailscale hostname, a tailnet IP, and unrelated or opaque origins, with initialization, tool discovery, upload and retrieval. Cross-site Fetch Metadata rejection and the body limit remain covered. A deployed Tailscale endpoint and an interactive Hermes Agent session have not been tested here; their setup instructions were checked against upstream documentation.

### Historical verification before local token removal

The following is the original implementation verification record, not a certification of every documented harness. Cursor and OMP setup instructions were checked against their upstream documentation; interactive end-to-end sessions in those clients have not been verified here.

Verified on 2026-10-06:

- 19 automated tests passed, including the browser flow and real HTTP/stdio MCP sessions. After the final file-permission and default-bind changes, the 18 backend/transport tests passed again.
- Docker built with the pinned Python 3.12 image and locked dependencies. The service is healthy, runs as UID 10001, and publishes only 127.0.0.1:8765.
- A real HTTP source and a fresh `docker exec -i` stdio client completed a shared handoff. Retrying push returned the original receipt.
- The completed record, revision and outcome survived a container restart.
- Claude Code reports Connected. Codex's enabled global registration uses the same stdio adapter. Fresh agent sessions are needed to load newly configured tools.
- The running Docker dashboard was checked in Chromium on desktop and mobile. Installed source files match the tested build. Screenshots: [desktop](dashboard.png), [mobile](dashboard-mobile.png).
- Windows localhost access: verified by PowerShell health request.

The store contains one ready welcome handoff and one completed, explicitly labeled automated transport check. The welcome ID is `25b47beb-74bf-4dea-9942-88f621cba3a5`.

No paid model-to-model conversation was run. Protocol tests verify transport, context integrity and lifecycle behavior; semantic continuity still needs checking in fresh sessions of the chosen source and receiving harnesses. Detailed results are in [verification.json](verification.json).
