import asyncio
import os
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from baton.__main__ import call_remote


def test_dashboard_details_search_filters_mobile_and_safe_text(live_server, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    args["record"]["title"] = "Carry the release checklist into Claude Code"
    args["record"]["context"]["background"] = '<img src=x onerror="window.handoffInjected=true">'
    args["record"]["context"]["facts"] = [{"text": "The adapter was checked locally.", "basis": "observed", "evidence_ids": []}]
    saved = asyncio.run(call_remote(live_server["url"] + "/mcp", "baton_push", args))
    handoff_id = saved["data"]["id"]
    screenshots = Path(os.environ.get("BATON_SCREENSHOT_DIR", "/tmp/handoff-screenshots"))
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"])
        expect(page.get_by_role("heading", name="All handoffs", exact=True)).to_be_visible()
        expect(page.locator("#signin-dialog")).not_to_be_visible()
        expect(page.locator("#signout-button")).to_be_hidden()
        row = page.locator(".handoff-row").filter(has_text=args["record"]["title"])
        expect(row).to_be_visible()
        page.get_by_role("button", name="Connect your agents").click()
        expect(page.locator("#mcp-url")).to_have_text(live_server["url"] + "/mcp")
        expect(page.locator("#codex-add")).to_have_text("codex mcp add baton --url " + live_server["url"] + "/mcp")
        expect(page.locator("#setup-dialog")).not_to_contain_text("docker exec")
        page.get_by_role("button", name="Copy MCP URL").click()
        assert page.evaluate("navigator.clipboard.readText()") == live_server["url"] + "/mcp"
        page.get_by_role("button", name="Close connection instructions").click()
        row.click()
        expect(page.locator("#detail h2")).to_have_text(args["record"]["title"])
        expect(page.get_by_role("heading", name="Next steps", exact=True)).to_be_visible()
        expect(page.locator("#detail")).to_contain_text(args["record"]["context"]["background"])
        assert not page.evaluate("Boolean(window.handoffInjected)")
        expect(page.locator("#detail .timeline li")).to_have_count(1)
        page.screenshot(path=str(screenshots / "dashboard-desktop.png"), full_page=True)
        page.get_by_label("Search handoffs").fill("missing-record-search")
        expect(page.get_by_text("No handoffs here yet.")).to_be_visible()
        page.get_by_label("Search handoffs").fill("")
        expect(row).to_be_visible()
        page.get_by_role("button", name="Completed", exact=False).first.click()
        expect(page.get_by_text("No handoffs here yet.")).to_be_visible()
        page.locator('[data-status="all"]').click()
        expect(row).to_be_visible()
        page.get_by_role("button", name="Copy ID", exact=True).click()
        expect(page.locator("#toast")).to_have_text("Copied to clipboard")
        assert page.evaluate("navigator.clipboard.readText()") == handoff_id
        page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.reject(new Error('denied'))}, configurable: true})")
        page.get_by_role("button", name="Copy resume prompt").click()
        expect(page.get_by_label("Text to copy")).to_be_visible()
        assert handoff_id in page.get_by_label("Text to copy").input_value()
        page.get_by_role("button", name="Close copy text").click()
        page.goto(live_server["url"] + "/handoffs/" + handoff_id)
        expect(page.locator("#detail h2")).to_have_text(args["record"]["title"])
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "dashboard-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.reload()
        expect(page.locator("#detail h2")).to_have_text(args["record"]["title"])
        assert not any(cookie["name"] == "handoff_session" for cookie in context.cookies())
        assert not errors, errors
        browser.close()


def test_personal_memories_browse_search_refresh_and_mobile(live_server):
    from test_memory import entry, update, forget
    url = live_server['url']
    payload = '<img src=x onerror="window.memoryInjected=true">'
    args = update(*(entry(f'personal.topic{i:02}', payload if i == 0 else f'Personal memory number {i}') for i in range(25)))
    asyncio.run(call_remote(url + '/mcp', 'baton_memory_update', args))
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.get_by_role('button', name='Personal memories').click()
        expect(page.get_by_role('heading', name='Personal memories', exact=True)).to_be_visible()
        expect(page.locator('#memory-total')).to_have_text('25')
        expect(page.locator('.memory-row')).to_have_count(20)
        page.get_by_role('button', name='Load more memories').click()
        expect(page.locator('.memory-row')).to_have_count(25)
        page.locator('.memory-row').filter(has_text='personal.topic00').click()
        expect(page.locator('#memory-detail')).to_contain_text(payload)
        assert not page.evaluate('Boolean(window.memoryInjected)')
        page.get_by_role('button', name='Copy memory', exact=True).click()
        assert page.evaluate('navigator.clipboard.readText()') == payload
        page.get_by_label('Search personal memories').fill('number 24')
        expect(page.locator('.memory-row')).to_have_count(1)
        page.get_by_label('Search personal memories').fill('does-not-exist')
        expect(page.get_by_text('No matching memories.')).to_be_visible()
        page.get_by_label('Search personal memories').fill('')
        page.get_by_label('Filter memories by category').select_option('habit')
        expect(page.get_by_text('No matching memories.')).to_be_visible()
        page.get_by_label('Filter memories by category').select_option('preference')
        expect(page.locator('.memory-row')).to_have_count(20)
        page.goto(url + '/memories/personal.topic00')
        expect(page.locator('#memory-detail h2')).to_have_text('personal.topic00')
        corrected = update(entry('personal.topic00', 'A corrected personal preference.', revision=1), client='claude-code')
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(call_remote(url + '/mcp', 'baton_memory_update', corrected))).result()
        page.locator('#memory-refresh').click()
        expect(page.locator('#memory-detail')).to_contain_text('A corrected personal preference.')
        expect(page.locator('#memory-detail')).to_contain_text('claude-code')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshots = Path(os.environ.get('BATON_SCREENSHOT_DIR', '/tmp/handoff-screenshots'))
        screenshots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshots / 'memory-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.screenshot(path=str(screenshots / 'memory-desktop.png'), full_page=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(call_remote(url + '/mcp', 'baton_memory_forget', forget('personal.topic00', 26)))).result()
        page.locator('#memory-refresh').click()
        expect(page.locator('#memory-detail')).to_contain_text('FORGOTTEN MEMORY')
        expect(page.locator('#memory-detail')).not_to_contain_text('A corrected personal preference.')
        expect(page.locator('#memory-total')).to_have_text('24')
        page.locator('[data-status="all"]').click()
        expect(page.get_by_role('heading', name='All handoffs', exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_role('heading', name='Personal memories', exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()


def test_dashboard_signs_in_when_the_server_requires_a_token(tmp_path, record):
    import socket
    import threading
    import time
    import uvicorn
    from baton.context import RequestContext
    from baton.server import create_app

    async def auth(request):
        return RequestContext(actor="alice") if request.headers.get("authorization") == "Bearer good-token" else None

    app = create_app(tmp_path, auth=auth)
    app.state.service.execute("baton_push", {"record": record})
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            expect(page.locator("#signin-dialog")).to_be_visible()
            page.get_by_label("Access token").fill("bad-token")
            page.get_by_role("button", name="Sign in").click()
            expect(page.locator("#signin-error")).to_have_text("That token was not accepted.")
            page.get_by_label("Access token").fill("good-token")
            page.get_by_role("button", name="Sign in").click()
            expect(page.locator("#signin-dialog")).not_to_be_visible()
            expect(page.locator(".handoff-row").filter(has_text=record["title"])).to_be_visible()
            page.get_by_role("button", name="Connect your agents").first.click()
            expect(page.locator("#claude-add")).to_contain_text('--header "Authorization: Bearer YOUR_TOKEN"')
            expect(page.locator("#setup-dialog")).not_to_contain_text("good-token")
            page.get_by_role("button", name="Close connection instructions").click()
            page.reload()
            expect(page.locator(".handoff-row").filter(has_text=record["title"])).to_be_visible()
            expect(page.locator("#signin-dialog")).not_to_be_visible()
            page.get_by_role("button", name="Sign out").click()
            expect(page.locator("#signin-dialog")).to_be_visible()
            assert page.evaluate("localStorage.getItem('baton.accessToken')") is None
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_dashboard_redirects_to_host_login_and_shows_the_session(tmp_path, record):
    import socket
    import threading
    import time
    from urllib.parse import quote
    import uvicorn
    from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
    from starlette.routing import Route
    from baton.context import RequestContext
    from baton.server import create_app

    async def auth(request):
        return RequestContext(actor="alice") if request.cookies.get("sid") == "ok" else None

    async def login(request):
        target = quote(request.query_params.get("return_to", "/"))
        return HTMLResponse(f'<h1>Host login</h1><a id="continue" href="/fake-login/complete?return_to={target}">Continue</a>')

    async def complete(request):
        response = RedirectResponse(request.query_params.get("return_to", "/"), status_code=303)
        response.set_cookie("sid", "ok", httponly=True, samesite="lax")
        return response

    async def logout(request):
        response = JSONResponse({}, status_code=200)
        response.delete_cookie("sid")
        return response

    async def session(request):
        return JSONResponse({"user": {"login": "alice", "name": "Alice Example"}, "workspace": {"name": "Alice's workspace"},
                             "logout_url": "/fake-logout"})

    app = create_app(tmp_path, auth=auth, login_url="/fake-login", extra_routes=[
        Route("/fake-login", login), Route("/fake-login/complete", complete),
        Route("/fake-logout", logout, methods=["POST"]), Route("/api/session", session)])
    saved = app.state.service.execute("baton_push", {"record": record})["data"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"{url}/handoffs/{saved['id']}")
            expect(page.get_by_role("heading", name="Host login")).to_be_visible()
            assert f"return_to=%2Fhandoffs%2F{saved['id']}" in page.url
            page.locator("#continue").click()
            expect(page.locator("#detail h2")).to_have_text(record["title"])
            expect(page.locator("#workspace-name")).to_have_text("Alice's workspace")
            expect(page.locator("#workspace-detail")).to_have_text("Signed in as alice")
            expect(page.locator("#signin-dialog")).not_to_be_visible()
            page.get_by_role("button", name="Sign out").click()
            expect(page.get_by_role("heading", name="Host login")).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
