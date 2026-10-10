# Changelog

All notable changes to Baton. Versions follow [semantic versioning](https://semver.org/). Baton is pre-1.0, so a
minor release (0.x) can include breaking changes, for MCP clients or for hosts using the extension API (`Backend`,
`RequestContext`, the registry and `create_app` hooks). Every breaking change is marked **Breaking** here, with what
to update. Patch releases (0.x.y) don't break anything.

## Unreleased

- Malformed `Host` and `Origin` headers (such as `Origin: https://[`, or a non-ASCII port) get a clean 403 instead of a 500 error.

## 0.12.0 — 2026-10-09

Security and quality fixes from the public-release review.

- **Security:** Starlette upgraded to 1.7.0 (minimum 1.3.1), fixing five advisories in 0.52.1, including NTLM credential disclosure when serving static files on native Windows.
- **Security:** a browser `Origin` header must now be the Baton server itself; foreign, invalid and `null` origins get 403, as the MCP transport spec requires. Native MCP clients send no `Origin` and are unaffected. **Breaking** only for setups that reached Baton from a page on another origin, which was never supported.
- **Security:** `Host` headers must be exactly `host[:port]`. Malformed ones (with paths, queries, userinfo or bad ports) are refused, even when `BATON_ALLOWED_HOSTS=*`.
- MCP tool annotations are accurate per tool: saves, claims, resumes and completions no longer claim idempotency (they're retry-safe only with the same `operation_id`), and `baton_memory_update` is marked destructive because it can overwrite a memory.
- The memory tools' JSON schemas use `minimum` for revisions (Pydantic 2.13 emitted a non-standard `ge`).
- Minimum `mcp` version is 1.30; earlier versions failed at startup. CI tests the minimum versions on Python 3.10.
- Dashboard: selecting a handoff shows a loading state immediately, so **Copy resume prompt** can no longer copy the previously open handoff on a slow connection. An empty search or filter says "No matching handoffs" with **Clear filters**. The 15-second refresh keeps keyboard focus and list scroll; opening a handoff moves focus to its title, and Back returns it to the row. Dialogs have accessible names; the connect dialog adds a read-only connection check and a link to every client's setup. Completed handoffs show their outcome.
- Packaging: the Docker image and wheel include `LICENSE` and `README.md`. CI adds a dependency audit, packaging checks, Windows tests, and a Docker smoke test under the Compose restrictions with a restart.
- Project: `SECURITY.md`, `CONTRIBUTING.md`, Dependabot, package links, and an accurate pre-1.0 compatibility policy. Documentation: shorter README and usage guide, a new API reference, complete backup, restore and update steps, and an accurate description of the browser protections.


## 0.11.0 — 2026-10-09

- **Hosting:** `create_app(mcp_challenge=...)` sets the `WWW-Authenticate` value for unauthenticated `/mcp` requests, so a host can point MCP clients at its OAuth metadata (MCP authorization spec, RFC 9728).
- **Dashboard:** when the host's `/api/session` reports `"mcp_sign_in": true`, **Connect your agents** tells people to add the URL and sign in through the browser, with no token in the commands; creating an access token becomes the fallback.

## 0.10.1 — 2026-10-09

- Dashboard on phones and small tablets: host account links (such as Access tokens) and **Sign out** move behind an account button in the top bar, which opens a bottom sheet. They no longer sit in a loose row under the status chips. Desktop is unchanged.

## 0.10.0 — 2026-10-09

- **Breaking: `baton_push` is now `baton_save`.** One verb everywhere: you *save* a handoff and *resume* it. Update anything that calls the tool by name (scripts, custom prompts, allowlists such as Claude Code's `mcp__baton__baton_push` permission). Agents pick up the new name automatically from the server. Saves made through the old name aren't recognised as retries of `baton_save`.
- **Dashboard redesign.** Phones and small tablets show one pane at a time: the list, then a full-screen handoff or memory with a Back button that returns to the same place in the list. Status filters become a row of chips under a compact top bar. On desktop the list keeps its own scroll beside the detail. The detail leads with status, title, sender → recipient and the copy actions, then objective, state and numbered next steps; metadata moves to a Details section. Larger, higher-contrast text, an automatic dark theme, and an empty state that explains save → resume.
- Wording: the docs, dashboard, `save` prompt and agent instructions say "save a handoff" instead of "upload". Agents still treat "upload a handoff" (or "push", or "hand off") as a save request.
- Licensed under the Apache License 2.0.
- **Port:** the server now listens on **8765** everywhere (`baton serve` default, container, Compose and health check). Earlier versions listened on 8080 inside the container and published it as 8765. If you customised `compose.yaml` or run the image directly, map `8765:8765`.
- The CLI's default `--url` is `http://127.0.0.1:8765/mcp`.
- Continuous integration runs the full test suite, including browser tests.
- Documentation fixes (Hermes tool names) and removal of internal planning material.
- Documentation: a how-it-works diagram, a step-by-step quickstart, and dashboard screenshots in the README and guides (`docs/images/`), regenerated by `scripts/screenshots.py` from synthetic data.
- Setup instructions for Meta's Muse Code ([clients/muse-code.json](clients/muse-code.json)).
- Dashboard: spacing fixed under the **Copy MCP URL** button in the connection dialog.

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
