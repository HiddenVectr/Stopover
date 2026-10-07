import asyncio
import os
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

from handoff.__main__ import call_remote


def test_dashboard_details_search_filters_mobile_and_safe_text(live_server, record):
    args = {"operation_id": str(uuid.uuid4()), "record": record}
    args["record"]["title"] = "Carry the release checklist into Claude Code"
    args["record"]["context"]["background"] = '<img src=x onerror="window.handoffInjected=true">'
    args["record"]["context"]["facts"] = [{"text": "The adapter was checked locally.", "basis": "observed", "evidence_ids": []}]
    saved = asyncio.run(call_remote(live_server["url"] + "/mcp", "handoff_push", args))
    handoff_id = saved["data"]["id"]
    screenshots = Path(os.environ.get("HANDOFF_SCREENSHOT_DIR", "/tmp/handoff-screenshots"))
    screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, permissions=["clipboard-read", "clipboard-write"])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server["url"])
        expect(page.get_by_role("heading", name="All handoffs", exact=True)).to_be_visible()
        assert page.locator("input[type=password]").count() == 0
        row = page.locator(".handoff-row").filter(has_text=args["record"]["title"])
        expect(row).to_be_visible()
        page.get_by_role("button", name="Connect your agents").click()
        expect(page.locator("#mcp-url")).to_have_text(live_server["url"] + "/mcp")
        expect(page.locator("#codex-add")).to_have_text("codex mcp add handoff --url " + live_server["url"] + "/mcp")
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
