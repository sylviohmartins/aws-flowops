"""Real Chromium journey against the local bootstrap, PostgreSQL and emulated AWS."""

import json
import subprocess
import sys
import time

from playwright.sync_api import expect, sync_playwright

from flowops.domain.models import Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.providers.aws.lab import LAB_DATABASE_URL
from flowops.providers.aws.local import local_client
from scripts.browser_acceptance import (
    ARTIFACTS,
    ROOT,
    choose,
    click,
    navigate,
    settled,
    wait_server,
)


def main() -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    store = ExecutionStore(Repository(LAB_DATABASE_URL))
    with (ARTIFACTS / "local-server.log").open("wb") as log:
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "local_app.py"),
                "--server.address=127.0.0.1",
                "--server.headless=true",
                "--server.port=8501",
                "--global.e2eTest=true",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_server(server)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                page.set_default_timeout(25000)
                try:
                    page.goto("http://127.0.0.1:8501")
                    expect(
                        page.get_by_text("DEV · 123456789012 · sa-east-1 · LOCAL", exact=True)
                    ).to_be_visible()
                    navigate(page, "Resources")
                    click(page, "Discover resources")
                    expect(
                        page.get_by_text("4 recurso(s) encontrado(s).", exact=False)
                    ).to_be_visible()
                    navigate(page, "Execute")
                    choose(page, "Execution runbook", "XPTO - Recuperar pagamento parado · default")
                    page.get_by_label("payment_id *", exact=True).fill("PAY-1004")
                    simulation = page.get_by_label("FlowOps simulation", exact=True)
                    if simulation.is_checked():
                        simulation.click(force=True)
                        settled(page)
                    expect(simulation).not_to_be_checked()
                    page.get_by_label("Reason / change reference", exact=True).fill(
                        "Browser local lab"
                    )
                    click(page, "Submit execution")
                    execution = store.history()[0]
                    deadline = time.monotonic() + 45
                    while (
                        store.get(execution.id).status in {Status.PENDING, Status.RUNNING}
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.1)
                    navigate(page, "Approvals")
                    page.get_by_label("Decision reason", exact=True).fill("Reviewed in browser")
                    click(page, "Approve")
                    while (
                        store.get(execution.id).status
                        in {Status.PENDING, Status.RUNNING, Status.WAITING_APPROVAL}
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.2)
                    result = store.get(execution.id)
                    assert result.status == Status.SUCCESS, result.error
                    assert (
                        result.node_outputs["prepare_event"]["Payload"]["event"]["payment_id"]
                        == "PAY-1004"
                    )
                    client = local_client("dynamodb")
                    try:
                        assert (
                            client.get_item(
                                TableName="flowops-payments", Key={"paymentId": {"S": "PAY-1004"}}
                            )["Item"]["status"]["S"]
                            == "PROCESSED"
                        )
                    finally:
                        client.close()
                    navigate(page, "Executions")
                    choose(page, "Execution detail", execution.id)
                    click(page, "Run again")
                    settled(page)
                    replay = store.history()[0]
                    while (
                        store.get(replay.id).status in {Status.PENDING, Status.RUNNING}
                        and time.monotonic() < deadline
                    ):
                        time.sleep(0.1)
                    assert replay.id != execution.id
                    assert "already_done" in store.get(replay.id).node_outputs
                    (ARTIFACTS / "local-result.json").write_text(
                        json.dumps(
                            {
                                "execution": execution.id,
                                "replay": replay.id,
                                "status": "PASS",
                                "checks": [
                                    "local bootstrap",
                                    "discovery",
                                    "saved flow",
                                    "parameters",
                                    "approval",
                                    "Docker Lambda",
                                    "DynamoDB effect",
                                    "replay",
                                ],
                            },
                            indent=2,
                        )
                    )
                    print("Local browser PASS: " + (ARTIFACTS / "local-result.json").read_text())
                finally:
                    page.screenshot(path=str(ARTIFACTS / "local-last-page.png"), full_page=True)
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
