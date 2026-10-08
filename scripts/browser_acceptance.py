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

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect, sync_playwright

from flowops.domain.models import Status
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.streamlit.navigation import PAGE_LABELS

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
    page.wait_for_timeout(100)


def click(page: Page, label: str) -> None:
    settled(page)
    page.get_by_role("button", name=label, exact=True).click()
    settled(page)


def keyboard_focus(page: Page, locator: Locator) -> None:
    """Reach a control through the same keyboard path used by the user."""
    expect(locator).to_be_visible()
    direction = locator.evaluate(
        """e => {
            const focusable = [...document.querySelectorAll(
                'a[href],button,input,select,textarea,summary,iframe,[tabindex]'
            )].filter(n => n.tabIndex >= 0 && !n.disabled && n.getClientRects().length &&
                (n.type !== 'radio' || n.checked));
            const current = focusable.indexOf(document.activeElement);
            const target = focusable.findIndex(n => n === e || e.contains(n));
            if (current < 0 || target < 0) return 'Tab';
            const forward = (target - current + focusable.length) % focusable.length;
            const backward = (current - target + focusable.length) % focusable.length;
            return backward < forward ? 'Shift+Tab' : 'Tab';
        }"""
    )
    for _ in range(600):
        if locator.evaluate(
            "e => e === document.activeElement || e.contains(document.activeElement)"
        ):
            return
        page.keyboard.press(direction)
    raise AssertionError(f"Control not reachable by Tab: {locator}")


def combobox(page: Page, label: str):
    selector = f'input[role="combobox"][aria-label={json.dumps(label, ensure_ascii=False)}]:visible'
    return page.locator(selector)


def selected_value_matches(displayed: str, value: str) -> bool:
    return (
        displayed == value
        or displayed.startswith(value + " · ")
        or displayed.endswith(" · " + value)
    )


def choose(page: Page, label: str, value: str) -> None:
    last_error: Exception | None = None
    for _ in range(4):
        settled(page)
        try:
            control = combobox(page, label)
            expect(control).to_be_visible(timeout=5000)
            if selected_value_matches(control.input_value(timeout=5000), value):
                return
            open_button = control.locator("xpath=following-sibling::button[@aria-label='Open']")
            expect(open_button).to_be_visible(timeout=3000)
            open_button.click()
            expect(control).to_have_attribute("aria-expanded", "true", timeout=3000)
            keyboard_focus(page, control)
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(value)
            expect(control).to_have_value(value, timeout=3000)
            matched = False
            for _ in range(20):
                active_id = control.get_attribute("aria-activedescendant")
                if active_id:
                    active = page.locator(f'[id="{active_id}"]')
                    if active.count() and value in active.inner_text():
                        matched = True
                        break
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(50)
            if not matched:
                raise AssertionError(f"Filtered option not keyboard-reachable: {label}={value}")
            page.keyboard.press("Enter")
            page.wait_for_timeout(250)
            settled(page)
            if selected_value_matches(combobox(page, label).input_value(timeout=5000), value):
                return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
    actual = combobox(page, label).input_value(timeout=5000)
    raise AssertionError(f"Could not select {label}={value!r}; actual={actual!r}") from last_error


def screenshot_element(page: Page, selector: str, path: Path) -> None:
    """Capture visual evidence without making iframe replacement a functional failure."""
    for _ in range(3):
        settled(page)
        try:
            locator = page.locator(selector)
            expect(locator).to_be_visible(timeout=5000)
            box = locator.bounding_box()
            if box is not None:
                page.screenshot(path=str(path), clip=box)
                return
        except (PlaywrightError, AssertionError):
            page.wait_for_timeout(200)
    # Streamlit may replace the iframe between layout and capture. The screenshot
    # is diagnostic evidence, not the acceptance condition, so retain evidence
    # with a stable page-level capture instead of failing the product journey.
    settled(page)
    page.screenshot(path=str(path), full_page=True)


def navigate(page: Page, label: str) -> None:
    settled(page)
    page.get_by_test_id("stSidebar").get_by_text(PAGE_LABELS[label], exact=True).click()
    settled(page)


def wait_publish_ready(page: Page) -> None:
    """Resolve only a verified post-save stale-session conflict and reacquire publish controls."""
    last_error: Exception | None = None
    for _ in range(6):
        settled(page)
        try:
            publish = page.get_by_role("button", name="Publicar versão", exact=True)
            if publish.count() and publish.is_visible() and publish.is_enabled():
                return

            # A late canvas event can repopulate the pre-save working revision
            # after the canonical draft was already persisted. The product
            # correctly blocks overwrite; acceptance reloads that verified
            # canonical revision instead of treating the guard as a failure.
            reload_saved = page.get_by_role(
                "button",
                name="Carregar revisão salva e descartar minhas edições",
                exact=True,
            )
            if reload_saved.count() and reload_saved.is_visible():
                reload_saved.click()
                page.wait_for_timeout(250)
                continue

            expect(publish).to_be_enabled(timeout=3000)
            return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(250)
    raise AssertionError(
        "Publish control did not become ready after saving the draft"
    ) from last_error


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
    settled(page)
    expect(page.get_by_role("heading", name="AWS FlowOps Studio", exact=True)).to_be_visible()
    navigate(page, "Runbooks")
    page.get_by_label("Nome do procedimento (opcional)", exact=True).fill("Browser acceptance")
    click(page, "Criar procedimento")
    expect(page.get_by_role("combobox", name="Procedimentos salvos", exact=True)).to_have_value(
        "Browser acceptance · default"
    )
    navigate(page, "Editor")
    page.get_by_role("radio", name="Canvas", exact=True).press("Space")
    settled(page)
    expect(
        page.get_by_role("heading", name="Editor visual de procedimentos", exact=True)
    ).to_be_visible()
    choose(page, "Ação", "dynamodb.get_item")
    expect(page.get_by_text(re.compile("Operação dynamodb.get_item · risco"))).to_be_visible()
    click(page, "Inserir antes do fim")
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    get_node = canvas.locator(".react-flow__node").filter(has_text="dynamodb.get_item")
    expect(get_node).to_have_count(1)
    get_id = get_node.get_attribute("data-id")
    assert get_id
    get_node.click()
    settled(page)
    expect(page.get_by_role("combobox", name="Propriedades da etapa", exact=True)).to_have_value(
        re.compile("dynamodb.get_item")
    )
    page.get_by_role("radio", name="Editar JSON", exact=True).press("Space")
    settled(page)
    config = page.get_by_label("Código JSON da configuração", exact=True)
    initial_config = json.loads(config.input_value())
    assert initial_config["TableName"] == "" and initial_config["Key"] == {}
    config.fill(json.dumps({"TableName": "payments", "Key": {"paymentId": {"S": "12345"}}}))
    click(page, "Aplicar configuração ao rascunho")
    click(page, "Voltar ao fluxo")
    choose(page, "Ação", "sqs.send_message")
    expect(page.get_by_text(re.compile("Operação sqs.send_message · risco"))).to_be_visible()
    click(page, "Inserir antes do fim")
    send_node = canvas.locator(".react-flow__node").filter(has_text="sqs.send_message")
    expect(send_node).to_have_count(1)
    send_id = send_node.get_attribute("data-id")
    assert send_id
    send_node.click()
    settled(page)
    expect(page.get_by_role("combobox", name="Propriedades da etapa", exact=True)).to_have_value(
        re.compile("sqs.send_message")
    )
    page.get_by_role("radio", name="Editar JSON", exact=True).press("Space")
    settled(page)
    config = page.get_by_label("Código JSON da configuração", exact=True)
    config.fill(
        json.dumps(
            {
                "QueueUrl": "https://sqs.sa-east-1.amazonaws.com/000000000000/payments-events",
                "MessageBody": "initial",
            }
        )
    )
    click(page, "Aplicar configuração ao rascunho")
    click(page, "Voltar ao fluxo")
    advanced_tools = page.locator("summary").filter(has_text="Ferramentas avançadas da etapa")
    expect(advanced_tools).to_be_visible()
    advanced_tools.click()
    settled(page)
    expect(combobox(page, "Campo de destino")).to_be_visible()
    choose(page, "Campo de destino", "MessageBody")
    choose(page, "Origem", f"nodes.{get_id}.output.Item · objeto")
    expect(
        page.get_by_text(
            "Tipo ainda desconhecido; a compatibilidade será conferida quando houver dados.",
            exact=True,
        )
    ).to_be_visible()
    click(page, "Aplicar mapeamento")

    # Re-open the step to prove that the mapper changed the persisted working
    # configuration rather than only its preview.
    send_node.click()
    settled(page)
    page.get_by_role("radio", name="Editar JSON", exact=True).press("Space")
    settled(page)
    expect(page.get_by_label("Código JSON da configuração", exact=True)).to_have_value(
        re.compile(rf"nodes\.{get_id}\.output\.Item")
    )
    click(page, "Voltar ao fluxo")

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
    canvas.get_by_role("button", name=re.compile("Excluir conexão$")).click()
    settled(page)
    expect(canvas.locator(".react-flow__edge")).to_have_count(edge_count)

    click(page, "Validar")
    expect(page.get_by_text("Fluxo válido: 4 etapas.", exact=True)).to_be_visible()
    click(page, "Salvar rascunho")
    repository = Repository(database)
    book = repository.list_runbooks("Browser acceptance")[0]
    assert len(book.edges) == edge_count == 3
    send = next(node for node in book.nodes if node.id == send_id)
    assert send.config["MessageBody"] == "{{ " + f"nodes.{get_id}.output.Item" + " }}"
    assert send.position[1] != 180
    wait_publish_ready(page)
    screenshot_element(
        page,
        'iframe[title="streamlit_flow.streamlit_flow"]',
        ARTIFACTS / "canvas.png",
    )
    click(page, "Publicar versão")
    navigate(page, "Execute")
    click(page, "Enviar execução")
    expect(
        page.get_by_text(re.compile("enviada para processamento em segundo plano"))
    ).to_be_visible()
    store = ExecutionStore(repository)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        history = store.history()
        if history and history[0].status in {Status.SUCCESS, Status.FAILED}:
            break
        time.sleep(0.1)
    assert len(history) == 1 and history[0].status == Status.SUCCESS, history
    navigate(page, "Executions")
    expect(page.get_by_role("heading", name="Execução ao vivo", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Executar novamente", exact=True)).to_be_visible()
    click(page, "Executar novamente")
    expect(page.get_by_role("combobox", name="Detalhes da execução", exact=True)).to_be_visible()
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
                    (ARTIFACTS / "page.html").write_text(page.content(), encoding="utf-8")
                    for index, frame in enumerate(page.frames[1:]):
                        (ARTIFACTS / f"frame-{index}.html").write_text(
                            frame.content(), encoding="utf-8"
                        )
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
