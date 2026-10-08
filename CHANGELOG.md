# Changelog

All notable changes to Baton. Versions follow [semantic versioning](https://semver.org/); the extension API
(`Backend`, `RequestContext`, the registry and `create_app` hooks) only changes incompatibly in a major release.

## Unreleased

- Licensed under the Apache License 2.0.
- **Port:** the server now listens on **8765** everywhere (`baton serve` default, container, Compose and health check). Earlier versions listened on 8080 inside the container and published it as 8765. If you customised `compose.yaml` or run the image directly, map `8765:8765`.
- The CLI's default `--url` is `http://127.0.0.1:8765/mcp`.
- Continuous integration runs the full test suite, including browser tests.
- Documentation fixes (Hermes tool names) and removal of internal planning material.

## 0.9.0 — 2026-10-07

- The dashboard shows host-provided account links and, when a host issues access tokens, token instructions in *Connect your agents* (`/api/session` fields `links` and `access_token_url`).

## 0.8.2 — 2026-10-07

- Cross-site top-level GET navigations (following a link, a sign-in provider redirecting back) are allowed; cross-site fetches, embeds and form POSTs are still refused.

## 0.8.1 — 2026-10-07

- The dashboard starts only one sign-in when several requests fail at once.

## 0.8.0 — 2026-10-07

- Hosts can provide a sign-in page (`create_app(login_url=...)`) and a signed-in account (`GET /api/session`); the dashboard redirects and shows the account.

## 0.7.0 — 2026-10-07

- The dashboard asks for an access token when an authenticated host returns 401.

## 0.6.0 — 2026-10-07

- `baton.testing`: a backend conformance suite for other storage backends.
- `Policy` (per-workspace limits and retention) and `on_event` (content-free domain events after commit) hooks.

## 0.5.0 — 2026-10-07

- Renamed from **Handoff** to **Baton**: package `baton-inbox`, module and CLI `baton`, MCP server `baton`, tools `baton_*`, environment variables `BATON_*` (old `HANDOFF_*` names still work), Docker project and volume `baton`.

### Upgrading from Handoff (before 0.5.0)

Baton was previously called Handoff. The data format is unchanged, and an existing `handoff.sqlite3` is renamed to `baton.sqlite3` on first start. The `HANDOFF_*` environment variables still work, but use `BATON_*` going forward.

The Compose project, container and volume names changed, so copy the old volume once. Run this from the repository directory:

```sh
docker compose -p handoff down          # stop the old container; its volume is kept
docker compose build
docker volume create baton_baton_data
docker run --rm --user 0 --entrypoint sh -v handoff_handoff_data:/from -v baton_baton_data:/to baton:0.5.0 \
  -c 'cp -a /from/. /to/ && chown 10001:10001 /to && chmod 700 /to'
docker compose up -d
```

Once Baton shows your handoffs, you can remove the old volume with `docker volume rm handoff_handoff_data`.

The MCP server is now named `baton`, and the tools are `baton_*` (for example `baton_push` and `baton_resume`). In each harness, remove the old `handoff` registration and add `baton` using the commands above; prompts become `/mcp__baton__save`, `/mcp__baton__resume` and so on. A saved record is still called a handoff, so "Resume Handoff `<id>`" works as before.

## 0.4.0 — 2026-10-07

- Storage, rules and transport separated (`Backend` interface, `RequestContext`, registry, `create_app` hooks).
- Host allowlist against DNS rebinding (`BATON_ALLOWED_HOSTS`).

## 0.3.x — 2026-10-07

- Shared personal memories (`*_memory_read/update/forget/export`, prompts, dashboard view), with provenance-preserving re-syncs, conflict reporting, recreation of forgotten keys and snapshot pagination.

## 0.2.0 — 2026-10-06

- Simpler claims (expired leases usable until re-acquired, token-only renew/complete), lenient validation, `resume` tool, MCP prompts, delete, retention, hashed claim tokens.

## 0.1.0 — 2026-10-06

- First version: MCP inbox for handoffs with claims, completion evidence and a web dashboard.
