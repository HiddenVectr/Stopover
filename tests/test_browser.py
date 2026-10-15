import asyncio
import os
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

from stopover.__main__ import call_remote


def test_dashboard_details_search_filters_mobile_and_safe_text(live_server, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    args["record"]["title"] = "Carry the release checklist into Claude Code"
    args["record"]["context"]["background"] = '<img src=x onerror="window.handoffInjected=true">'
    args["record"]["context"]["facts"] = [{"text": "The adapter was checked locally.", "basis": "observed", "evidence_ids": []}]
    saved = asyncio.run(call_remote(live_server["url"] + "/mcp", "stopover_save", args))
    handoff_id = saved["data"]["id"]
    screenshots = Path(os.environ.get("STOPOVER_SCREENSHOT_DIR", "/tmp/handoff-screenshots"))
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"])
        expect(page.get_by_role("heading", name="Inbox", exact=True)).to_be_visible()
        expect(page.locator("#signin-dialog")).not_to_be_visible()
        expect(page.locator("#signout-button")).to_be_hidden()
        row = page.locator(".handoff-row").filter(has_text=args["record"]["title"])
        expect(row).to_be_visible()
        page.get_by_role("button", name="Connect your agents").click()
        expect(page.get_by_role("dialog", name="Connect your agents")).to_be_visible()  # dialogs have accessible names
        expect(page.locator("#mcp-url")).to_have_text(live_server["url"] + "/mcp")
        expect(page.locator("#codex-add")).to_have_text("codex mcp add stopover --url " + live_server["url"] + "/mcp")
        expect(page.locator("#setup-dialog")).not_to_contain_text("docker exec")
        page.get_by_role("button", name="Copy MCP URL").click()
        assert page.evaluate("navigator.clipboard.readText()") == live_server["url"] + "/mcp"
        page.get_by_role("button", name="Close connection instructions").click()
        row.click()
        expect(page.locator("#detail h2")).to_have_text(args["record"]["title"])
        expect(page.locator("#detail h2")).to_be_focused()  # keyboard and screen-reader users land on what they opened
        expect(page.get_by_role("heading", name="Next steps", exact=True)).to_be_visible()
        expect(page.locator("#detail")).to_contain_text(args["record"]["context"]["background"])
        assert not page.evaluate("Boolean(window.handoffInjected)")
        expect(page.locator("#detail .timeline li")).to_have_count(1)
        page.screenshot(path=str(screenshots / "dashboard-desktop.png"), full_page=True)
        # An empty search result is not an empty inbox: it says so, and offers to clear the filters.
        page.get_by_label("Search handoffs").fill("missing-record-search")
        expect(page.get_by_text("No matching handoffs.")).to_be_visible()
        expect(page.get_by_text("No handoffs here yet.")).to_have_count(0)
        page.get_by_role("button", name="Clear filters").click()
        expect(row).to_be_visible()
        expect(page.get_by_label("Search handoffs")).to_have_value("")
        page.locator('[data-status="done"]').click()
        expect(page.get_by_text("Nothing done yet.")).to_be_visible()
        page.locator('[data-status="inbox"]').click()
        expect(row).to_be_visible()
        # Less-used actions sit behind the More menu.
        expect(page.get_by_role("button", name="Copy ID", exact=True)).to_be_hidden()
        page.get_by_label("More actions").click()
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
    asyncio.run(call_remote(url + '/mcp', 'stopover_memory_update', args))
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
            pool.submit(lambda: asyncio.run(call_remote(url + '/mcp', 'stopover_memory_update', corrected))).result()
        page.locator('#memory-refresh').click()
        expect(page.locator('#memory-detail')).to_contain_text('A corrected personal preference.')
        expect(page.locator('#memory-detail')).to_contain_text('claude-code')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        screenshots = Path(os.environ.get('STOPOVER_SCREENSHOT_DIR', '/tmp/handoff-screenshots'))
        screenshots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshots / 'memory-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.screenshot(path=str(screenshots / 'memory-desktop.png'), full_page=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(call_remote(url + '/mcp', 'stopover_memory_forget', forget('personal.topic00', 26)))).result()
        page.locator('#memory-refresh').click()
        expect(page.locator('#memory-detail')).to_contain_text('FORGOTTEN MEMORY')
        expect(page.locator('#memory-detail')).not_to_contain_text('A corrected personal preference.')
        expect(page.locator('#memory-total')).to_have_text('24')
        page.locator('[data-status="inbox"]').click()
        expect(page.get_by_role('heading', name='Inbox', exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_role('heading', name='Personal memories', exact=True)).to_be_visible()
        assert not errors, errors
        browser.close()


def test_dashboard_signs_in_when_the_server_requires_a_token(tmp_path, record):
    import socket
    import threading
    import time
    import uvicorn
    from stopover.context import RequestContext
    from stopover.server import create_app

    async def auth(request):
        return RequestContext(actor="alice") if request.headers.get("authorization") == "Bearer good-token" else None

    app = create_app(tmp_path, auth=auth)
    app.state.service.execute("stopover_save", {"record": record})
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
            assert page.evaluate("localStorage.getItem('stopover.accessToken')") is None
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
    from stopover.context import RequestContext
    from stopover.server import create_app

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
                             "logout_url": "/fake-logout", "access_token_url": "/settings/tokens",
                             "links": [{"label": "Access tokens", "url": "/settings/tokens"},
                                       {"label": "Elsewhere", "url": "https://evil.example/"}, {"label": "Protocol", "url": "//evil.example"}],
                             "usage": {"title": "Free plan", "url": "/settings/tokens#plan", "items": [
                                 {"label": "Changes today", "used": 200, "limit": 200}, {"label": "Saved handoffs", "used": 12, "limit": 50},
                                 {"label": "Memories", "used": 3, "limit": None}, {"label": "Broken", "used": "x"}]}})

    app = create_app(tmp_path, auth=auth, login_url="/fake-login", extra_routes=[
        Route("/fake-login", login), Route("/fake-login/complete", complete),
        Route("/fake-logout", logout, methods=["POST"]), Route("/api/session", session)])
    saved = app.state.service.execute("stopover_save", {"record": record})["data"]
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
            # Host links: same-origin only.
            expect(page.locator("#host-links a")).to_have_count(1)
            expect(page.get_by_role("link", name="Access tokens")).to_have_attribute("href", "/settings/tokens")
            # Plan usage from the host: what's left of each limit; malformed items are skipped.
            usage = page.locator("#host-usage")
            expect(usage.locator(".usage-item")).to_have_count(3)
            expect(usage).to_contain_text("Free plan")
            expect(usage.locator(".usage-head.out")).to_have_text("Changes today0 of 200 left")
            expect(usage).to_contain_text("38 of 50 left")
            expect(usage).to_contain_text("No limit")
            expect(usage.get_by_role("link", name="Details")).to_have_attribute("href", "/settings/tokens#plan")
            # Phones: account links and Sign out sit behind the account button, not in the top bar.
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator("#host-links")).to_be_hidden()
            page.get_by_role("button", name="Account").click()
            sheet = page.locator("#account-dialog")
            expect(sheet).to_contain_text("Alice's workspace")
            expect(sheet.get_by_role("link", name="Access tokens")).to_have_attribute("href", "/settings/tokens")
            expect(sheet.get_by_role("button", name="Sign out")).to_be_visible()
            expect(sheet.locator("#account-usage")).to_contain_text("38 of 50 left")
            page.get_by_role("button", name="Close account menu").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.set_viewport_size({"width": 1280, "height": 900})
            expect(page.get_by_role("button", name="Account")).to_be_hidden()
            # The setup dialog tells the user to create a token rather than "no token needed".
            page.get_by_role("button", name="Connect your agents").first.click()
            expect(page.locator("#claude-add")).to_contain_text('--header "Authorization: Bearer YOUR_TOKEN"')
            expect(page.get_by_role("link", name="Create an access token")).to_have_attribute("href", "/settings/tokens")
            expect(page.locator("#setup-intro")).not_to_contain_text("No token")
            page.get_by_role("button", name="Close connection instructions").click()
            # Hosts with MCP OAuth: agents sign in through the browser, so the commands carry no token.
            def with_sign_in(route):
                body = route.fetch().json()
                route.fulfill(json={**body, "mcp_sign_in": True})
            page.route("**/api/session", with_sign_in)
            page.reload()
            expect(page.locator("#workspace-name")).to_have_text("Alice's workspace")
            page.get_by_role("button", name="Connect your agents").first.click()
            expect(page.locator("#claude-add")).not_to_contain_text("Authorization")
            expect(page.locator("#codex-add")).to_contain_text("codex mcp login stopover")
            expect(page.locator("#setup-intro")).to_contain_text("opens your browser to sign in")
            expect(page.get_by_role("link", name="Or create an access token")).to_have_attribute("href", "/settings/tokens")
            page.get_by_role("button", name="Close connection instructions").click()
            page.unroute("**/api/session")
            page.get_by_role("button", name="Sign out").click()
            expect(page.get_by_role("heading", name="Host login")).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_selecting_another_handoff_never_offers_the_previous_one(live_server, record):
    """On a slow connection, the old details (and their copy buttons) must not stay up while the new one loads."""
    ids = []
    for title in ("First handoff", "Second handoff"):
        args = {"operation_id": str(uuid.uuid4()), "record": {**record, "title": title}}
        ids.append(asyncio.run(call_remote(live_server["url"] + "/mcp", "stopover_save", args))["data"]["id"])
    first, second = ids
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        page.goto(f"{live_server['url']}/handoffs/{first}")
        expect(page.locator("#detail h2")).to_have_text("First handoff")
        held = []
        page.route(f"**/api/handoffs/{second}", lambda route: held.append(route))  # hold the second response
        page.locator(".handoff-row").filter(has_text="Second handoff").click()
        expect(page.locator("#detail")).to_contain_text("Loading handoff")
        expect(page.get_by_role("button", name="Copy resume prompt")).to_have_count(0)
        expect(page.locator("#detail")).not_to_contain_text("First handoff")
        assert held, "the detail request should be in flight"
        held[0].continue_()
        expect(page.locator("#detail h2")).to_have_text("Second handoff")
        page.get_by_role("button", name="Copy resume prompt").click()
        assert page.evaluate("navigator.clipboard.readText()") == f"Resume Handoff {second}"
        browser.close()


def test_refresh_keeps_keyboard_focus_on_the_list(live_server, record):
    args = {"operation_id": str(uuid.uuid4()), "record": {**record, "title": "Focused handoff"}}
    focused_id = asyncio.run(call_remote(live_server["url"] + "/mcp", "stopover_save", args))["data"]["id"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.clock.install()
        page.goto(live_server["url"])
        row = page.locator(f'.handoff-row[data-key="{focused_id}"]')
        row.focus()
        # Another agent saves a handoff; the next refresh rebuilds the list.
        more = {"operation_id": str(uuid.uuid4()), "record": {**record, "title": "Arrived during refresh"}}
        httpx.post(live_server["url"] + "/mcp", headers={"accept": "application/json, text/event-stream"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "stopover_save", "arguments": more}})
        page.clock.run_for(16000)
        expect(page.locator(".handoff-row").filter(has_text="Arrived during refresh")).to_be_visible()
        assert page.evaluate("document.activeElement.dataset.key") == focused_id
        browser.close()


def test_inbox_groups_by_project_answers_questions_and_deletes(live_server, record):
    import copy
    url = live_server["url"]
    def save(title, project, questions=()):
        data = copy.deepcopy(record)
        data.update(title=title, project_key=project)
        data["context"]["open_questions"] = list(questions)
        data["context"]["summary"] = (f"{title} is about half done. The parser reads every report format we support, its unit "
                                      "tests pass, and we chose streaming over buffering so large reports don't run out of memory.\n\n"
                                      "It stopped before the export screen. Next, wire the parser into that screen, then confirm "
                                      "which columns belong in the file before writing the end-to-end test.")
        return asyncio.run(call_remote(url + "/mcp", "stopover_save", {"operation_id": str(uuid.uuid4()), "record": data}))["data"]["id"]
    save("Fix login", "api")
    asking = save("Add CSV export", "web", ["Which columns go in the export?"])
    save("Loose note", None)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        # The inbox: what needs you first, then what's ready, each grouped by project when there are several.
        expect(page.locator(".list-section h2")).to_have_text(["Needs you", "Ready to continue"])
        expect(page.locator(".project-label")).to_have_text(["api", "No project"])
        expect(page.locator("#count-needs_you")).to_have_text("1")
        expect(page.locator(".next-up")).to_contain_text("Add CSV export")  # nothing selected: what to do next
        row = page.locator(".handoff-row").first
        expect(row).to_contain_text("Add CSV export")
        expect(row).to_contain_text("1 question for you")
        row.click()
        # The summary sits at the top, as paragraphs.
        expect(page.locator(".detail-header .glance-summary")).to_have_count(2)
        page.get_by_label("Your answer to: Which columns go in the export?").fill("Date, amount and payee")
        page.get_by_role("button", name="Save answer").click()
        expect(page.locator("#toast")).to_have_text("Answer saved")
        expect(page.locator(".question-card .answer")).to_have_text("Date, amount and payee")
        expect(page.locator("#count-needs_you")).to_be_hidden()
        expect(page.locator(".list-section h2")).to_have_text(["Ready to continue"])
        # Answered, so continuing is the main action again.
        expect(page.locator(".detail-header .resume-box")).to_contain_text("Continue in another agent")
        # Playwright runs its own event loop here, so the MCP call goes on another thread.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            resumed = pool.submit(asyncio.run, call_remote(url + "/mcp", "stopover_resume", {"id": asking, "holder_label": "codex"})).result()["data"]
        assert resumed["answers"][0]["answer"] == "Date, amount and payee"
        # Deleting asks first, and warns that an agent has it.
        page.reload()
        page.get_by_label("More actions").click()
        page.get_by_role("button", name="Delete", exact=True).click()
        expect(page.locator("#delete-text")).to_contain_text("codex has picked this up")
        page.get_by_role("button", name="Cancel").click()
        expect(page.locator("#detail h2")).to_have_text("Add CSV export")
        page.get_by_label("More actions").click()
        page.get_by_role("button", name="Delete", exact=True).click()
        page.get_by_role("button", name="Delete handoff").click()
        expect(page.locator("#toast")).to_have_text("Handoff deleted")
        expect(page.locator(".handoff-row")).to_have_count(2)
        expect(page.locator(".project-label")).to_have_count(2)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors, errors
        browser.close()
