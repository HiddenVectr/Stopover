# Handoff

Carry a task from one AI conversation into another with enough context to continue.

**Status:** local-only MVP v1 plan, dated 2026-10-06. Nothing is implemented or running. This `outputs/` folder is the planning deliverable root.

The intended flow is: ask the source agent to prepare and push a structured handoff, open a fresh recipient session, then fetch, claim, resume, and complete it. Handoff transfers a task brief and evidence; it does not transfer hidden reasoning or launch an agent.

## Proposed v1

- One single-user MCP service in Docker; one persistent SQLite store.
- Five tools: `handoff_push`, `handoff_list`, `handoff_get`, `handoff_claim`, `handoff_complete`.
- Loopback HTTP plus a stdio adapter that forwards to the same service.
- Vendor-neutral, versioned JSON records, immutable task context, idempotent writes, and expiring claims.
- No cloud backend, tunnel, provider API calls, autonomous execution, or transcript scraping.

“Local-only” covers this service's storage and transport. The AI clients may still send handoff contents to their model providers for inference.

## ChatGPT → Claude Code

ChatGPT Desktop plugins may include local MCP apps; exact platform, account, conversation surface, and custom-plugin access still need testing. [OpenAI documentation](https://help.openai.com/en/articles/20001256-plugins-in-chatgpt)

The web MCP path needs a remote connection or tunnel and does not meet this v1 transport boundary. [Web MCP documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt)

**The original ChatGPT-to-Claude example is a release gate, not a tested integration.** Manual JSON export/import is an explicitly labeled fallback.

## Planning files

- [Implementation-ready MVP plan](docs/mvp-v1.md): contracts, storage, transport, compatibility gates, milestones, and acceptance tests.
- [Example push request](examples/handoff-push.json): synthetic task context; no actual conversation or repository is represented.

Start implementation with milestone M0: prove the target clients can use a local connection. All commands and configuration in the plan are proposals, not validated setup instructions.
