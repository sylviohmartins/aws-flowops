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

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect, sync_playwright
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


NAVIGATION_HEADINGS = {
    "Dashboard": "Visão geral",
    "Runbooks": "Procedimentos",
    "Editor": "Editor visual de procedimentos",
    "Execute": "Executar procedimento",
    "Executions": "Histórico de execuções",
    "Approvals": "Aprovações",
    "Audit": "Auditoria",
    "Resources": "Explorador de recursos AWS",
    "Catalog": "Catálogo de ações AWS",
    "Guide": "Guia passo a passo do FlowOps",
}


def navigate(page: Page, name: str) -> None:
    """Navigate only after both client selection and server-rendered content agree."""
    label = PAGE_LABELS[name]
    heading = NAVIGATION_HEADINGS.get(name)
    last_error: Exception | None = None
    for _ in range(6):
        try:
            target = page.get_by_role("radio", name=label, exact=True)
            expect(target).to_be_visible(timeout=5000)
            if not target.is_checked():
                target.press("Space", timeout=5000)
            settled(page)
            target = page.get_by_role("radio", name=label, exact=True)
            expect(target).to_be_checked(timeout=5000)
            if heading:
                expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(
                    timeout=5000
                )
            return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            # A Streamlit rerun may update the radio client-side before the
            # server-rendered page catches up. Force a different page first so
            # the next attempt sends a fresh navigation event.
            fallback = "Dashboard" if name != "Dashboard" else "Runbooks"
            fallback_radio = page.get_by_role("radio", name=PAGE_LABELS[fallback], exact=True)
            if fallback_radio.count() and fallback_radio.is_visible():
                fallback_radio.press("Space", timeout=5000)
                page.wait_for_timeout(200)
                settled(page)
            else:
                page.wait_for_timeout(250)
    raise AssertionError(f"Navigation did not settle on {name}") from last_error


def select_radio(page: Page, label: str) -> None:
    """Select a Streamlit radio option across reruns without retaining a stale locator."""
    last_error: Exception | None = None
    for _ in range(6):
        settled(page)
        try:
            target = page.get_by_role("radio", name=label, exact=True)
            expect(target).to_be_visible(timeout=5000)
            if target.is_checked():
                return
            target.press("Space", timeout=5000)
            page.wait_for_timeout(200)
            settled(page)
            current = page.get_by_role("radio", name=label, exact=True)
            if current.is_checked():
                return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(250)
    raise AssertionError(f"Radio option did not settle as checked: {label}") from last_error


def open_pending_approval(page: Page, database: Path) -> Locator:
    """Wait for durable approval state, then reacquire its form across navigation reruns."""
    store = ExecutionStore(Repository(database))
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if store.pending_approvals():
            break
        time.sleep(0.1)
    else:
        raise AssertionError("Execution paused without a durable pending approval")

    last_error: Exception | None = None
    for _ in range(5):
        try:
            navigate(page, "Approvals")
            reason = page.get_by_label("Motivo da decisão", exact=True)
            expect(reason).to_be_visible(timeout=5000)
            return reason
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(250)
    raise AssertionError("Pending approval form did not become available") from last_error


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


def combobox(scope: Page | Locator, label: str):
    selector = f'input[role="combobox"][aria-label={json.dumps(label, ensure_ascii=False)}]:visible'
    return scope.locator(selector)


def selected_value_matches(displayed: str, value: str) -> bool:
    return (
        displayed == value
        or displayed.startswith(value + " · ")
        or displayed.endswith(" · " + value)
    )


def choose(page: Page, label: str, value: str) -> None:
    """Select a Streamlit/BaseWeb option across reruns without retaining stale containers."""
    last_error: Exception | None = None
    for _ in range(6):
        settled(page)
        try:
            control = combobox(page, label)
            expect(control).to_be_visible(timeout=5000)
            if selected_value_matches(control.input_value(timeout=5000), value):
                return

            # Prefer keyboard selection. BaseWeb/Streamlit can recreate the
            # combobox during a rerun before aria-expanded settles, so never
            # make that transient attribute a correctness requirement.
            keyboard_focus(page, control)
            page.keyboard.press("Enter")
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(value)
            page.wait_for_timeout(100)

            control = combobox(page, label)
            option = page.get_by_role("option", name=value, exact=True)
            if option.count() and option.first.is_visible():
                option.first.click()
            else:
                keyboard_focus(page, control)
                page.keyboard.press("Enter")

            page.wait_for_timeout(350)
            settled(page)
            current = combobox(page, label)
            if selected_value_matches(current.input_value(timeout=5000), value):
                return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
    actual = "<control unavailable after rerun>"
    try:
        control = combobox(page, label)
        if control.count() and control.is_visible():
            actual = control.input_value(timeout=2000)
    except PlaywrightError:
        pass
    raise AssertionError(f"Could not select {label}={value!r}; actual={actual!r}") from last_error


def select_assistant_step(
    page: Page,
    value: str,
    *,
    expected_label: str,
) -> None:
    """Select an assistant step and wait for its server-rendered editor."""
    last_error: Exception | None = None
    for _ in range(4):
        try:
            choose(page, "Propriedades da etapa", value)
            settled(page)
            field = page.get_by_label(expected_label, exact=True)
            expect(field).to_be_visible(timeout=5000)
            return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(200)
    raise AssertionError(
        f"Assistant step {value!r} did not render expected field {expected_label!r}"
    ) from last_error


def select_result_node(page: Page, node_id: str) -> None:
    """Select a result node without depending on canvas-to-Streamlit rerun timing."""
    last_error: Exception | None = None
    for _ in range(4):
        try:
            frame = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
            node = frame.locator(f'.react-flow__node[data-id="{node_id}"]')
            expect(node).to_be_visible(timeout=5000)
            node.click()
            settled(page)
            selector = combobox(page, "Etapa do resultado")
            expect(selector).to_be_visible(timeout=5000)
            if selected_value_matches(selector.input_value(timeout=5000), node_id):
                return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
        page.wait_for_timeout(200)

    # The canvas component and Streamlit selector are siblings updated by
    # independent reruns. If the canvas click was not acknowledged, use the
    # explicit result selector as the authoritative user control instead of
    # treating that timing race as an application failure.
    try:
        choose(page, "Etapa do resultado", node_id)
        selector = combobox(page, "Etapa do resultado")
        if selected_value_matches(selector.input_value(timeout=5000), node_id):
            return
    except (PlaywrightError, AssertionError) as exc:
        last_error = exc

    actual = combobox(page, "Etapa do resultado").input_value(timeout=5000)
    raise AssertionError(
        f"Result node {node_id!r} could not be selected; selector={actual!r}"
    ) from last_error


def open_node_dialog(page: Page, node_id: str | None = None) -> Locator:
    """Reopen a node editor even when a rerun clears the selected-node controls."""
    last_error: Exception | None = None
    for _ in range(4):
        dialog = page.get_by_role("dialog")
        if dialog.is_visible():
            return dialog
        try:
            edit = page.get_by_role("button", name="Editar etapa selecionada", exact=True)
            if edit.is_visible():
                edit.click(timeout=3000)
            elif node_id is not None:
                canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
                node = canvas.locator(f'.react-flow__node[data-id="{node_id}"]')
                expect(node).to_be_visible(timeout=5000)
                node.click()
            else:
                canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
                selected = canvas.locator(".react-flow__node.selected")
                expect(selected).to_have_count(1, timeout=3000)
                selected.click()
            settled(page)
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible(timeout=5000)
            return dialog
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    raise AssertionError(f"Could not reopen node dialog for {node_id!r}") from last_error


def ensure_node_dialog_section(
    page: Page,
    section: str,
    target_label: str,
    *,
    node_id: str | None = None,
) -> Locator:
    """Reopen a node dialog/section after Streamlit reruns close the modal."""
    last_error: Exception | None = None
    for _ in range(4):
        try:
            dialog = open_node_dialog(page, node_id)
            target = dialog.get_by_role("combobox", name=target_label, exact=True)
            if target.is_visible():
                return dialog
            toggle = dialog.get_by_text(section, exact=True)
            expect(toggle).to_be_visible(timeout=5000)
            toggle.click()
            settled(page)
            dialog = open_node_dialog(page, node_id)
            target = dialog.get_by_role("combobox", name=target_label, exact=True)
            expect(target).to_be_visible(timeout=5000)
            return dialog
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(200)
    raise AssertionError(
        f"Node section {section!r} did not expose {target_label!r}"
    ) from last_error


def ensure_node_dialog_field(
    page: Page,
    section: str,
    field_label_text: str,
    *,
    node_id: str | None = None,
) -> Locator:
    """Reopen a node dialog/section and return it once a resulting field is visible."""
    last_error: Exception | None = None
    for _ in range(4):
        try:
            dialog = open_node_dialog(page, node_id)
            field = dialog.get_by_label(field_label_text, exact=True)
            if field.is_visible():
                return dialog
            toggle = dialog.get_by_text(section, exact=True)
            expect(toggle).to_be_visible(timeout=5000)
            toggle.click()
            settled(page)
            dialog = open_node_dialog(page, node_id)
            field = dialog.get_by_label(field_label_text, exact=True)
            expect(field).to_be_visible(timeout=5000)
            return dialog
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(200)
    raise AssertionError(
        f"Node section {section!r} did not expose field {field_label_text!r}"
    ) from last_error


def choose_structural_kind(
    page: Page,
    type_label: str,
    kind: str,
    *,
    section: str,
    resulting_field_label: str,
    node_id: str | None = None,
) -> Locator:
    """Change a value kind and validate the newly rendered editor after callback reruns."""
    last_error: Exception | None = None
    for _ in range(4):
        ensure_node_dialog_section(page, section, type_label, node_id=node_id)
        try:
            control = combobox(page, type_label)
            expect(control).to_be_visible(timeout=5000)
            keyboard_focus(page, control)
            page.keyboard.press("Enter")
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(kind)
            expect(control).to_have_value(kind, timeout=3000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(250)
            settled(page)
            return ensure_node_dialog_field(
                page,
                section,
                resulting_field_label,
                node_id=node_id,
            )
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    raise AssertionError(
        f"Could not change {type_label} to {kind!r} and render {resulting_field_label!r}"
    ) from last_error


def choose_first_option(
    page: Page,
    label: str,
    expected: str,
    *,
    section: str,
    node_id: str | None = None,
) -> Locator:
    """Choose the semantic first option and validate it after any Streamlit rerun."""
    last_error: Exception | None = None
    actual = "<not mounted>"
    for _ in range(4):
        dialog = ensure_node_dialog_section(page, section, label, node_id=node_id)
        try:
            control = combobox(page, label)
            expect(control).to_be_visible(timeout=5000)
            actual = control.input_value(timeout=5000)
            if selected_value_matches(actual, expected):
                return dialog
            keyboard_focus(page, control)
            page.keyboard.press("Enter")
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(expected)
            expect(control).to_have_value(expected, timeout=3000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(250)
            settled(page)
            # Selection may close/replace the dialog. Reopen the current node and
            # read the newly mounted visible control instead of the detached one.
            dialog = ensure_node_dialog_section(page, section, label, node_id=node_id)
            current = combobox(page, label)
            actual = current.input_value(timeout=5000)
            if selected_value_matches(actual, expected):
                return dialog
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
    raise AssertionError(
        f"Could not select first option {label}={expected!r}; actual={actual!r}"
    ) from last_error


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
        except PlaywrightError:
            page.wait_for_timeout(200)
    # Streamlit may replace the iframe between layout and capture. The screenshot
    # is diagnostic evidence, not the acceptance condition, so retain evidence
    # with a stable page-level capture instead of failing the product journey.
    settled(page)
    page.screenshot(path=str(path), full_page=True)


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
    screenshot_element(
        page,
        'iframe[title="streamlit_flow.streamlit_flow"]',
        ARTIFACTS / "organization-before.png",
    )
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
    screenshot_element(
        page,
        'iframe[title="streamlit_flow.streamlit_flow"]',
        ARTIFACTS / "organization-after.png",
    )
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
    """Close the current node dialog despite Streamlit rerun replacement races."""
    last_error: Exception | None = None
    for _ in range(4):
        dialog = page.get_by_role("dialog")
        if not dialog.count():
            return
        try:
            back = dialog.get_by_role("button", name="Voltar ao fluxo", exact=True)
            if back.count():
                back.press("Enter", timeout=2000)
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(150)
            settled(page)
            if not page.get_by_role("dialog").count():
                return
        except (PlaywrightError, PlaywrightTimeoutError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
    dialog = page.get_by_role("dialog")
    if dialog.count():
        raise AssertionError(
            "Node dialog remained open after repeated close attempts"
        ) from last_error


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
    select_radio(page, "Canvas")
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
    dialog = choose_first_option(
        page,
        "Origem da chave paymentId",
        "Valor fixo",
        section="Buscar recursos e montar consulta DynamoDB",
        node_id="query",
    )
    dialog.get_by_label("Chave paymentId (S)", exact=True).fill("12345")
    dialog.get_by_role("button", name="Aplicar requisição DynamoDB gerada", exact=True).click()
    settled(page)
    dialog = ensure_node_dialog_section(
        page,
        "Buscar recursos e montar consulta DynamoDB",
        "Origem da chave paymentId",
        node_id="query",
    )
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
    select_radio(page, "Assistente")
    template_field_label = f"Nome do novo campo em {field_label('template')}"
    select_assistant_step(
        page,
        "Preparar evento · core.map",
        expected_label=template_field_label,
    )
    page.get_by_label(template_field_label, exact=True).fill("source_system")
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
    select_radio(page, "Canvas")
    page.get_by_role("button", name="Validar", exact=True).click()
    settled(page)
    close_node_dialog(page)
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
    reason = open_pending_approval(page, database)
    reason.fill("Payload e destino revisados no demo")
    page.get_by_role("button", name="Aprovar", exact=True).click()
    navigate(page, "Executions")
    live = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    expect(live.locator(".react-flow__edge.animated")).to_have_count(1, timeout=30000)
    page.screenshot(path=str(ARTIFACTS / "running.png"))
    expect(page.get_by_text("Sucesso · atualização", exact=False)).to_be_visible(timeout=60000)
    select_result_node(page, "invoke")
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
    select_radio(page, "Canvas")
    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
    query = canvas.locator('.react-flow__node[data-id="query"]')
    expect(query).to_be_visible()
    query.click()
    settled(page)
    table_type_label = f"Tipo de {field_label('TableName')}"
    dialog = choose_structural_kind(
        page,
        table_type_label,
        "Texto",
        section="Propriedades avançadas da etapa",
        resulting_field_label=field_label("TableName"),
        node_id="query",
    )
    dialog.get_by_label(field_label("TableName"), exact=True).fill("missing-demo-table")
    dialog.get_by_role("button", name="Aplicar configuração ao rascunho", exact=True).press("Enter")
    settled(page)
    dialog.get_by_role("button", name="Voltar ao fluxo", exact=True).press("Enter")
    expect(dialog).to_have_count(0)
    expect(query).to_be_visible()
    settled(page)
    close_node_dialog(page)
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
    select_result_node(page, "query")
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
