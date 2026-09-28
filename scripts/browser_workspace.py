"""Isolated Chromium acceptance for canvas editing, query, approval and per-node exports."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Page, expect, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from flowops.domain.models import Edge, Node
from flowops.persistence.executions import ExecutionStore
from flowops.persistence.repository import Repository
from flowops.streamlit.graph_layout import organize_workflow
from flowops.streamlit.localization import field_label
from flowops.streamlit.navigation import PAGE_LABELS
from flowops.templates import dynamodb_query_lambda
from scripts.browser_layout import check_layout_fixture, check_layout_pages
from scripts.browser_localization import check_adapter, check_pages

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (
    ROOT
    / "browser-artifacts"
    / (
        "react-editor"
        if "--react-only" in sys.argv
        else "authoring-completion"
        if "--authoring-completion" in sys.argv
        else "visual-authoring"
        if "--visual-authoring" in sys.argv
        else "workspace"
    )
)


def settled(page: Page) -> None:
    page.wait_for_timeout(250)
    expect(page.get_by_test_id("stApp")).to_have_attribute(
        "data-test-script-state", "notRunning", timeout=30000
    )
    expect(page.get_by_test_id("stException")).to_have_count(0)
    expect(page.get_by_test_id("stSkeleton")).to_have_count(0, timeout=30000)


def navigate(page: Page, name: str) -> None:
    page.get_by_test_id("stSidebar").get_by_text(PAGE_LABELS[name], exact=True).click()
    settled(page)
    expect(page.get_by_role("radio", name=PAGE_LABELS[name], exact=True)).to_be_checked()


def choose(page: Page, label: str, value: str) -> None:
    settled(page)
    control = page.get_by_role("combobox", name=label, exact=True)
    if control.input_value() == value:
        return
    control.click()
    control.fill(value)
    control.press("ArrowDown")
    page.get_by_role("option", name=value, exact=True).click()
    settled(page)


def check_organization(page: Page, database: Path) -> None:
    """Exercise real iframe synchronization, geometry, undo and unsaved draft isolation."""
    repo = Repository(database)
    book = repo.list_runbooks()[0]
    before, revision = repo.get_draft(book.id)
    events = repo.events()
    organized, _ = organize_workflow(before, revision)
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')

    def expect_positions(expected) -> None:
        for node in expected.nodes:
            x, y = node.position
            expect(canvas.locator(f'.react-flow__node[data-id="{node.id}"]')).to_have_css(
                "transform", f"matrix(1, 0, 0, 1, {x:g}, {y:g})"
            )

    expect_positions(before)
    iframe = page.locator('iframe[title="streamlit_flow.streamlit_flow"]')
    iframe.screenshot(path=str(ARTIFACTS / "organization-before.png"))
    page.get_by_role("button", name="Organizar fluxo", exact=True).press("Enter")
    settled(page)
    expect_positions(organized)
    rectangles = canvas.locator(".react-flow__node").evaluate_all(
        "nodes => nodes.map(node => ({id: node.dataset.id, ...node.getBoundingClientRect().toJSON()}))"
    )
    viewport = canvas.locator(".react-flow").bounding_box()
    assert viewport is not None
    for index, first in enumerate(rectangles):
        assert 0 <= first["left"] < first["right"] <= viewport["width"]
        assert 0 <= first["top"] < first["bottom"] <= viewport["height"]
        for second in rectangles[index + 1 :]:
            assert (
                first["right"] <= second["left"]
                or second["right"] <= first["left"]
                or first["bottom"] <= second["top"]
                or second["bottom"] <= first["top"]
            ), (first, second)
    iframe.screenshot(path=str(ARTIFACTS / "organization-after.png"))
    page.get_by_role("button", name="Organizar fluxo", exact=True).click()
    settled(page)
    expect(page.get_by_text("O fluxo já está organizado.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Desfazer organização", exact=True).press("Enter")
    settled(page)
    expect_positions(before)
    expect(page.get_by_role("button", name="Desfazer organização", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Organizar fluxo", exact=True).click()
    settled(page)
    expect_positions(organized)
    # Manual movement expires undo, so a later click cannot overwrite the user's adjustment.
    start = canvas.locator('.react-flow__node[data-id="start"]')
    start.scroll_into_view_if_needed()
    bounds = start.bounding_box()
    assert bounds is not None
    x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y + 60, steps=10)
    page.mouse.up()
    settled(page)
    expect(page.get_by_role("button", name="Desfazer organização", exact=True)).to_be_disabled()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_role("button", name="Organizar fluxo", exact=True).click()
    settled(page)
    expect_positions(organized)
    close_node_dialog(page)
    assert repo.get_draft(book.id) == (before, revision)
    assert repo.events() == events
    assert ExecutionStore(repo).history() == []
    (ARTIFACTS / "organization.json").write_text(
        json.dumps({"status": "PASS", "positions_only": True, "rectangles": rectangles}, indent=2),
        encoding="utf-8",
    )


def close_node_dialog(page: Page) -> None:
    dialog = page.get_by_role("dialog")
    if not dialog.count():
        return
    back = dialog.get_by_role("button", name="Voltar ao fluxo", exact=True)
    if back.count():
        try:
            back.press("Enter", timeout=2000)
        except PlaywrightTimeoutError:
            # A Streamlit rerun can detach the button while the dialog is
            # already closing. Only recover if a dialog is still present.
            if dialog.count():
                page.keyboard.press("Escape")
        settled(page)
    elif dialog.count():
        page.keyboard.press("Escape")
        settled(page)
    expect(dialog).to_have_count(0)


def journey(page: Page, url: str, database: Path) -> None:
    check_adapter(page)
    page.goto(url)
    settled(page)
    expect(page.get_by_role("region", name="Tour do FlowOps")).to_have_count(0)
    navigate(page, "Guide")
    expect(
        page.get_by_role("heading", name="Guia passo a passo do FlowOps", exact=True)
    ).to_be_visible()
    navigate(page, "Editor")
    page.get_by_role("radio", name="Canvas", exact=True).press("Space")
    settled(page)
    check_organization(page, database)
    close_node_dialog(page)
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    query = canvas.locator('.react-flow__node[data-id="query"]')
    expect(query).to_be_visible()
    query.click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_role("heading", name="Editar etapa", exact=True)).to_be_visible()
    dialog.get_by_text("Buscar recursos e montar consulta DynamoDB", exact=True).click()
    dialog.get_by_role("button", name="Buscar recursos para esta etapa", exact=True).click()
    settled(page)
    dialog.get_by_role("button", name="Carregar estrutura da tabela", exact=True).click()
    settled(page)
    choose(page, "Origem da chave paymentId", "Valor fixo")
    dialog.get_by_label("Chave paymentId (S)", exact=True).fill("12345")
    dialog.get_by_role("button", name="Aplicar requisição DynamoDB gerada", exact=True).click()
    settled(page)
    expect(dialog.get_by_label(field_label("KeyConditionExpression"), exact=True)).to_have_value(
        re.compile(":pk")
    )
    close_node_dialog(page)
    # Closing resets selection so clicking the same box opens it again.
    query.click()
    expect(dialog).to_have_count(1)
    dialog.get_by_text("Propriedades avançadas da etapa", exact=True).click()
    dialog.get_by_label("Nome da etapa", exact=True).fill("Consultar pagamento no DynamoDB")
    dialog.get_by_role("button", name="Aplicar propriedades da etapa", exact=True).press("Enter")
    settled(page)
    page.screenshot(path=str(ARTIFACTS / "node-editor.png"))
    close_node_dialog(page)
    # Configure map/approval/payload through the guide, without editing JSON or expressions.
    page.get_by_role("radio", name="Assistente", exact=True).press("Space")
    settled(page)
    choose(page, "Propriedades da etapa", "Preparar evento · core.map")
    page.get_by_label(f"Nome do novo campo em {field_label('template')}", exact=True).fill(
        "source_system"
    )
    page.get_by_label(f"Nome do novo campo em {field_label('template')}", exact=True).press("Tab")
    settled(page)
    page.get_by_role(
        "button", name=f"Adicionar campo em {field_label('template')}", exact=True
    ).click()
    settled(page)
    page.get_by_label("source_system", exact=True).fill("FlowOps visual")
    page.get_by_role("button", name="Aplicar configuração ao rascunho", exact=True).click()
    settled(page)
    page.get_by_role("button", name="Próxima etapa", exact=True).click()
    settled(page)
    page.get_by_label(field_label("message"), exact=True).fill(
        "Confira os pagamentos e a função de destino."
    )
    page.get_by_role("button", name="Aplicar configuração ao rascunho", exact=True).click()
    settled(page)
    page.get_by_role("button", name="Próxima etapa", exact=True).click()
    settled(page)
    page.get_by_label(f"Nome do novo campo em {field_label('Payload')}", exact=True).fill(
        "metadata"
    )
    page.get_by_label(f"Nome do novo campo em {field_label('Payload')}", exact=True).press("Tab")
    settled(page)
    page.get_by_role(
        "button", name=f"Adicionar campo em {field_label('Payload')}", exact=True
    ).click()
    settled(page)
    choose(page, "Tipo de metadata", "Objeto (campos)")
    page.get_by_label("Nome do novo campo em metadata", exact=True).fill("origin")
    page.get_by_label("Nome do novo campo em metadata", exact=True).press("Tab")
    settled(page)
    page.get_by_role("button", name="Adicionar campo em metadata", exact=True).click()
    settled(page)
    page.get_by_label(field_label("origin"), exact=True).fill("web")
    page.get_by_role("button", name="Aplicar configuração ao rascunho", exact=True).click()
    settled(page)
    page.screenshot(path=str(ARTIFACTS / "visual-payload.png"))
    page.get_by_role("radio", name="Canvas", exact=True).press("Space")
    settled(page)
    page.get_by_role("button", name="Validar", exact=True).click()
    settled(page)
    page.get_by_role("button", name="Salvar rascunho", exact=True).click()
    settled(page)
    expect(page.get_by_role("button", name="Desfazer organização", exact=True)).to_be_disabled()
    saved, revision = Repository(database).get_draft(Repository(database).list_runbooks()[0].id)
    assert organize_workflow(saved, revision)[1] is None
    page.get_by_role("button", name="Publicar versão", exact=True).click()
    settled(page)
    navigate(page, "Execute")
    page.get_by_text("Simulação do FlowOps", exact=True).click()
    expect(page.get_by_label("Simulação do FlowOps", exact=True)).not_to_be_checked()
    page.get_by_label("Motivo / referência da mudança", exact=True).fill("Browser demo approval")
    page.get_by_role("button", name="Enviar execução", exact=True).click()
    expect(page.get_by_text("Execução pausada.", exact=False)).to_be_visible(timeout=30000)
    page.screenshot(path=str(ARTIFACTS / "waiting-approval.png"))
    navigate(page, "Approvals")
    page.get_by_label("Motivo da decisão", exact=True).fill("Payload e destino revisados no demo")
    page.get_by_role("button", name="Aprovar", exact=True).click()
    navigate(page, "Executions")
    live = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    expect(live.locator(".react-flow__edge.animated")).to_have_count(1, timeout=30000)
    page.screenshot(path=str(ARTIFACTS / "running.png"))
    expect(page.get_by_text("Sucesso · atualização", exact=False)).to_be_visible(timeout=60000)
    live.locator('.react-flow__node[data-id="invoke"]').click()
    settled(page)
    expect(page.get_by_role("combobox", name="Etapa do resultado", exact=True)).to_have_value(
        "invoke"
    )
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Baixar resultado em JSON", exact=True).click()
    file = downloaded.value
    assert file.suggested_filename == "invoke-result.json"
    file.save_as(ARTIFACTS / file.suggested_filename)
    body = json.loads((ARTIFACTS / file.suggested_filename).read_text())
    assert body["Payload"]["payload"]["payments"][0]["payment_id"] == "12345"
    assert body["Payload"]["payload"]["payments"][0]["source_system"] == "FlowOps visual"
    assert body["Payload"]["payload"]["metadata"] == {"origin": "web"}
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Baixar resultado em CSV", exact=True).click()
    assert downloaded.value.suggested_filename == "invoke-result.csv"
    page.screenshot(path=str(ARTIFACTS / "execution-results.png"))
    # A new version deliberately references a missing demo table; the successful snapshot survives.
    # Editor-view widgets are intentionally page-local. Returning from another page
    # restores the product default (advanced canvas), so choose the legacy canvas
    # explicitly before interacting with its iframe.
    navigate(page, "Editor")
    page.get_by_role("radio", name="Canvas", exact=True).press("Space")
    settled(page)
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    query = canvas.locator('.react-flow__node[data-id="query"]')
    expect(query).to_be_visible()
    query.click()
    settled(page)
    choose(page, f"Tipo de {field_label('TableName')}", "Texto")
    dialog.get_by_label(field_label("TableName"), exact=True).fill("missing-demo-table")
    dialog.get_by_role("button", name="Aplicar configuração ao rascunho", exact=True).press("Enter")
    settled(page)
    dialog.get_by_role("button", name="Voltar ao fluxo", exact=True).press("Enter")
    expect(dialog).to_have_count(0)
    expect(query).to_be_visible()
    settled(page)
    page.get_by_role("button", name="Salvar rascunho", exact=True).click()
    settled(page)
    publish = page.locator("button:enabled").filter(has_text="Publicar versão")
    expect(publish).to_have_count(1)
    publish.click()
    settled(page)
    navigate(page, "Execute")
    choose(page, "Versão", "2")
    expect(page.get_by_label("Simulação do FlowOps", exact=True)).to_be_checked()
    page.get_by_role("button", name="Enviar execução", exact=True).click()
    expect(page.get_by_text("Falha · atualização", exact=False)).to_be_visible(timeout=30000)
    failed = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    expect(failed.locator('.react-flow__node[data-id="query"]')).to_have_css(
        "border-color", "rgb(220, 38, 38)"
    )
    # FAILED can be visible before the worker finishes marking downstream nodes.
    # Wait for the complete terminal graph before interacting with its iframe.
    expect(failed.locator('.react-flow__node[data-id="end"]')).to_contain_text("Não executada")
    settled(page)
    failed.locator('.react-flow__node[data-id="query"]').click()
    settled(page)
    expect(page.get_by_role("combobox", name="Etapa do resultado", exact=True)).to_have_value(
        "query"
    )
    # Streamlit streams sibling replacements: the selector can already say query while
    # the previous node's download is still mounted. Await the server-rendered node key.
    checkpoint_button = page.locator('[class*="-query-checkpoint"]').get_by_role(
        "button", name="Baixar diagnóstico do nó (JSON)", exact=True
    )
    expect(checkpoint_button).to_be_visible(timeout=30000)
    with page.expect_download() as downloaded:
        checkpoint_button.click()
    assert downloaded.value.suggested_filename == "query-checkpoint.json", (
        downloaded.value.suggested_filename
    )
    downloaded.value.save_as(ARTIFACTS / "query-checkpoint.json")
    checkpoint = json.loads((ARTIFACTS / "query-checkpoint.json").read_text())
    assert checkpoint["status"] == "FAILED" and "ResourceNotFoundException" in checkpoint["error"]
    page.screenshot(path=str(ARTIFACTS / "failure.png"))
    navigate(page, "Catalog")
    choose(page, "Serviço AWS", "ec2")
    page.get_by_label("Buscar operação", exact=True).fill("describe_instances")
    page.get_by_label("Buscar operação", exact=True).press("Enter")
    expect(
        page.get_by_text("Disponível no editor: ec2.describe_instances", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Usar no editor", exact=True).click()
    expect(
        page.get_by_role("heading", name="Editor visual de procedimentos", exact=True)
    ).to_be_visible()
    page.get_by_text("Adicionar etapa pelo formulário", exact=True).click()
    expect(page.get_by_role("combobox", name="Ação", exact=True)).to_have_value(
        "ec2.describe_instances"
    )
    check_pages(page, ARTIFACTS / "pt-br")
    check_layout_pages(page, ARTIFACTS / "layout")
    navigate(page, "Editor")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(500)
    collapse = page.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
    if collapse.is_visible():
        collapse.press("Enter")
    page.wait_for_timeout(500)
    expect(
        page.get_by_role("heading", name="Editor visual de procedimentos", exact=True)
    ).to_be_visible()
    page.screenshot(path=str(ARTIFACTS / "mobile.png"))
    repo = Repository(database)
    history = ExecutionStore(repo).history()
    assert len(history) == 2 and {entry.status for entry in history} == {"SUCCESS", "FAILED"}
    assert history[1].snapshot.nodes[1].config["TableName"] == "{{ params.table_name }}"
    assert history[1].parameters["table_name"] == "payments"
    assert any(event["event"] == "EXECUTION_APPROVED" for event in repo.events())


def main() -> None:
    locale_only = "--locale-only" in sys.argv
    layout_only = "--layout-only" in sys.argv
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "result.json").write_text(json.dumps({"status": "RUNNING"}))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    with (
        tempfile.TemporaryDirectory(dir=ARTIFACTS) as directory,
        (ARTIFACTS / "server.log").open("wb") as log,
    ):
        database = Path(directory) / "browser.db"
        repo = Repository(database)
        book = dynamodb_query_lambda("demo-author", "default")
        # A deliberate local wait makes transient live animation observable, not timing luck.
        # Keep it longer than the browser's approval/navigation steps so the running
        # edge is asserted while the fixture is genuinely in progress.
        book.nodes.insert(-1, Node(id="pause", action="core.wait", config={"seconds": 30}))
        book.edges = [edge for edge in book.edges if edge.target != "end"] + [
            Edge(source="invoke", target="pause"),
            Edge(source="pause", target="end"),
        ]
        revision = repo.save_draft(book, "demo-author")
        if layout_only:
            repo.publish(book.id, "demo-author", revision)
        env = os.environ | {
            "FLOWOPS_DATABASE": str(database),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "PYTHONUTF8": "1",
        }
        env.pop("FLOWOPS_DATABASE_URL", None)
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "standalone_app.py"),
                "--server.headless=true",
                f"--server.port={port}",
                "--server.address=127.0.0.1",
                "--global.e2eTest=true",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
        try:
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urlopen(url + "/_stcore/health", timeout=1):
                        break
                except (URLError, TimeoutError):
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Streamlit did not start") from None
                    time.sleep(0.2)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(20000)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    check_layout_fixture(page)
                    if layout_only:
                        page.goto(url)
                        settled(page)
                        check_layout_pages(page, ARTIFACTS / "layout")
                    elif locale_only:
                        check_adapter(page)
                        page.goto(url)
                        settled(page)
                        check_pages(page, ARTIFACTS / "pt-br")
                    elif "--react-only" in sys.argv:
                        from scripts.browser_authoring import react_proof

                        page.goto(url)
                        settled(page)
                        navigate(page, "Editor")
                        react_proof(page, ARTIFACTS, book.name)
                    elif "--authoring-completion" in sys.argv:
                        from scripts.browser_authoring import journey as authoring_journey

                        authoring_journey(page, url, database, ARTIFACTS)
                    else:
                        journey(page, url, database)
                    assert not errors, errors
                    (ARTIFACTS / "result.json").write_text(
                        json.dumps(
                            {
                                "status": "PASS",
                                "journey": "React builder only"
                                if "--react-only" in sys.argv
                                else "User-created keyboard journey and React builder"
                                if "--authoring-completion" in sys.argv
                                else "Responsive layout across 10 pages and node dialog"
                                if layout_only
                                else "Portuguese controls and 10 pages"
                                if locale_only
                                else "organize -> undo -> query -> map -> manual approval -> Lambda -> node exports -> Portuguese controls and 10 pages",
                                "AWS_real_calls": 0,
                            },
                            indent=2,
                        )
                    )
                    print("Workspace browser acceptance PASS", flush=True)
                except Exception as exc:
                    (ARTIFACTS / "result.json").write_text(
                        json.dumps(
                            {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                            ensure_ascii=True,
                        )
                    )
                    raise
                finally:
                    page.screenshot(path=str(ARTIFACTS / "last-page.png"))
                    (ARTIFACTS / "last-page.html").write_text(page.content(), encoding="utf-8")
                    browser.close()
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == "__main__":
    main()
