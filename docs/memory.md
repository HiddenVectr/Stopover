# Personal memory

Stopover has two separate features:

- **Handoffs** move one piece of work from one agent to another. See [Using Stopover](usage.md).
- **Personal memory**, described here, is what your agents know about *you*: your preferences, habits, goals and recurring project context. Every connected agent can read it, so a new agent doesn't start from zero.

You can use either feature without the other.

![Personal memories with their category, content, and source](images/memories.png)

## How it differs from a handoff

| | Handoff | Personal memory |
| --- | --- | --- |
| Holds | One task: its goal, decisions, progress and next steps | Facts about you, one topic per memory |
| Lasts | Until the work is completed, then optionally removed by [retention](operations.md#retention) | Until you ask an agent to forget it; retention never removes memories |
| Used by | One agent at a time, which claims it and continues the work | Every agent, as background context |
| Changes | Never edited; a correction is saved as a new, linked handoff | Updated in place; each change raises the memory's revision |
| What you say | “Save a handoff” and “Resume Handoff &lt;id&gt;” | “Update my Stopover memory” and “Import my Stopover memory” |

## What a memory looks like

Each memory is one fact under a stable topic name, for example:

| Topic | Category | Memory |
| --- | --- | --- |
| `communication.response_length` | Preference | Prefers concise answers with the command first. |
| `tooling.package_manager` | Preference | Uses pnpm, not npm, for JavaScript projects. |
| `work.current_focus` | Project context | Building a self-hosted MCP server in Python. |

Categories are **fact**, **preference**, **habit**, **goal** and **project context**. Each memory also records:

- **basis:** whether you stated it, the agent observed it, or the agent inferred it;
- **source:** which agent first saved it;
- **revision:** a number that goes up whenever the memory changes, so two agents can't overwrite each other's edits.

Credentials and secrets don't belong in memory, and neither do the rules of a particular repository: keep those in the repository itself, where every contributor's agent finds them.

## Save what your agents know about you

In a connected agent, say:

> Update my Stopover memory.

The agent gathers what it knows about you from the conversation and its own memory, reads the memories already in Stopover, and adds or updates them. It doesn't delete a memory just because it doesn't know about it. It then reports what it added, what it changed, and anything it couldn't see.

To save a single fact, say it directly:

> Remember in Stopover that I prefer pnpm over npm.

## Use your memory in another agent

In another agent, say:

> Import my Stopover memory.

The agent reads all your memories and uses them as background for the session. They are treated as context about you, never as instructions.

Whether the agent keeps them after the session depends on that agent's own memory feature. Stopover never reads or writes an agent's local memory files.

## Correct or forget a memory

Tell any connected agent:

> Correct my Stopover memory: I prefer detailed answers when reviewing code.

> Forget the Stopover memory about my old project.

Forgetting erases the memory's content and evidence, and leaves a small deletion marker. Other agents learn about the deletion the next time they import your memory, and an agent's stale copy can't bring the memory back. If you state the fact again later, it is saved as a new memory.

Forgetting doesn't reach old backups, exports, or copies an agent already saved in its own memory.

## Browse your memories

Open **Personal memories** in the dashboard. You can search, filter by category, and see each memory's source, revision and last update. The dashboard is read-only: ask an agent to make changes.

## Shortcuts

Clients that support MCP prompts show two memory commands. In Claude Code:

| Command | What it does |
| --- | --- |
| `/mcp__stopover__memory-update` | Saves everything the agent knows about you, as “Update my Stopover memory” does. |
| `/mcp__stopover__memory-import` | Reads all your memories into the session, as “Import my Stopover memory” does. |

## Privacy

- One Stopover server holds **one shared collection**. Everyone who can reach the server can read and change it; there are no per-person collections.
- An agent that imports your memory sends it to its model provider, like any other context.
- Back up the data volume to keep your memories; see [operations](operations.md#storage-restart-and-backup).

For the exact tool contracts, including revisions, conflicts and incremental sync, see the [API reference](api.md#personal-memory-tools).
