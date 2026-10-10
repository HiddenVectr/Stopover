# Host Baton on your Tailscale network

Run the Baton container on your server and use Tailscale Serve to provide a private HTTPS endpoint. Each AI agent connects directly using Streamable HTTP. Clients need network access to your tailnet, but no Docker, Python, SSH tunnel, or stdio bridge.

```text
AI agent on your tailnet
  -> https://<server>.<tailnet>.ts.net/mcp
  -> Tailscale Serve on the server
  -> http://127.0.0.1:8765/mcp
  -> Baton container + persistent SQLite volume
```

## Access model

Baton requires no connection token or login. Baton only answers requests whose `Host` is `localhost`, `127.0.0.1`, `::1` or a `*.ts.net` name. The Host check is an additional request boundary; access still depends on your network rules. To reach it by another name or a tailnet IP, add a comma-separated list to `BATON_ALLOWED_HOSTS` in the Compose service's `environment` (for example `handoff.example.com,100.64.0.10`; a leading `*.` matches subdomains, and `*` turns the check off). Access is otherwise controlled by Tailscale and the server's network configuration. Anyone allowed to reach Baton can read and mutate its shared inbox; there are no separate user permissions inside the application.

Keep Docker's published port bound to loopback (`127.0.0.1:8765:8765`) and use **Tailscale Serve**. Tailscale Funnel publishes services to the internet and is unsuitable for this token-free deployment. Restrict tailnet access to the server's HTTPS port (443) to your intended users/devices. [Tailscale Serve applies tailnet access rules](https://tailscale.com/docs/features/tailscale-serve).

The same request checks apply as locally: a well-formed, allowed `Host`; an `Origin`, when a browser sends one, that is the Serve URL itself; refusal of other cross-site browser requests (`Sec-Fetch-Site: cross-site`, except following a link); a 64 KiB request limit; and security response headers. No cross-origin (CORS) access is added. These checks make it harder for web pages you visit to reach Baton through your browser; they do not replace network access control.

## 1. Prepare the server

Install Docker Engine with Compose v2 and [Tailscale](https://tailscale.com/docs/install), then join the server to your tailnet. Use a local Docker daemon on that server. The existing Compose file requires Docker Engine 28+ or current Docker Desktop.

Clone the public repository and start the server:

```sh
git clone https://github.com/HiddenVectr/Baton.git
cd Baton
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
curl --fail http://127.0.0.1:8765/healthz
```

The health response should contain `"ready": true`. The named Docker volume stores handoffs across container replacements. A fresh server starts with its own store; cloning the repository does not copy handoffs from another machine. To move existing data, follow the [backup and restore guidance](operations.md#storage-restart-and-backup).

## 2. Enable private HTTPS

On the same server:

```sh
sudo tailscale serve --bg http://127.0.0.1:8765
tailscale serve status
```

Follow the HTTPS enablement link if Tailscale prints one. Serve supplies a certificate and prints the actual URL, for example `https://myserver.example-tailnet.ts.net`. Substitute that actual hostname everywhere below. No Baton environment variable or code change is needed for a different server name.

`--bg` keeps the Serve configuration active across Tailscale and server restarts. The container uses `restart: unless-stopped`; ensure Docker and Tailscale start with the host. If Serve already routes another application on port 443, inspect its configuration before assigning the root path to Baton. See the [Serve CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve).

## 3. Connect your agents

Use these settings from devices permitted by your tailnet rules:

| Setting | Value |
| --- | --- |
| Transport | Streamable HTTP |
| MCP URL | `https://myserver.example-tailnet.ts.net/mcp` |
| Authentication | None |
| Dashboard | `https://myserver.example-tailnet.ts.net/` |

Follow the [client setup instructions](clients.md) for Codex, Claude Code, Cursor, OMP, Hermes Agent, or a generic client. Replace the localhost URL with the MCP URL above in either the add command or configuration file. Remove obsolete token settings from older registrations.

The process making the MCP connection must have tailnet access. For a remote agent, container, VM, or hosted agent, check connectivity from that runtime; having Tailscale on your laptop alone does not give a cloud agent access. Clients must support Streamable HTTP or use a compatible adapter.

## 4. Verify from a client device

```sh
curl --fail https://myserver.example-tailnet.ts.net/healthz
```

Open the dashboard at the same origin, then ask your agent:

> Use Baton's baton_list with status="all" and limit=5. Report whether the call succeeds. Do not create or claim a handoff.

An empty successful result is valid. Confirm discovery of all eleven tools. To save context, say:

> Save a handoff so I can continue this conversation later.

## Updates and troubleshooting

Update the server checkout and rebuild:

```sh
git pull --ff-only
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
```

The data volume is preserved. Do not run `docker compose down -v` unless you intend to delete its handoffs.

- If the local health check fails, inspect `docker logs --tail 50 baton` and `docker compose ps`.
- If local health works but the HTTPS check fails, inspect `tailscale status`, `tailscale serve status`, the client's tailnet connection, and access rules for port 443.
- If a client receives `Host not allowed`, it is using a hostname or IP outside the allowlist. Use the `*.ts.net` Serve URL, or add the name to `BATON_ALLOWED_HOSTS` and restart the container.
- If Baton returns `Cross-site request not allowed`, open the dashboard directly at its Serve URL. Native MCP clients normally omit Fetch Metadata headers.
- If a agent discovers no tools, verify that it uses the `/mcp` endpoint and Streamable HTTP, then reload its MCP configuration or start a new session.

MCP transfers saved task context, not project files. Receiving agents need their own access to any workspace required to continue the work.
