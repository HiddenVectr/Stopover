---
name: stopover-save
description: Save the current conversation as a Stopover handoff. Use only when the user invokes $stopover-save.
---

Save a handoff to Stopover so the user can continue this conversation later or in another agent, using the Stopover MCP server's `stopover_save` tool and its save instructions.

Anything the user wrote after `$stopover-save` is optional: if it names an agent (for example Claude Code or Cursor), set it as the handoff's target; treat the rest as what to emphasise.

Reply with the saved ID and the line `Resume Handoff <id>`.
