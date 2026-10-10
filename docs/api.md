# API reference

Exact MCP tool contracts for integrations and custom scripts. For everyday requests such as saving and resuming work, see [Using Baton](usage.md).

The server exposes eleven tools over Streamable HTTP at `/mcp`; the stdio bridge exposes the same tools. Inputs are validated against the [committed schemas](../schemas/), generated from the Python models. HTTP request bodies are limited to 64 KiB; individual records and memory batches have smaller limits described below. Agents build tool arguments from your request and available context.

## Handoff tools

| Tool | Behavior |
| --- | --- |
| `baton_save` | Validate and save immutable source context. Return an ID and receipt. |
| `baton_list` | Filter and paginate summaries; defaults to available handoffs. Use `status="all"` for all records. |
| `baton_get` | Return every record field and the current lifecycle state, without changing anything. |
| `baton_resume` | Claim a handoff and return its full record plus the claim token, in one call. Fails with `ALREADY_CLAIMED` or `ALREADY_COMPLETED`. |
| `baton_claim` | Acquire, renew or release a lease. Acquire returns a claim token; renew and release need only the ID and token. |
| `baton_complete` | Record success, blocked work or abandonment, using the claim token. |
| `baton_delete` | Permanently delete a handoff and its history (refused while another agent holds an active claim). Agents are told to use it only on explicit request. |

Task mutations (except deletion) accept an optional `operation_id` (any UUID, any case). Supply one to make retries safe: after uncertain delivery, retry the **identical request and operation ID**. Changing its arguments returns `IDEMPOTENCY_CONFLICT`. Without an operation ID, a retry creates a second record or action. The `replayed` flag means the receipt is historical: fetch current state before relying on an old claim. Receipts are kept for 7 days; a retry after that is treated as a new request.

The tools' MCP annotations follow the same rule. Only the read tools, `baton_delete` and `baton_memory_forget` advertise `idempotentHint`, because repeating them with identical arguments changes nothing further. Saves, claims, resumes and completions are retry-safe only when the same `operation_id` is reused, so they don't. `baton_delete`, `baton_memory_forget` and `baton_memory_update` (which can overwrite a memory) advertise `destructiveHint`, so clients may ask before calling them.

Claims default to 1 hour (60–86,400 seconds allowed). An expired claim shows as available, but its holder can still renew, release or complete it until another agent acquires the handoff; the new claim's token fences out the old one. Renewal is therefore only needed to stop someone else taking over during long work. `expected_revision` and `claim_generation` are optional extra checks. A claim coordinates ownership; it does not make external file edits exactly once.

The minimum record requires `title`, `source.client`, and `context` with `objective`, `current_state`, at least one `next_steps` entry (`id`, `action`, `done_when`), and at least one `acceptance_criteria` string. Optional fields have stable defaults. [examples/push.json](../examples/push.json) is a complete importable save request. The MCP schemas expose all fields and limits.

For `outcome="succeeded"`, completion must report one passing result with nonempty evidence for each original acceptance criterion. Identify each criterion by `index` (0-based, in the record's order) or by its text; text matching ignores case and whitespace. A mismatch error lists the original criteria with their indexes. Use `blocked` or `abandoned` for an unfinished attempt, or release the claim to leave it available. Corrections/continuations use a new save with `parent_id`; source records are never silently rewritten.

## Personal-memory tools

Personal memories are separate from task claims and completion, and are not removed by handoff retention. All connected clients use one shared collection; the self-hosted server has no per-user partitioning.

| Memory tool | Contract |
| --- | --- |
| `baton_memory_read` | Read by `key`, `category`, or `q`; paginate with `limit` (1–50) and `cursor`. Use `include_deleted=true` for full reconciliation. |
| `baton_memory_update` | Atomic batch of 1–50 entries under 48 KiB. Requires the updating `client` and `memories`; `operation_id` (any UUID) is optional but makes retries safe; optional `coverage` is echoed for the capture report (not retained in receipts); `partial=true` applies non-conflicting entries and reports the rest as `action: "conflict"`. Each entry has a stable topic `key`, `content`, and `expected_revision` (0 for new keys). Optional category, basis, evidence and `source` (defaults to the updating client) preserve meaning/provenance; `recreate=true` re-establishes a forgotten key. |
| `baton_memory_forget` | Explicit user-requested deletion; entries contain `key` and an optional `expected_revision` check, and `operation_id` is optional. Removes the active content and evidence, leaving an ID/key/revision deletion marker. |
| `baton_memory_export` | Same pagination/filtering as read, plus `format=json` or `markdown`; each page includes structured entries, schema version, store revision, and continuation cursor. Follow all pages for a full snapshot. |

Topic keys are normalized to lowercase, with spaces turned into dashes, and identify individual facts (for example `communication.response_length`). Reuse keys to avoid duplicates. Semantic reconciliation belongs to the harness; the server does not run an LLM or infer whether differently worded entries refer to the same fact. `source` records the original evidence, while `client` identifies the harness performing the update. An entry whose content, category and basis match the stored memory is unchanged: it keeps its revision and original `source`, so re-syncing the same fact from another harness does not rewrite provenance. When only category or basis change, the original source and evidence are kept.

Writes require the revisions read from the store. A conflict rolls back the **whole batch** (unless `partial=true`); the error lists every conflicting key with its current revision in `conflicts`. Reread those entries, reconcile, and use a fresh operation UUID. For uncertain delivery, retry identical arguments with the same UUID. Receipts last seven days and contain only result IDs/revisions/actions, not memory bodies. A replay reports historical success; reread for current state. Deleted keys reject stale updates and resurrection with `MEMORY_DELETED`. If the user freshly states the memory again, save it under the same key with `recreate=true` and the deletion marker's revision; it gets a new memory ID.

`since_revision` returns changed entries, including deletion markers even when their erased content can no longer match a filter. After consuming all pages, save `store_revision` as the next checkpoint. A filtered read covers only that filter; use unfiltered reads for complete sync. Pagination continues across concurrent writes: every page reports the first page's `store_revision`, and anything written while you paginate has a higher revision, so the next `since_revision` read picks it up. `complete` means no further pages for this query, not that the source harness knew every fact about you.

The memory tables are added automatically to existing schema-2 databases without changing task records. Back up the data volume before upgrading. Tombstones count toward the 10,000 memory-key limit; deletion removes content from application queries, not historical backups or forensic disk traces. Other harnesses learn deletions only when they retrieve them.

## Prompts

The server exposes `save`, `resume`, `inbox`, `memory-update`, and `memory-import`. Client-specific shortcuts are described in [Using Baton](usage.md#optional-shortcuts). Prompts provide instructions to the receiving agent; they do not start agents or execute work independently.
