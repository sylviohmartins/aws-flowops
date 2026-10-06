"""Portuguese chrome checks, shared by the isolated workspace browser journey."""

from pathlib import Path

from playwright.sync_api import Page, expect

from flowops.streamlit.navigation import PAGE_LABELS


def check_adapter(page: Page) -> None:
    """Use controlled fixtures to verify that translation never changes app data."""
    page.set_content("""<html lang="en"><body>
      <section data-testid="stFileUploader"><div data-testid="stFileUploaderDropzone"><button><span translate="no">upload</span><span>Upload</span></button></div>
        <span>Limit 200MB per file</span></section>
      <div data-baseweb="popover"><span>No options</span><div role="option">Source</div></div>
      <div class="modal"><label>Source</label><input value="Source">
        <pre>{"TableName":"Source"}</pre><code>Delete Edge</code></div>
      <iframe title="streamlit_flow.streamlit_flow" srcdoc='<html lang="en"><body>
        <div class="btn-group-vertical"><button>Delete Edge</button></div></body></html>'></iframe>
    </body></html>""")
    script = (Path(__file__).resolve().parents[1] / "flowops/streamlit/ui_locale.js").read_text(
        encoding="utf-8"
    )
    page.evaluate(
        """source => {
      const setup = new Function('return (' + source.replace('export default ', '') + ')')();
      window.cleanupLocale = setup({parentElement: document.body});
    }""",
        script,
    )
    expect(page.locator("html")).to_have_attribute("lang", "pt-BR")
    expect(page.get_by_text("Selecionar arquivo", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Selecionar arquivo", exact=True)).to_be_visible()
    expect(page.get_by_text("Limite de 200MB por arquivo", exact=True)).to_be_visible()
    expect(page.get_by_role("option")).to_have_text("Source")
    expect(page.locator("input")).to_have_value("Source")
    expect(page.locator("pre")).to_have_text('{"TableName":"Source"}')
    expect(page.locator("code")).to_have_text("Delete Edge")
    frame = page.frame_locator("iframe")
    expect(frame.get_by_role("button", name="Excluir conexão", exact=True)).to_be_visible()
    page.locator(".modal").evaluate(
        "el => { const b = document.createElement('button'); b.textContent = 'Save Changes'; el.append(b); }"
    )
    expect(page.get_by_role("button", name="Salvar alterações", exact=True)).to_be_visible()
    page.locator("iframe").evaluate("el => el.remove()")
    page.evaluate("window.cleanupLocale()")
    expect(page.locator("html")).to_have_attribute("lang", "en")


def check_pages(page: Page, artifacts: Path) -> None:
    # Import lazily to share the server-acknowledgement helper without a module cycle.
    from scripts.browser_workspace import navigate

    headings = {
        "Dashboard": "Execuções recentes",
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
    artifacts.mkdir(parents=True, exist_ok=True)
    page.get_by_test_id("stMainMenu").click()
    expect(page.get_by_role("menu", name="Menu da aplicação")).to_be_visible()
    expect(page.get_by_role("menuitemradio", name="Sistema", exact=True)).to_be_visible()
    expect(
        page.get_by_role("menuitemcheckbox", name="Atualizar automaticamente", exact=True)
    ).to_be_visible()
    page.keyboard.press("Escape")
    for key, heading in headings.items():
        navigate(page, key)
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("lang", "pt-BR")
        for label in PAGE_LABELS.values():
            expect(page.get_by_role("radio", name=label, exact=True)).to_have_count(1)
        expect(page.get_by_test_id("stException")).to_have_count(0)
        if key == "Runbooks":
            page.get_by_test_id("stFileUploader").scroll_into_view_if_needed()
            (artifacts / "uploader.html").write_text(page.content(), encoding="utf-8")
            expect(page.get_by_role("button", name="Selecionar arquivo", exact=True)).to_have_count(
                1
            )
        if key == "Executions":
            page.get_by_label("De", exact=True).click()
            page.screenshot(path=str(artifacts / "calendar.png"))
            (artifacts / "calendar.html").write_text(page.content(), encoding="utf-8")
            page.keyboard.press("Escape")
        (artifacts / f"{key}.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
        page.screenshot(path=str(artifacts / f"{key}.png"))
