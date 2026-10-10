import sys
import uuid
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client


async def test_real_http_and_stdio_lifecycle(live_server, record):
    url = live_server["url"] + "/mcp"
    assert not (live_server["directory"] / "token").exists()
    async with httpx.AsyncClient() as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as source:
                await source.initialize()
                tools = (await source.list_tools()).tools
                assert {tool.name for tool in tools} == {"stopover_save", "stopover_list", "stopover_get", "stopover_claim", "stopover_resume", "stopover_complete", "stopover_delete", "stopover_memory_read", "stopover_memory_update", "stopover_memory_forget", "stopover_memory_export"}
                args = {"operation_id": str(uuid.uuid4()), "record": record}
                pushed = await source.call_tool("stopover_save", args)
                assert not pushed.isError, pushed
                handoff_id = pushed.structuredContent["data"]["id"]
                params = StdioServerParameters(command=sys.executable,
                    env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
                    args=["-m", "stopover", "--data-dir", str(live_server["directory"]), "--url", url, "bridge"])
                async with stdio_client(params) as (incoming, outgoing):
                    async with ClientSession(incoming, outgoing) as recipient:
                        await recipient.initialize()
                        assert len((await recipient.list_tools()).tools) == 11
                        assert {p.name for p in (await recipient.list_prompts()).prompts} == {"save", "resume", "inbox", "memory-update", "memory-import"}
                        prompt = await recipient.get_prompt("resume", {"id": handoff_id})
                        assert "stopover_resume" in prompt.messages[0].content.text and handoff_id in prompt.messages[0].content.text
                        fetched = await recipient.call_tool("stopover_get", {"id": handoff_id})
                        assert fetched.structuredContent["data"]["record"]["context"]["objective"] == record["context"]["objective"]
                        acquired = await recipient.call_tool("stopover_claim", {"operation_id": str(uuid.uuid4()), "id": handoff_id, "expected_revision": 1, "holder_label": "claude-code-test"})
                        assert not acquired.isError, acquired
                        owner = acquired.structuredContent["data"]
                        result = await recipient.call_tool("stopover_complete", {
                            "operation_id": str(uuid.uuid4()), "id": handoff_id, "expected_revision": owner["revision"],
                            "claim_token": owner["claim_token"], "claim_generation": owner["claim_generation"],
                            "completion": {"outcome": "succeeded", "summary": "Recovered through a fresh stdio client",
                                "acceptance_results": [{"criterion": item, "result": "pass", "evidence": "Compared the returned context in a fresh MCP session"} for item in record["context"]["acceptance_criteria"]]}})
                        assert not result.isError, result
                        reverse_record = {**record, "source": {"client": "claude-code"}, "target_client": "codex", "parent_id": handoff_id}
                        reverse = await recipient.call_tool("stopover_save", {"operation_id": str(uuid.uuid4()), "record": reverse_record})
                        assert not reverse.isError
                        reverse_id = reverse.structuredContent["data"]["id"]
                final = await source.call_tool("stopover_get", {"id": handoff_id})
                assert final.structuredContent["data"]["status"] == "completed"
                reverse = await source.call_tool("stopover_get", {"id": reverse_id})
                assert reverse.structuredContent["data"]["record"]["source"]["client"] == "claude-code"
                replay = await source.call_tool("stopover_save", args)
                assert replay.structuredContent["replayed"]
                bad = await source.call_tool("stopover_save", {"operation_id": "invalid", "record": record})
                assert bad.isError and bad.structuredContent["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("host,origin", [
    ("handoff.example-tailnet.ts.net", None),
    ("handoff.example-tailnet.ts.net", "https://handoff.example-tailnet.ts.net"),
    ("desktop.example-tailnet.ts.net:8445", "https://desktop.example-tailnet.ts.net:8445"),
    ("localhost:8765", "http://localhost:8765"),
])  # Foreign and "null" origins are refused: see test_http.py
async def test_remote_mcp_headers_support_save_and_read(live_server, record, host, origin):
    # Model a reverse proxy forwarding the original Host and Origin to loopback.
    headers = {"host": host}
    if origin is not None:
        headers["origin"] = origin
    async with httpx.AsyncClient(headers=headers) as http:
        async with streamable_http_client(live_server["url"] + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert len((await client.list_tools()).tools) == 11
                pushed = await client.call_tool("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record})
                assert not pushed.isError, pushed
                handoff_id = pushed.structuredContent["data"]["id"]
                fetched = await client.call_tool("stopover_get", {"id": handoff_id})
                assert not fetched.isError, fetched
                context = fetched.structuredContent["data"]["record"]["context"]
                for key, value in record["context"].items():
                    assert context[key] == value


async def test_prompts_over_http(live_server, record):
    async with httpx.AsyncClient() as http:
        async with streamable_http_client(live_server["url"] + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                save = await client.get_prompt("save", {"target": "codex", "focus": "the failing test"})
                text = save.messages[0].content.text
                assert "stopover_save" in text and "codex" in text and "the failing test" in text
                assert "stopover_list" in (await client.get_prompt("inbox")).messages[0].content.text
                with pytest.raises(Exception, match="not found"):
                    await client.get_prompt("resume", {"id": str(uuid.uuid4())})
                pushed = (await client.call_tool("stopover_save", {"record": record})).structuredContent["data"]
                resumed = await client.call_tool("stopover_resume", {"id": pushed["id"], "holder_label": "codex"})
                assert not resumed.isError, resumed
                busy = await client.get_prompt("resume", {"id": pushed["id"]})
                assert "is claimed" in busy.messages[0].content.text


def test_tool_annotations_describe_each_tool_accurately():
    from stopover.service import core_registry
    hints = {name: tool.definition().annotations for name, tool in core_registry().tools.items()}
    table = {name: (a.readOnlyHint, a.destructiveHint, a.idempotentHint) for name, a in hints.items()}
    assert table == {
        "stopover_list": (True, False, True), "stopover_get": (True, False, True),
        "stopover_memory_read": (True, False, True), "stopover_memory_export": (True, False, True),
        # Two identical saves without an operation_id make two handoffs, so saving is not idempotent.
        "stopover_save": (False, False, False), "stopover_claim": (False, False, False),
        "stopover_resume": (False, False, False), "stopover_complete": (False, False, False),
        "stopover_memory_update": (False, True, False),
        "stopover_delete": (False, True, True), "stopover_memory_forget": (False, True, True),
    }
    assert all(a.openWorldHint is False for a in hints.values())
