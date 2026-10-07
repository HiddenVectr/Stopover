"""Verify the running container; creates one labeled, completed test handoff."""
import argparse
import asyncio
import json
import uuid

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from handoff.sample import sample_record
from handoff.models import Record


async def check(verify_id=None):
    async with httpx.AsyncClient() as http:
        async with streamable_http_client("http://127.0.0.1:8765/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as sender:
                await sender.initialize()
                if verify_id:
                    result = await sender.call_tool("handoff_get", {"id": verify_id})
                    assert not result.isError and result.structuredContent["data"]["status"] == "completed"
                    print(json.dumps({"persisted_after_restart": True, "id": verify_id, "revision": result.structuredContent["data"]["revision"]}))
                    return
                record = sample_record("codex-protocol-check", "claude-code-protocol-check")
                record['title'] = 'Local MCP transport verification (automated test)'
                record['project_key'] = 'handoff-check'
                record['context'].update(
                    objective="Verify that the running container's HTTP and stdio endpoints share the same persistent store.",
                    current_state="An automated local protocol check. No model inference is involved.",
                    next_steps=[{"id": "verify", "action": "Fetch the record through a fresh Docker stdio client and finish its lifecycle.", "done_when": "The HTTP client sees the same handoff completed."}],
                    acceptance_criteria=["A fresh Docker stdio client retrieves the exact saved context and records a completed lifecycle."])
                args = {"operation_id": str(uuid.uuid4()), "record": record}
                saved = await sender.call_tool("handoff_push", args)
                assert not saved.isError, saved
                handoff_id = saved.structuredContent["data"]["id"]
                params = StdioServerParameters(command="docker", args=["exec", "-i", "handoff", "python", "-m", "handoff", "bridge"])
                async with stdio_client(params) as (incoming, outgoing):
                    async with ClientSession(incoming, outgoing) as receiver:
                        await receiver.initialize()
                        assert len((await receiver.list_tools()).tools) == 11
                        fetched = await receiver.call_tool("handoff_get", {"id": handoff_id})
                        assert fetched.structuredContent["data"]["record"]["context"] == Record.model_validate(record).model_dump(mode="json")["context"]
                        claimed = await receiver.call_tool("handoff_claim", {"operation_id": str(uuid.uuid4()), "id": handoff_id, "expected_revision": 1, "holder_label": "fresh-stdio-test-client"})
                        assert not claimed.isError, claimed
                        claim = claimed.structuredContent["data"]
                        completed = await receiver.call_tool("handoff_complete", {"operation_id": str(uuid.uuid4()), "id": handoff_id,
                            "expected_revision": claim["revision"], "claim_token": claim["claim_token"], "claim_generation": claim["claim_generation"],
                            "completion": {"outcome": "succeeded", "summary": "HTTP source and fresh Docker stdio recipient shared the same context and lifecycle. This is a protocol test, not a model conversation.",
                                "acceptance_results": [{"criterion": item, "result": "pass", "evidence": "The fresh MCP client retrieved and compared the source context through the container's stdio adapter."} for item in record["context"]["acceptance_criteria"]]}})
                        assert not completed.isError, completed
                replay = await sender.call_tool("handoff_push", args)
                assert replay.structuredContent["replayed"]
                final = await sender.call_tool("handoff_get", {"id": handoff_id})
                assert final.structuredContent["data"]["status"] == "completed"
                print(json.dumps({"http_stdio_roundtrip": True, "id": handoff_id, "status": "completed", "retry_deduplicated": True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-id')
    args = parser.parse_args()
    asyncio.run(check(args.verify_id))
