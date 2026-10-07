# Remote HTTP deployment

## Connection model

Each AI harness connects to `https://<your-hostname>/mcp` with the server's access token. The harness does not need Docker, Python, SSH, a shared filesystem, or a stdio bridge. Locally, clients use `http://127.0.0.1:8765/mcp` without authentication. Authentication is required for the proposed remote mode, not for localhost. See the [client setup guide](../README.md#connect-an-ai-harness).

## Current status

The server already implements token-free localhost Streamable HTTP at `/mcp`. Its HTTP middleware and MCP SDK settings currently allow only local Host headers, and Compose publishes the service on `127.0.0.1:8765`. Consequently, adding a DNS record or putting a reverse proxy in front of the current build is not enough: a request preserving the public Host is rejected.

The client examples now use direct HTTP. The server changes below are proposed and **have not been applied or deployed**.

## Proposed server change for approval

- Add `HANDOFF_PUBLIC_URL`, an explicit HTTPS origin such as `https://handoff.example.com`, and pass it through Compose. Leave local-only behavior unchanged when it is unset.
- Validate that the value is an HTTPS origin without credentials, a path, query, fragment, or wildcard. The MCP endpoint is that origin plus `/mcp`.
- Allow the configured public authority in both the application boundary and MCP SDK host validation. Continue rejecting other hosts and unrelated browser origins.
- Terminate HTTPS at a reverse proxy on the server and forward to `127.0.0.1:8765`, preserving the original Host and Authorization headers. Keep the application port bound to loopback. TLS certificates and DNS must belong to the approved hostname.
- Add authentication for every remote MCP request and protect remote dashboard access. Localhost connections remain token-free. Remote access must not inherit the localhost authentication exemption merely because a proxy connects from loopback.
- Show remote authentication instructions in the dashboard when remote mode is enabled. The local dashboard already displays the URL and requires no login.
- Test remote-host MCP initialization, tool discovery and calls, rejection of invalid/missing tokens and unapproved hosts/origins, secure dashboard sessions, and existing local connections.

The public hostname and permission to enable it are needed before applying the server change. No remote server, domain, or certificate has been provisioned.

## Access scope

The current local deployment is one shared inbox available to local clients without credentials. The proposed remote deployment would require an access token; any holder could read handoffs and use mutation tools, subject to the claim lifecycle. Separate users, per-client permissions, OAuth authorization, and a public multi-tenant service are not implemented. Remote clients also need their own access to any project files required by the task; MCP carries the saved context, not the workspace.
