---
name: stopover-resume
description: Resume a Stopover handoff by ID, or pick one from the inbox. Use only when the user invokes $stopover-resume.
---

If the user gave a handoff ID after `$stopover-resume`, treat the request as `Resume Handoff <id>`: call the Stopover MCP server's `stopover_resume` tool with that ID and continue the work.

If no ID was given, list the Stopover handoffs that are ready to resume (title, project, source agent, age and ID) with `stopover_list` and ask which one to resume. Don't claim anything until the user chooses.
