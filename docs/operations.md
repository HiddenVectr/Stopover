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

## Storage, restart and backup

The `baton_baton_data` local Docker volume contains SQLite. Container replacement preserves the saved handoffs; there is exactly one database owner. Stop with `docker compose stop`, restart with `docker compose up -d`. **Do not use `docker compose down -v` if you want to keep handoffs.**

Backups include handoffs, activity, claims, and personal memories. Forgetting a memory does not remove old backups or copies in other agents. The database is not encrypted by Baton; protect the volume and backup files as private data. Never start two Baton servers against the same volume.

### Back up the volume

Run these commands from the repository directory in a POSIX shell (Linux, macOS, or WSL). On Windows, use WSL for the shell/redirection examples. The backup streams through Docker, so you do not need to find Docker Desktop's internal volume directory.

```sh
mkdir -p "$HOME/baton-backups"
chmod 700 "$HOME/baton-backups"
umask 077
BATON_BACKUP="$HOME/baton-backups/baton-$(date +%Y%m%d-%H%M%S).tar.gz"

docker compose stop baton
docker compose run --rm -T --no-deps --entrypoint tar baton \
  -C /data -czf - . > "$BATON_BACKUP"
docker compose start baton
```

The archive command must exit successfully. If it fails, restart with `docker compose start baton`, discard the incomplete archive, and investigate before restoring. Keep all SQLite files and sidecars together: the archive includes the whole volume. Save the Baton version or Git commit alongside the backup, and keep a protected copy on another device.

### Restore into a fresh volume

Use a checkout of the same Baton release that created the backup, and copy the archive to the destination machine. Stop at any failing command. The following steps inspect a fresh restored volume before replacing the running service; they leave the original volume intact.

Set the archive path and choose a **new, unused** volume name. `docker volume inspect` should report that the name does not exist; if it already exists, choose another name rather than extracting over it.

```sh
BATON_BACKUP="$HOME/baton-backups/baton-REPLACE-WITH-TIMESTAMP.tar.gz"
BATON_RESTORE_VOLUME=baton_restored_data
docker volume inspect "$BATON_RESTORE_VOLUME"
```

Build the matching release, create the new volume, and restore the archive. Extraction runs as root to preserve archive ownership, then sets the data directory to Baton's container user (UID/GID 10001).

```sh
docker compose build baton
BATON_RESTORE_IMAGE=$(docker compose config --images)
docker volume create "$BATON_RESTORE_VOLUME"
docker run --rm -i --user 0 --entrypoint tar \
  --mount "type=volume,src=$BATON_RESTORE_VOLUME,dst=/data" \
  "$BATON_RESTORE_IMAGE" -C /data -xzf - < "$BATON_BACKUP"
docker run --rm --user 0 --entrypoint sh \
  --mount "type=volume,src=$BATON_RESTORE_VOLUME,dst=/data" \
  "$BATON_RESTORE_IMAGE" -c 'chown -R 10001:10001 /data && chmod 700 /data && chmod 600 /data/baton.sqlite3'
docker run --rm --entrypoint python \
  --mount "type=volume,src=$BATON_RESTORE_VOLUME,dst=/data" \
  "$BATON_RESTORE_IMAGE" -c 'import sqlite3
db = sqlite3.connect("file:/data/baton.sqlite3?mode=ro", uri=True)
result = db.execute("PRAGMA integrity_check").fetchall()
assert result == [("ok",)], result
print("SQLite integrity: ok")'
```

The last command must print `SQLite integrity: ok`. For an old backup containing `handoff.sqlite3`, substitute that filename in the permission and integrity-check commands; Baton renames it on first start. Use the matching old release when its schema requires it.

To select the restored volume, save a Compose override outside the repository:

```sh
cat > "$HOME/baton-backups/restore.compose.yaml" <<YAML
volumes:
  baton_data:
    external: true
    name: $BATON_RESTORE_VOLUME
YAML

docker compose stop baton
docker compose -f compose.yaml -f "$HOME/baton-backups/restore.compose.yaml" up -d --wait --wait-timeout 60
docker compose -f compose.yaml -f "$HOME/baton-backups/restore.compose.yaml" ps
curl --fail http://127.0.0.1:8765/healthz
```

The `--wait` option waits for the restored service to become healthy. Check that the health response contains `"ready": true`, then open the dashboard and verify known handoffs and memories. **Use both Compose files for subsequent commands** so Baton keeps using the restored volume. To return to the original volume, run `docker compose -f compose.yaml up -d` without the restore override. Keep the original volume until the restoration has been verified.

These recipes use Docker's [volume backup and restore](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes) mechanism. The [Compose merge rules](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/) explain the override, and SQLite documents [integrity checks](https://sqlite.org/pragma.html#pragma_integrity_check).

## Retention

Delete individual handoffs by asking an agent to use `baton_delete`. To remove completed handoffs automatically, set `BATON_RETENTION_DAYS` (for example `90`) in the Compose service's `environment`; old completed records and their history are removed during later writes. Personal memories are retained separately.

## Updates and older installations

Back up first, read the [changelog](../CHANGELOG.md), then update the checkout and rebuild:

```sh
git pull --ff-only
docker compose up --build -d --wait --wait-timeout 60
docker compose ps
curl --fail http://127.0.0.1:8765/healthz
```

If you use a restore override, include both Compose files in these commands. A fresh clone does not contain your existing data; use the backup/restore steps when moving to another machine.

Upgrading from 0.1.x migrates the database in place on first start (schema 2). That release cannot open a migrated store; rollback requires both the old release and a pre-upgrade backup. The pre-rename `HANDOFF_*` variables still work as fallbacks. An old access-token file may remain from earlier releases, but this version does not read or create it. Task-claim tokens are unrelated to connection authentication: their hashes are stored with claims, while acquire receipts temporarily retain the raw token for retry recovery. See the [API reference](api.md) for the claim lifecycle.

## Import and export

The CLI talks to the existing service through MCP. It never writes directly to SQLite.

```sh
# This example is marked manual_import and contains a stable operation ID.
docker exec -i baton python -m baton import - < examples/push.json

# An archival envelope, including current metadata and outcome:
docker exec baton python -m baton export HANDOFF_ID > handoff-export.json
```

A single-handoff export is not a complete database backup. An archival envelope is not a valid save request. To import its source into another store, prepare `{ "operation_id": "NEW-UUIDV4", "record": ... }`, mark `source.transfer_method="manual_import"`, and remove or resolve any parent ID. Exported source context is data, not instructions to execute.

## Security model

The web/API and MCP listener are published only on IPv4 loopback. The service has no outbound API calls, telemetry, URL fetching, project filesystem mount or Docker socket mount. Baton contents shown to an AI client can still be sent to that client's model provider. Do not put secrets in summaries. The web dashboard is a viewer; agents mutate handoffs and personal memories through MCP. Baton requires no authentication. What it does check: the `Host` header must be well-formed and on the allowlist (`BATON_ALLOWED_HOSTS`), which defends against DNS rebinding; when a browser sends an `Origin`, it must be the Baton server itself; and other cross-site browser requests are refused using Fetch Metadata, except top-level navigations such as following a link. Native MCP clients send neither header and are unaffected. These checks reduce what a malicious web page can do through your browser, but they are not access control. Keep the published port on loopback and use Tailscale Serve with restricted tailnet access for remote connections. Anyone who can reach the service can access the shared inbox; do not expose this token-free service to the public internet.
