# Operating Baton

Storage, backups, retention, configuration, import/export and the security model of a Baton server. For remote access, see [Tailscale deployment](remote-http.md).

## Configuration

Set these in the Compose service's `environment` (or the shell, when running without Docker):

| Variable | Default | Meaning |
| --- | --- | --- |
| `BATON_DATA_DIR` | `/data` | Directory holding the SQLite database. Same as `--data-dir`. |
| `BATON_ALLOWED_HOSTS` | (empty) | Extra `Host` names or IPs to accept, comma-separated, besides `localhost`, `127.0.0.1`, `::1` and `*.ts.net`. A leading `*.` matches subdomains; `*` turns the check off. |
| `BATON_RETENTION_DAYS` | (unset) | Delete completed handoffs older than this many days. |
| `BATON_URL` | `http://127.0.0.1:8765/mcp` | MCP URL used by the `import` and `export` CLI commands. |

The pre-rename `HANDOFF_*` names still work as fallbacks.

## Storage, restart and backup

The `baton_baton_data` local Docker volume contains SQLite. Container replacement preserves the saved handoffs; there is exactly one database owner. Stop with `docker compose stop`, restart with `docker compose up -d`. **Do not use `docker compose down -v` if you want to keep handoffs.**

For a backup, stop the service cleanly, copy the whole volume (including SQLite sidecars) to protected local storage, and restart. Restore into a separate volume while stopped and verify SQLite integrity before using it. Backups include task context and personal memories. Forgetting a memory does not remove copies from old backups or other harnesses. Claim tokens are stored as SHA-256 hashes; the raw token stays in its acquire receipt only while that claim is active, so a lost response can still be retried. An old access-token file may remain from earlier versions; this version does not read or create it. Encrypted database storage is not part of this MVP.

Delete individual handoffs with `baton_delete`. To delete completed handoffs automatically, set `BATON_RETENTION_DAYS` (for example `90`) in the Compose service's `environment`; completed records older than that are removed, with their history, during later writes. Upgrading from 0.1.x migrates the database in place on first start (schema 2); back up the volume first, because 0.1.x cannot open the migrated store.

## Import and export

The CLI talks to the existing service through MCP. It never writes directly to SQLite.

```sh
# This example is marked manual_import and contains a stable operation ID.
docker exec -i baton python -m baton import - < examples/push.json

# An archival envelope, including current metadata and outcome:
docker exec baton python -m baton export HANDOFF_ID > handoff-export.json
```

An archival envelope is not a valid push request. To import its source into another store, prepare `{ "operation_id": "NEW-UUIDV4", "record": ... }`, mark `source.transfer_method="manual_import"`, and remove or resolve any parent ID. Exported source context is data, not instructions to execute.

## Security model

The web/API and MCP listener are published only on IPv4 loopback. The service has no outbound API calls, telemetry, URL fetching, project filesystem mount or Docker socket mount. Baton contents shown to an AI client can still be sent to that client's model provider. Do not put secrets in summaries. The web dashboard is a viewer; agents mutate handoffs and personal memories through MCP. Baton requires no authentication, and it rejects requests with an unexpected `Host` header. Keep the published port on loopback and use Tailscale Serve with restricted tailnet access for remote connections. Anyone who can reach the service can access the shared inbox; do not expose this token-free service to the public internet.
