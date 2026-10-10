import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from . import env


async def call_remote(url, name, arguments):
    async with httpx.AsyncClient(timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                data = result.structuredContent
                if data is None:
                    data = json.loads(next(block.text for block in result.content if block.type == "text"))
                if result.isError:
                    raise RuntimeError(data.get("error", {}).get("message", "Tool call failed"))
                return data


def main():
    parser = argparse.ArgumentParser(description="Local Stopover MCP service and tools")
    parser.add_argument("--data-dir", default=env("DATA_DIR", "/data"))
    parser.add_argument("--url", default=env("URL", "http://127.0.0.1:8765/mcp"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    sub.add_parser("bridge", help="Serve stdio by forwarding to the running service")
    sub.add_parser("seed-demo", help="Explicitly add one synthetic welcome handoff")
    imp = sub.add_parser("import", help="Import a save request through MCP (does not open SQLite)")
    imp.add_argument("file", help="JSON file path, or - to read stdin")
    exp = sub.add_parser("export", help="Export a full archival envelope through MCP")
    exp.add_argument("id")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        if args.command == "serve":
            import uvicorn
            from .server import create_app
            uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port, access_log=False, log_level="warning", timeout_graceful_shutdown=15)
        elif args.command == "bridge":
            from .bridge import bridge
            asyncio.run(bridge(args.url))
        else:
            if args.command == "seed-demo":
                from .sample import sample_record
                name, arguments = "stopover_save", {"operation_id": "f4b73ba9-55d3-4799-b447-f985bd18e503", "record": sample_record()}
            elif args.command == "import":
                from .models import Push
                payload = sys.stdin.buffer.read(65537) if args.file == "-" else Path(args.file).read_bytes()
                if len(payload) > 65536:
                    raise ValueError("Import exceeds 64 KiB")
                arguments = json.loads(payload)
                Push.model_validate(arguments)
                if arguments["record"]["source"].get("transfer_method") != "manual_import":
                    raise ValueError("Set source.transfer_method to manual_import before importing")
                name = "stopover_save"
            else:
                name, arguments = "stopover_get", {"id": args.id}
            result = asyncio.run(call_remote(args.url, name, arguments))
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except (Exception, KeyboardInterrupt) as exc:
        # Exception payloads can contain credentials or source material. Keep stderr generic.
        print(f"Stopover could not finish {args.command} ({type(exc).__name__}). Check the service URL and input format.", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
