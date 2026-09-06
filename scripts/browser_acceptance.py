"""Real Chromium acceptance against Streamlit and its React Flow iframe, in demo mode."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Page, expect, sync_playwright

from flowops.domain.models import Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "browser-artifacts"


def settled(page: Page) -> None:
    """Wait for Streamlit's server acknowledgement, not just the optimistic widget value.

    The official e2e helper uses these app-state attributes and a short debounce grace:
    https://github.com/streamlit/streamlit/blob/1.56.0/e2e_playwright/conftest.py
    """
    page.wait_for_timeout(250)
    app = page.get_by_test_id("stApp")
    expect(app).to_have_attribute("data-test-connection-state", "CONNECTED", timeout=25000)
    expect(app).to_have_attribute("data-test-script-state", "notRunning", timeout=25000)
    expect(page.get_by_test_id("stSkeleton")).to_have_count(0, timeout=25000)


def click(page: Page, label: str) -> None:
    settled(page)
    page.get_by_role("button", name=label, exact=True).click()
    settled(page)


def choose(page: Page, label: str, value: str) -> None:
    settled(page)
    control = page.get_by_role("combobox", name=label, exact=True)
    control.click()
    control.fill(value)
    page.get_by_role("option", name=value, exact=True).click()
    settled(page)


def navigate(page: Page, label: str) -> None:
    settled(page)
    page.get_by_test_id("stSidebar").get_by_text(label, exact=True).click()
    settled(page)


def wait_server(process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Streamlit exited before becoming healthy.")
        try:
            with urlopen("http://127.0.0.1:8501/_stcore/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError):
            time.sleep(0.2)
    raise TimeoutError("Streamlit health check timed out.")


def journey(page: Page, database: Path) -> None:
    page.goto("http://127.0.0.1:8501")
    expect(page.get_by_role("heading", name="AWS FlowOps Studio", exact=True)).to_be_visible()
    navigate(page, "Runbooks")
    page.get_by_label("Name override", exact=True).fill("Browser acceptance")
    click(page, "Create runbook")
    expect(page.get_by_role("combobox", name="Saved runbooks", exact=True)).to_have_value(
        "Browser acceptance · default"
    )
    navigate(page, "Editor")
    expect(page.get_by_role("heading", name="Visual Runbook Editor", exact=True)).to_be_visible()
    choose(page, "Action", "dynamodb.get_item")
    expect(page.get_by_text(re.compile("AWS dynamodb GetItem · risk"))).to_be_visible()
    click(page, "Insert before End")
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    get_node = canvas.locator(".react-flow__node").filter(has_text="dynamodb.get_item")
    expect(get_node).to_have_count(1)
    get_id = get_node.get_attribute("data-id")
    assert get_id
    get_node.click()
    settled(page)
    expect(page.get_by_role("combobox", name="Node properties", exact=True)).to_have_value(
        re.compile("dynamodb.get_item")
    )
    expect(page.get_by_label("Configuration JSON", exact=True)).to_have_value("{}")
    page.get_by_label("Configuration JSON", exact=True).fill(
        json.dumps({"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}})
    )
    click(page, "Apply node properties")
    choose(page, "Action", "sqs.send_message")
    expect(page.get_by_text(re.compile("AWS sqs SendMessage · risk"))).to_be_visible()
    click(page, "Insert before End")
    send_node = canvas.locator(".react-flow__node").filter(has_text="sqs.send_message")
    expect(send_node).to_have_count(1)
    send_id = send_node.get_attribute("data-id")
    assert send_id
    send_node.click()
    settled(page)
    expect(page.get_by_role("combobox", name="Node properties", exact=True)).to_have_value(
        re.compile("sqs.send_message")
    )
    page.get_by_label("Configuration JSON", exact=True).fill(
        json.dumps(
            {
                "QueueUrl": "https://sqs.sa-east-1.amazonaws.com/000000000000/payments-events",
                "MessageBody": "initial",
            }
        )
    )
    click(page, "Apply node properties")
    choose(page, "Target field", "MessageBody")
    choose(page, "Source", f"nodes.{get_id}.output.Item · object")
    expect(page.get_by_text("Type compatible: object → any", exact=True)).to_be_visible()
    click(page, "Apply mapping")
    expect(page.get_by_label("Configuration JSON", exact=True)).to_have_value(
        re.compile(rf"nodes\.{get_id}\.output\.Item")
    )

    # Exercise the installed canvas rather than synthesizing component payloads.
    node_before = send_node.get_attribute("style")
    send_node.hover()
    box = send_node.bounding_box()
    assert box
    page.mouse.move(box["x"] + 70, box["y"] + 25)
    page.mouse.down()
    page.mouse.move(box["x"] + 70, box["y"] + 135, steps=12)
    page.mouse.up()
    settled(page)
    expect(send_node).not_to_have_attribute("style", node_before or "")
    expect(canvas.locator(".react-flow__minimap")).to_be_visible()
    start_handle = canvas.locator('.react-flow__node[data-id="start"] .source')
    target_handle = canvas.locator(f'.react-flow__node[data-id="{send_id}"] .target')
    edge_count = canvas.locator(".react-flow__edge").count()
    start_handle.drag_to(target_handle)
    settled(page)
    expect(canvas.locator(".react-flow__edge")).to_have_count(edge_count + 1)
    added_edge = canvas.locator(".react-flow__edge").last
    point = added_edge.locator(".react-flow__edge-path").evaluate(
        """path => {
            const p = path.getPointAtLength(path.getTotalLength() * 0.25);
            const screen = new DOMPoint(p.x, p.y).matrixTransform(path.getScreenCTM());
            return {x: screen.x, y: screen.y};
        }"""
    )
    frame_box = page.locator('iframe[title="streamlit_flow.streamlit_flow"]').bounding_box()
    assert frame_box
    page.mouse.click(frame_box["x"] + point["x"], frame_box["y"] + point["y"], button="right")
    canvas.get_by_role("button", name=re.compile("Delete Edge$")).click()
    settled(page)
    expect(canvas.locator(".react-flow__edge")).to_have_count(edge_count)

    click(page, "Validate")
    expect(page.get_by_text("Valid workflow: 4 nodes.", exact=True)).to_be_visible()
    click(page, "Save draft")
    expect(page.get_by_role("button", name="Publish version", exact=True)).to_be_enabled()
    repository = Repository(database)
    book = repository.list_runbooks("Browser acceptance")[0]
    assert len(book.edges) == edge_count == 3
    send = next(node for node in book.nodes if node.id == send_id)
    assert send.config["MessageBody"] == "{{ " + f"nodes.{get_id}.output.Item" + " }}"
    assert send.position[1] != 180
    page.locator('iframe[title="streamlit_flow.streamlit_flow"]').screenshot(
        path=str(ARTIFACTS / "canvas.png")
    )
    click(page, "Publish version")
    navigate(page, "Execute")
    click(page, "Submit execution")
    expect(page.get_by_text(re.compile("submitted asynchronously"))).to_be_visible()
    store = ExecutionStore(repository)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        history = store.history()
        if history and history[0].status in {Status.SUCCESS, Status.FAILED}:
            break
        time.sleep(0.1)
    assert len(history) == 1 and history[0].status == Status.SUCCESS, history
    navigate(page, "Executions")
    expect(page.get_by_role("heading", name="Visual execution", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Run again", exact=True)).to_be_visible()
    click(page, "Run again")
    expect(page.get_by_role("combobox", name="Execution detail", exact=True)).to_be_visible()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        replay_history = store.history()
        if len(replay_history) == 2 and all(
            entry.status in {Status.SUCCESS, Status.FAILED} for entry in replay_history
        ):
            break
        time.sleep(0.1)
    assert len(replay_history) == 2 and all(
        entry.status == Status.SUCCESS for entry in replay_history
    ), replay_history
    page.screenshot(path=str(ARTIFACTS / "history.png"), full_page=True)
    (ARTIFACTS / "result.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "created": book.id,
                "version": history[0].runbook_version,
                "execution": history[0].id,
                "nodes": len(book.nodes),
                "checks": [
                    "startup",
                    "create",
                    "configure",
                    "canvas selection",
                    "drag",
                    "connect",
                    "disconnect",
                    "mapper",
                    "validate",
                    "save",
                    "publish",
                    "execute",
                    "history",
                    "rerun",
                ],
            },
            indent=2,
        )
    )


def main() -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as directory, (ARTIFACTS / "server.log").open("wb") as log:
        database = Path(directory) / "browser.db"
        env = os.environ | {
            "FLOWOPS_DATABASE": str(database),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        }
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "standalone_app.py"),
                "--server.headless=true",
                "--server.port=8501",
                "--global.e2eTest=true",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_server(server)
            with sync_playwright() as browser_tool:
                browser = browser_tool.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.set_default_timeout(20000)
                browser_errors: list[str] = []
                page.on("pageerror", lambda error: browser_errors.append(str(error)))
                try:
                    journey(page, database)
                    assert not browser_errors, browser_errors
                    print("Browser acceptance PASS: " + (ARTIFACTS / "result.json").read_text())
                finally:
                    page.screenshot(path=str(ARTIFACTS / "last-page.png"), full_page=True)
                    print(
                        "FLOWOPS_BROWSER_SCREENSHOT="
                        + base64.b64encode((ARTIFACTS / "last-page.png").read_bytes()).decode()
                    )
                    (ARTIFACTS / "frames.json").write_text(
                        json.dumps([frame.url for frame in page.frames])
                    )
                    (ARTIFACTS / "page.html").write_text(page.content())
                    for index, frame in enumerate(page.frames[1:]):
                        (ARTIFACTS / f"frame-{index}.html").write_text(frame.content())
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
