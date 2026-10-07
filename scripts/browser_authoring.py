"""User-created visual journey. Keyboard traversal is real Tab/Shift+Tab, not focus injection."""

import json
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page, expect

from flowops.persistence.repository import Repository
from flowops.streamlit.localization import field_label
from scripts.browser_workspace import settled

NAVIGATION_HEADINGS = {
    "Procedimentos": "Procedimentos",
    "Editor visual": "Editor visual de procedimentos",
    "Executar": "Executar procedimento",
    "Execuções": "Histórico de execuções",
    "Aprovações": "Aprovações",
}


def keyboard_focus(page: Page, locator: Locator) -> None:
    expect(locator).to_be_visible()
    direction = locator.evaluate("""e => {
        const focusable = [...document.querySelectorAll('a[href],button,input,select,textarea,summary,iframe,[tabindex]')].filter(n => n.tabIndex >= 0 && !n.disabled && n.getClientRects().length && (n.type !== 'radio' || n.checked));
        const current = focusable.indexOf(document.activeElement);
        const target = focusable.findIndex(n => n === e || e.contains(n));
        if (current < 0 || target < 0) return 'Tab';
        const forward = (target - current + focusable.length) % focusable.length;
        const backward = (current - target + focusable.length) % focusable.length;
        return backward < forward ? 'Shift+Tab' : 'Tab';
    }""")
    for _ in range(600):
        if locator.evaluate(
            "e => e === document.activeElement || e.contains(document.activeElement)"
        ):
            return
        page.keyboard.press(direction)
    raise AssertionError(f"Control not reachable by Tab: {locator}")


def button(page: Page, label: str) -> None:
    target = page.get_by_role("button", name=label, exact=True)
    keyboard_focus(page, target)
    page.keyboard.press("Enter")
    settled(page)


def text_field(page: Page, label: str, value: str) -> None:
    target = page.get_by_role("textbox", name=label, exact=True)
    keyboard_focus(page, target)
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(value)
    page.keyboard.press("Tab")
    settled(page)
    expect(target).to_have_value(value)


def radio(page: Page, label: str) -> None:
    # A Streamlit rerun recreates the radio group and can drop keyboard focus.
    # Re-acquire the option on every attempt and only accept navigation after
    # both the checked state and the server-rendered destination agree.
    last_error: Exception | None = None
    for _ in range(20):
        target = page.get_by_role("radio", name=label, exact=True)
        heading = NAVIGATION_HEADINGS.get(label)
        if target.is_checked():
            if not heading:
                return
            try:
                expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible(
                    timeout=5000
                )
                settled(page)
                return
            except (PlaywrightError, AssertionError) as exc:
                last_error = exc
                # The browser can mark the radio as checked before Streamlit
                # acknowledges the change. Move to the previous option, then
                # let the next loop drive back to the target with a fresh
                # keyboard event instead of accepting stale client state.
                group = target.locator("xpath=ancestor::*[@role='radiogroup'][1]")
                keyboard_focus(page, group)
                page.keyboard.press("ArrowLeft")
                settled(page)
                page.wait_for_timeout(200)
                continue
        group = target.locator("xpath=ancestor::*[@role='radiogroup'][1]")
        keyboard_focus(page, group)
        page.keyboard.press("ArrowRight")
        settled(page)
    raise AssertionError(f"Radio option not reachable: {label}") from last_error


def expand(page: Page, label: str) -> None:
    last_error: Exception | None = None
    for _ in range(6):
        settled(page)
        try:
            summary = page.locator("summary").filter(has_text=label)
            expect(summary).to_be_visible(timeout=5000)
            details = summary.locator("xpath=ancestor::details[1]")
            if details.count() and details.evaluate("node => node.open"):
                return
            keyboard_focus(page, summary)
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
            settled(page)
            summary = page.locator("summary").filter(has_text=label)
            expect(summary).to_be_visible(timeout=5000)
            details = summary.locator("xpath=ancestor::details[1]")
            if details.count() and details.evaluate("node => node.open"):
                return
        except (PlaywrightError, AssertionError) as exc:
            last_error = exc
            page.wait_for_timeout(250)
    raise AssertionError(f"Expander did not become available/open: {label}") from last_error


def combo(page: Page, label: str, value: str) -> None:
    target = page.get_by_role("combobox", name=label, exact=True)
    keyboard_focus(page, target)
    # Open the BaseWeb listbox, filter to the exact accessible value and commit
    # the filtered selection directly with Enter. No pointer interaction.
    page.keyboard.press("Enter")
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(value)
    expect(target).to_have_value(value)
    page.keyboard.press("Enter")
    page.wait_for_timeout(750)
    settled(page)
    expect(page.get_by_role("combobox", name=label, exact=True)).to_have_value(value)


def journey(page: Page, url: str, database: Path, artifacts: Path) -> None:
    repo = Repository(database)
    before = {book.id for book in repo.list_runbooks()}
    page.goto(url)
    settled(page)
    radio(page, "Procedimentos")
    expand(page, "Criar por objetivo: consultar DynamoDB e enviar para Lambda")
    text_field(page, "Nome do novo fluxo", "Jornada visual por teclado")
    button(page, "Continuar")
    text_field(page, "Tabela a consultar", "payments")
    text_field(page, "Valor da chave de partição", "12345")
    button(page, "Continuar")
    button(page, "Voltar")
    expect(page.get_by_role("textbox", name="Tabela a consultar", exact=True)).to_have_value(
        "payments"
    )
    button(page, "Continuar")
    checkbox = page.get_by_role("checkbox", name="Filtrar registros pelo status", exact=True)
    keyboard_focus(page, checkbox)
    page.keyboard.press("Space")
    button(page, "Continuar")
    text_field(page, "Função Lambda de destino", "payment-processor")
    button(page, "Continuar")
    button(page, "Criar rascunho e abrir editor")
    added = [book for book in repo.list_runbooks() if book.id not in before]
    assert len(added) == 1
    book, revision = repo.get_draft(added[0].id)
    assert len(book.nodes) == 7 and "payment_id" in book.parameters
    expect(page.get_by_role("radio", name="Assistente", exact=True)).to_be_checked()
    button(page, "Próxima etapa")  # filter
    button(page, "Prévia fictícia da transformação")
    button(page, "Próxima etapa")  # map
    button(page, "Prévia fictícia da transformação")
    button(page, "Próxima etapa")  # approval
    button(page, "Próxima etapa")  # lambda
    expand(page, "Criar parâmetro para source")
    text_field(page, "Nome do parâmetro de source", "source_system")
    checkbox = page.get_by_role(
        "checkbox", name="Usar valor atual de source como padrão", exact=True
    )
    keyboard_focus(page, checkbox)
    page.keyboard.press("Space")
    button(page, "Preparar parâmetro e vínculo de source")
    assert "source_system" not in repo.get_draft(book.id)[0].parameters
    button(page, "Aplicar configuração ao rascunho")
    button(page, "Desfazer edição")
    button(page, "Refazer edição")
    expect(page.get_by_role("radio", name="Assistente", exact=True)).to_be_checked()
    expect(page.get_by_role("combobox", name="Tipo de source", exact=True)).to_have_value(
        "Valor de outra origem"
    )
    # Add another field to the payload, using only the visual controls.
    text_field(page, f"Nome do novo campo em {field_label('Payload')}", "origin")
    button(page, f"Adicionar campo em {field_label('Payload')}")
    text_field(page, field_label("origin"), "web")
    button(page, "Aplicar configuração ao rascunho")
    expand(page, "Revisar pendências e próximos passos")
    expect(page.get_by_text("Revisão estrutural sem pendências.", exact=False)).to_be_visible()
    button(page, "Validar")
    button(page, "Salvar rascunho")
    persisted, _ = repo.get_draft(book.id)
    assert persisted.parameters["source_system"].default == "flowops"
    button(page, "Publicar versão")
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / "keyboard-authoring.png"))
    radio(page, "Executar")
    text_field(page, "Motivo / referência da mudança", "Validar jornada fictícia por teclado")
    button(page, "Enviar execução")
    expect(page.get_by_text("Sucesso · atualização", exact=False)).to_be_visible(timeout=30000)
    from flowops.persistence.executions import ExecutionStore

    store = ExecutionStore(repo)
    assert not store.pending_approvals()
    radio(page, "Execuções")
    radio(page, "Executar")
    simulation = page.get_by_role("checkbox", name="Simulação do FlowOps", exact=True)
    keyboard_focus(page, simulation)
    page.keyboard.press("Space")
    settled(page)
    button(page, "Enviar execução")
    expect(page.get_by_text("Execução pausada.", exact=False)).to_be_visible(timeout=30000)
    radio(page, "Aprovações")
    text_field(page, "Motivo da decisão", "Dados fictícios e função revisados")
    button(page, "Aprovar")
    radio(page, "Execuções")
    execution = next(entry for entry in store.history() if not entry.dry_run)
    combo(page, "Detalhes da execução", execution.id)
    expect(page.get_by_text("Sucesso · atualização", exact=False)).to_be_visible(timeout=30000)
    combo(page, "Etapa do resultado", "invoke")
    with page.expect_download() as downloaded:
        button(page, "Baixar resultado em JSON")
    downloaded.value.save_as(artifacts / "invoke-result.json")
    body = json.loads((artifacts / "invoke-result.json").read_text(encoding="utf-8"))
    assert body["Payload"]["payload"]["payments"][0]["payment_id"] == "12345"
    with page.expect_download() as downloaded:
        button(page, "Baixar resultado em CSV")
    downloaded.value.save_as(artifacts / "invoke-result.csv")
    (artifacts / "keyboard.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "created_by_user": book.id,
                "manual_JSON": False,
                "manual_expressions": False,
                "focus_injection": False,
                "input": "Tab + arrows + Enter + Space + text; combobox selections committed by keyboard only",
                "persisted_revision": repo.get_draft(book.id)[1],
            },
            indent=2,
        )
    )
    # Inspect the new React surface separately from the keyboard-first journey.
    radio(page, "Editor visual")
    combo(page, "Procedimento em edição", "Jornada visual por teclado · default")
    radio(page, "Canvas avançado")
    react_proof(page, artifacts, "Jornada visual por teclado")


def react_proof(page: Page, artifacts: Path, book_name: str) -> None:
    frame = page.frame_locator('iframe[title="flowops.streamlit.react_editor.flowops_editor"]')
    expect(frame.get_by_role("heading", name=book_name, exact=True)).to_be_visible(timeout=30000)
    frame.get_by_role("button", name="Consultar DynamoDB dynamodb.query", exact=False).first.click()
    field = frame.get_by_role("textbox", name="Nome da etapa no canvas", exact=True)
    field.fill("Consulta no novo builder")
    frame.get_by_role("button", name="Aplicar ao rascunho", exact=True).click()
    settled(page)
    expect(
        frame.get_by_role("heading", name="Consulta no novo builder", exact=True)
    ).to_be_visible()
    for width in (1440, 1024, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        page.wait_for_timeout(500)
        page.locator('iframe[title="flowops.streamlit.react_editor.flowops_editor"]').screenshot(
            path=str(artifacts / f"builder-{width}.png")
        )
        assert frame.locator("body").evaluate("e => e.scrollWidth <= innerWidth + 2")
    (artifacts / "react.json").write_text(
        json.dumps({"status": "PASS", "viewports": [1440, 1024, 390], "inline_and_inspector": True})
    )
