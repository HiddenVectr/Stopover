"""Regenerate the documentation screenshots in docs/images/.

Starts a throwaway Stopover server on a temporary data directory, fills it with clearly synthetic demo data through
real MCP calls (the same path agents use), and captures the dashboard with Playwright:

    .venv/bin/python scripts/screenshots.py

Needs the development dependencies and Chromium (see README, Development).
"""
from __future__ import annotations

import asyncio
import copy
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
sys.path.insert(0, str(ROOT / "src"))
from stopover.sample import sample_record  # noqa: E402

HANDOFFS = [
    dict(title="Fix refresh-token rotation in the auth service", project_key="acme-api", client="claude-code",
         target=None, objective="Rotate refresh tokens on every use and detect reuse of an old token.",
         summary="Refresh tokens now rotate on every use, and reusing an old token revokes the whole token family. Mobile "
                 "tokens expire after 30 days because people sign in on phones less often.\n\nIt stopped before the expiry "
                 "tests. Next, add tests for expiry and reuse detection, then document the behaviour in docs/auth.md.",
         state="Rotation and reuse detection are implemented. Expiry tests are still missing.",
         decision=("Expire mobile refresh tokens after 30 days", "Mobile users complained about weekly sign-outs."),
         steps=[("expiry-tests", "Add tests for 30-day expiry and reuse detection.", "pytest passes with the new tests."),
                ("docs", "Document the rotation behaviour in docs/auth.md.", "The doc explains rotation and reuse.")],
         criteria=["Reusing a rotated token revokes the whole token family.", "Tests cover expiry and reuse."]),
    dict(title="Migrate the billing worker to the new queue", project_key="acme-api", client="codex", target="claude-code",
         objective="Move the billing worker from the legacy cron to the job queue without double-charging.",
         summary="The queue consumer is built behind a flag, and the cron stays as a fallback for one release.\n\nNext, "
                 "make every charge idempotent so a retried job can never charge twice, then turn off the cron.",
         state="The queue consumer exists behind a flag. The cron job still runs in production.",
         decision=("Keep the cron as a fallback for one release", "Rollback must not need a deploy."),
         steps=[("idempotency", "Add an idempotency key to every charge.", "A replayed job never charges twice.")],
         criteria=["No customer is charged twice when a job is retried."]),
    dict(title="Speed up the dashboard's first load", project_key="acme-web", client="cursor", target=None,
         objective="Get the dashboard's first contentful paint under one second on a mid-range phone.",
         summary="Charts are 41% of the first bundle; next, lazy-load them to get first paint under a second.",
         state="Bundle analysis done: the chart library is 41% of the initial bundle.",
         decision=("Lazy-load charts below the fold", "Most users never scroll to them."),
         steps=[("split", "Split the chart library into a lazy chunk.", "The initial bundle shrinks by at least 30%.")],
         criteria=["First contentful paint under 1 s in the Lighthouse mobile profile."]),
    dict(title="Add CSV export to reports", project_key="acme-web", client="codex", target=None,
         objective="Let people download any report as a CSV file.",
         summary="The CSV writer streams rows so large reports don't run out of memory, and the export button is on the "
                 "reports page.\n\nTwo decisions block the last step: which columns to include, and how to format dates.",
         state="Writer and button done; the column mapping waits on two decisions.",
         decision=("Stream rows instead of building the file in memory", "Some reports have a million rows."),
         steps=[("columns", "Map the chosen columns.", "The file contains exactly the agreed columns.")],
         criteria=["Downloading any report produces a valid CSV."],
         questions=["Which columns go in the export: everything on screen, or a fixed set?",
                    "Should dates be in UTC or the viewer's timezone?"]),
    dict(title="Write the release notes for 2.4", project_key="acme-web", client="hermes", target="codex",
         objective="Summarise the 2.4 changes for customers.", state="Draft covers features; fixes are missing.",
         decision=("Group fixes by product area", "Customers scan by area, not by ticket."),
         steps=[("fixes", "Add the fixed bugs from the milestone.", "Every closed bug in the milestone is listed.")],
         criteria=["Every user-visible change in 2.4 is in the notes."]),
]
MEMORIES = [
    ("profile.summary", "A Python developer who switches between Claude Code and Codex. Prefers short answers with the "
     "conclusion first, typed and small functions, and tests that pass before work is called done.", "fact"),
    ("work.oncall", "On call for acme-api this week; keep suggestions low-risk.", "project_context", 5),
    ("communication.response_length", "Prefers short answers with the conclusion first.", "preference"),
    ("code.style.python", "Uses type hints and keeps functions small; follows the repository's existing style.", "preference"),
    ("workflow.commits", "Commit only when asked; never push without confirmation.", "preference"),
    ("project.acme-api.stack", "acme-api is Python 3.12 with FastAPI and Postgres 17.", "project_context"),
    ("tools.editor", "Switches between Claude Code and Codex depending on usage limits.", "habit"),
    ("testing.policy", "Expects tests to run and pass before work is reported done.", "preference"),
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def record_for(spec) -> dict:
    record = copy.deepcopy(sample_record())
    record.update(title=spec["title"], project_key=spec["project_key"], target_client=spec["target"])
    record["source"].update(client=spec["client"], authoring_method="agent_summary", transfer_method="direct_mcp")
    record["coverage"] = {"basis": "Synthetic example data for documentation screenshots.", "omitted": []}
    context = record["context"]
    context.update(summary=spec.get("summary", ""), objective=spec["objective"], current_state=spec["state"],
                   background="Synthetic example for Stopover's documentation; not a real project.", constraints=[],
                   decisions=[{"decision": spec["decision"][0], "reason": spec["decision"][1], "evidence_ids": []}],
                   next_steps=[{"id": i, "action": a, "done_when": d} for i, a, d in spec["steps"]],
                   acceptance_criteria=spec["criteria"], open_questions=spec.get("questions", []))
    if record["target_client"] is None:
        del record["target_client"]
    return record


async def populate(url: str):
    async with streamablehttp_client(url) as (read, write, _), ClientSession(read, write) as session:
        await session.initialize()

        async def call(tool, args):
            result = await session.call_tool(tool, args)
            data = json.loads(result.content[0].text)
            assert data.get("ok", True), data
            return data.get("data", data)

        saved = []
        for spec in HANDOFFS:
            saved.append(await call("stopover_save", {"operation_id": str(uuid.uuid4()), "record": record_for(spec)}))
            time.sleep(1.1)  # distinct timestamps, so the list order is stable
        # One handoff with an agent, one asking questions, one finished, the rest ready to continue.
        await call("stopover_resume", {"operation_id": str(uuid.uuid4()), "id": saved[1]["id"], "holder_label": "claude-code"})
        done = await call("stopover_resume", {"operation_id": str(uuid.uuid4()), "id": saved[4]["id"], "holder_label": "codex"})
        await call("stopover_complete", {"operation_id": str(uuid.uuid4()), "id": saved[4]["id"], "claim_token": done["claim_token"],
                                      "completion": {"outcome": "succeeded", "summary": "Release notes drafted with all fixes.",
                                                     "acceptance_results": [{"index": 0, "result": "pass",
                                                                             "evidence": "Checked against the 2.4 milestone."}]}})
        await call("stopover_memory_update", {"operation_id": str(uuid.uuid4()), "client": "claude-code", "memories": [
            {"key": key, "content": content, "expected_revision": 0, "category": category, "basis": "stated",
             "evidence": "Synthetic example for the documentation.",
             # A fourth value: the memory expires that many days from now.
             **({"expires_at": time.strftime("%Y-%m-%d", time.gmtime(time.time() + rest[0] * 86400))} if rest else {})}
            for key, content, category, *rest in MEMORIES]})
        return saved


# Screenshots show the documented default URL, whatever port the throwaway server uses.
SHOWN = "http://127.0.0.1:8765"


def capture(base: str, first_id: str, asking_id: str):
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def new_page(**options):
            # Dark theme for the docs; no fade-ins mid-capture.
            page = browser.new_page(color_scheme="dark", reduced_motion="reduce", **options)
            page.route(SHOWN + "/**", lambda route: route.fulfill(response=route.fetch(url=route.request.url.replace(SHOWN, base))))
            return page

        def open_list(page, path="/"):
            page.goto(SHOWN + path)
            page.wait_for_selector("#handoff-list .handoff-row", timeout=15000)

        page = new_page(viewport={"width": 1440, "height": 900})
        open_list(page)
        page.screenshot(path=OUT / "dashboard.png")
        open_list(page, f"/handoffs/{first_id}")
        page.wait_for_function("!document.querySelector('#detail .empty-detail')", timeout=15000)
        page.screenshot(path=OUT / "handoff-detail.png")
        open_list(page, f"/handoffs/{asking_id}")
        page.wait_for_selector("#detail .question-card", timeout=15000)
        page.screenshot(path=OUT / "questions.png")
        page.goto(SHOWN + "/memories/communication.response_length")
        page.wait_for_selector("#memory-list button", timeout=15000)
        page.wait_for_function("!document.querySelector('#memory-detail .empty-detail')", timeout=15000)
        page.screenshot(path=OUT / "memories.png")
        open_list(page)
        page.click("#setup-button")
        page.wait_for_selector("#setup-dialog[open]", timeout=5000)
        page.screenshot(path=OUT / "connect-dialog.png")
        mobile = new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        open_list(mobile)
        mobile.screenshot(path=OUT / "dashboard-mobile.png")
        browser.close()


def main():
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory() as data:
        server = subprocess.Popen([sys.executable, "-m", "stopover", "--data-dir", data, "serve", "--host", "127.0.0.1",
                                   "--port", str(port)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                try:
                    if json.load(urllib.request.urlopen(base + "/healthz", timeout=1)).get("ready"):
                        break
                except OSError:
                    time.sleep(0.1)
            saved = asyncio.run(populate(base + "/mcp"))
            capture(base, saved[0]["id"], saved[3]["id"])
        finally:
            server.terminate()
            server.wait(timeout=10)
    print("Wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
