"""HTTP application: MCP endpoint, read-only dashboard API, and the extension points used by hosted builds."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Awaitable, Callable, Iterable

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, env
from .catalog import DESCRIPTIONS, INSTRUCTIONS, MEMORY_INSTRUCTIONS, SAVE_INSTRUCTIONS  # noqa: F401 (re-exported)
from .context import LOCAL, RequestContext
from .domain import DomainError
from .service import BatonService
from .store import Store

STATIC = Path(__file__).parent / "static"
DEFAULT_ALLOWED_HOSTS = ("localhost", "127.0.0.1", "::1", "*.ts.net")
Authenticator = Callable[[Request], Awaitable[RequestContext | None]]


def result_message(result):
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                                structuredContent=result, isError=not result.get("ok", False))


def request_context(request) -> RequestContext:
    """The caller's context, as set by the authentication layer; the local workspace when there is none."""
    return getattr(request.state, "handoff_ctx", LOCAL) if request is not None else LOCAL


def make_mcp(service: BatonService):
    registry = service.registry
    server = Server("baton", version=__version__, instructions=registry.server_instructions())

    def current_context():
        try:
            return request_context(server.request_context.request)
        except LookupError:
            return LOCAL

    @server.list_prompts()
    async def list_prompts():
        return [prompt.definition() for prompt in registry.prompts.values()]

    @server.get_prompt()
    async def get_prompt(name, arguments):
        text = await anyio.to_thread.run_sync(service.render_prompt, name, arguments, current_context())
        return types.GetPromptResult(messages=[types.PromptMessage(role="user", content=types.TextContent(type="text", text=text))])

    @server.list_tools()
    async def list_tools():
        return [tool.definition() for tool in registry.tools.values()]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        return result_message(await anyio.to_thread.run_sync(service.execute, name, arguments or {}, current_context()))

    return server


def parse_hosts(value):
    return [h.strip().lower() for h in (value or "").split(",") if h.strip()]


def host_allowed(header, patterns):
    if "*" in patterns:
        return True
    host = header.strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return bool(host) and any(host.endswith(p[1:]) if p.startswith("*.") else host == p for p in patterns)


class HostAllowlist:
    """Reject requests whose Host is not expected, which blocks DNS-rebinding attacks from web pages."""
    def __init__(self, app, allowed_hosts):
        self.app, self.allowed = app, list(allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            if not host_allowed(host, self.allowed):
                return await JSONResponse({"error": "Host not allowed. Add it to BATON_ALLOWED_HOSTS on the server."},
                                          status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)


class Authentication:
    """Run the configured authenticator for /mcp and /api/* and attach the resulting RequestContext."""
    def __init__(self, app, auth: Authenticator | None, login_url: str | None = None):
        self.app, self.auth, self.login_url = app, auth, login_url

    async def __call__(self, scope, receive, send):
        if self.auth and scope["type"] == "http" and (scope["path"] == "/mcp" or scope["path"].startswith("/api/")):
            ctx = await self.auth(Request(scope))
            if ctx is None:
                body = {"error": "Authentication required"}
                if self.login_url and scope["path"].startswith("/api/"):
                    body["login_url"] = self.login_url  # The dashboard redirects here to sign in.
                return await JSONResponse(body, status_code=401, headers={"www-authenticate": "Bearer"})(scope, receive, send)
            scope.setdefault("state", {})["handoff_ctx"] = ctx
        await self.app(scope, receive, send)


class MCPRoute:
    def __init__(self, manager):
        self.manager = manager

    async def __call__(self, scope, receive, send):
        await self.manager.handle_request(scope, receive, send)


class RequestBoundary:
    """Limit request bodies and apply browser protections across HTTP routes."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        # Native MCP clients do not send Fetch Metadata. Reject cross-site browser
        # requests even when a browser omits Origin (for example an image GET).
        # Top-level GET/HEAD navigations are allowed: following a link from another site, or a sign-in
        # provider redirecting back. The other site can't read the response, and nothing changes state.
        if headers.get(b"sec-fetch-site", b"").lower() == b"cross-site":
            navigation = (headers.get(b"sec-fetch-mode", b"").lower() == b"navigate"
                          and headers.get(b"sec-fetch-dest", b"document").lower() == b"document"
                          and scope["method"] in ("GET", "HEAD"))
            if not navigation:
                return await JSONResponse({"error": "Cross-site request not allowed"}, status_code=403)(scope, receive, send)
        # Enforce bytes even for chunked bodies; never trust Content-Length alone.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 65536:
                return await JSONResponse({"error": "Request exceeds 64 KiB"}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]}
            await send(message)
        await self.app(scope, replay, secure_send)


def create_app(directory=None, *, service: BatonService | None = None, auth: Authenticator | None = None,
               allowed_hosts: Iterable[str] | None = None, extra_routes: Iterable[BaseRoute] = (),
               middleware: Iterable[Middleware] = (), login_url: str | None = None):
    """Build the HTTP app.

    The local deployment calls this with no arguments. A hosted build passes its own service (backend and registry),
    an authenticator that maps requests to a RequestContext, its allowed hosts, and any extra routes or middleware.
    With login_url, unauthenticated dashboard API calls return it so the dashboard can redirect to sign in; a host can
    also serve GET /api/session ({"user": {...}, "workspace": {...}, "logout_url": ...}) to show the signed-in account.
    """
    if service is None:
        directory = directory or env("DATA_DIR", "/data")
        retention = env("RETENTION_DAYS")
        service = Store(directory, retention_days=float(retention) if retention else None)
    if allowed_hosts is None:
        allowed_hosts = [*DEFAULT_ALLOWED_HOSTS, *parse_hosts(env("ALLOWED_HOSTS"))]
    server = make_mcp(service)
    # Host checks happen in HostAllowlist, which supports wildcard domains; the SDK's exact-match check is off.
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True, max_request_body_size=65536,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    @asynccontextmanager
    async def lifespan(app):
        try:
            async with manager.run():
                yield
        finally:
            service.close()

    async def call(request, name, params):
        return await anyio.to_thread.run_sync(service.execute, name, params, request_context(request))

    async def page(request):
        return FileResponse(STATIC / "index.html")

    async def health(request):
        try:
            await anyio.to_thread.run_sync(service.ping)
        except Exception:
            return JSONResponse({"ready": False, "version": __version__}, status_code=503)
        return JSONResponse({"ready": True, "version": __version__})

    async def overview(request):
        return JSONResponse(await anyio.to_thread.run_sync(service.overview, request_context(request)))

    async def handoffs(request):
        params = dict(request.query_params)
        if "limit" in params:
            try:
                params["limit"] = int(params["limit"])
            except ValueError:
                return JSONResponse({"error": "Invalid limit"}, status_code=400)
        params.setdefault("status", "all")
        result = await call(request, "baton_list", params)
        return JSONResponse(result, status_code=200 if result["ok"] else 400)

    async def memories(request):
        params = dict(request.query_params)
        for key in ("limit", "since_revision"):
            if key in params:
                try:
                    params[key] = int(params[key])
                except ValueError:
                    return JSONResponse({"error": "Invalid " + key}, status_code=400)
        if "key" in request.path_params:
            params["key"] = request.path_params["key"]
            params["include_deleted"] = True
        result = await call(request, "baton_memory_read", params)
        return JSONResponse(result, status_code=200 if result["ok"] else 400)

    async def detail(request):
        result = await call(request, "baton_get", {"id": request.path_params["id"]})
        return JSONResponse(result, status_code=200 if result["ok"] else 404 if result["error"]["code"] == "NOT_FOUND" else 400)

    async def events(request):
        try:
            before = int(request.query_params["before"]) if "before" in request.query_params else None
            if before is not None and before <= 0:
                raise ValueError()
            result = await anyio.to_thread.run_sync(partial(service.events, request.path_params["id"], before, request_context(request)))
            return JSONResponse(result)
        except (ValueError, OverflowError):
            return JSONResponse({"error": "Invalid event cursor"}, status_code=400)
        except DomainError:
            return JSONResponse({"error": "Handoff not found"}, status_code=404)

    routes = [Route("/", page), Route("/handoffs/{id}", page), Route("/memories", page), Route("/memories/{key}", page),
              Route("/healthz", health), Route("/api/overview", overview), Route("/api/memories", memories),
              Route("/api/memories/{key}", memories), Route("/api/handoffs", handoffs),
              Route("/api/handoffs/{id}", detail), Route("/api/handoffs/{id}/events", events),
              Route("/mcp", MCPRoute(manager)), *extra_routes, Mount("/assets", app=StaticFiles(directory=STATIC))]
    # The first middleware is outermost: reject unknown hosts, then bound bodies, then authenticate.
    stack = [Middleware(HostAllowlist, allowed_hosts=allowed_hosts), Middleware(RequestBoundary),
             Middleware(Authentication, auth=auth, login_url=login_url), *middleware]
    app = Starlette(routes=routes, middleware=stack, lifespan=lifespan)
    app.state.store = app.state.service = service
    return app
