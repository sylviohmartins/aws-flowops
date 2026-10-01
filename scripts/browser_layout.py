"""Pixel-level layout checks for the isolated DEMO browser acceptance journey."""

import json
from pathlib import Path

from playwright.sync_api import Page, expect

from flowops.streamlit.navigation import PAGE_LABELS

MEASURE_LAYOUT = """() => {
  const root = document.querySelector('.st-key-flowops-workspace');
  const failures = [];
  const visible = e => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.height > 0 && getComputedStyle(e).visibility !== 'hidden'
      && !e.closest('[data-testid="hidden-dateinput-container"]')
      && !e.closest('details:not([open]) > div');
  };
  const bounds = root.getBoundingClientRect();
  const surfaces = [root, ...document.querySelectorAll('.st-key-flowops-node-editor')];
  const grids = [];
  if (document.documentElement.scrollWidth > innerWidth + 2) failures.push('page overflow');
  for (const surface of surfaces) {
    const sb = surface.getBoundingClientRect();
    if (sb.left < -2 || sb.right > innerWidth + 2) failures.push('surface outside viewport');
    for (const row of surface.querySelectorAll('[data-testid="stHorizontalBlock"]')) {
      if (!visible(row)) continue;
      const items = [...row.children].filter(visible).map(e => e.getBoundingClientRect());
      const style = getComputedStyle(row);
      if (style.display !== 'grid' || style.gap !== '16px') failures.push('inconsistent grid');
      for (const item of items) {
        if (Math.abs(item.width - items[0].width) > 2) failures.push('unequal tracks');
        if (item.left < sb.left - 2 || item.right > sb.right + 2) failures.push('grid overflow');
      }
      for (let i = 1; i < items.length; i++) {
        if (Math.abs(items[i].top - items[i-1].top) < 2
            && Math.abs(items[i].left - items[i-1].right - 16) > 2) failures.push('unequal gap');
      }
      grids.push({tracks: style.gridTemplateColumns, count: items.length});
    }
    for (const e of surface.querySelectorAll('input,textarea,iframe,button')) {
      if (!visible(e) || e.closest('[data-testid="stDataFrame"], [data-testid="stJson"]')) continue;
      const b = e.getBoundingClientRect();
      if (b.left < sb.left-2 || b.right > sb.right+2) failures.push('control outside surface');
      const action = e.tagName === 'BUTTON' && e.closest(
        '[data-testid="stButton"], [data-testid="stFormSubmitButton"], [data-testid="stDownloadButton"]');
      if (action && b.height < 43.5) failures.push('small action target');
      if (action && e.closest('[data-testid="stHorizontalBlock"]')) {
        const column = e.closest('[data-testid="stColumn"]').getBoundingClientRect();
        if (Math.abs(b.width-column.width)>2) failures.push('narrow action in grid');
      }
    }
  }
  for (const h of root.querySelectorAll(':scope > [data-testid="stElementContainer"] > [data-testid="stHeading"]')) {
    if (Math.abs(h.getBoundingClientRect().left-bounds.left)>2) failures.push('heading off grid');
  }
  return {width:innerWidth, contentWidth:bounds.width, grids, failures:[...new Set(failures)]};
}"""


def check_layout_fixture(page: Page) -> None:
    """Prove that the measurement catches defects and styling does not leak to hosts."""
    page.set_content("""<div id="host" style="display:flex;gap:23px"><button>Host</button></div>
      <div class="st-key-flowops-workspace" style="width:400px;margin:0">
        <div data-testid="stHorizontalBlock">
          <div data-testid="stColumn"><div data-testid="stElementContainer">
            <div data-testid="stButton"><button>Validar</button></div></div></div>
          <div data-testid="stColumn"><div data-testid="stElementContainer">
            <div data-testid="stButton"><button>Salvar rascunho</button></div></div></div>
        </div>
      </div>""")
    host_before = page.locator("#host").evaluate(
        "e => [getComputedStyle(e).display, getComputedStyle(e).gap, e.firstChild.offsetHeight]"
    )
    page.add_style_tag(
        path=str(Path(__file__).resolve().parents[1] / "flowops/streamlit/workspace.css")
    )
    assert (
        page.locator("#host").evaluate(
            "e => [getComputedStyle(e).display, getComputedStyle(e).gap, e.firstChild.offsetHeight]"
        )
        == host_before
    )
    assert not page.evaluate(MEASURE_LAYOUT)["failures"]
    page.get_by_test_id("stColumn").last.evaluate("e => e.style.width = '90px'")
    assert "unequal tracks" in page.evaluate(MEASURE_LAYOUT)["failures"]


def check_layout_pages(page: Page, artifacts: Path) -> None:
    from scripts.browser_workspace import navigate, settled

    artifacts.mkdir(parents=True, exist_ok=True)
    reports = []
    previous = page.viewport_size
    try:
        for width in (1440, 1024, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            sidebar = page.get_by_test_id("stSidebar")
            if width < 640:
                # Streamlit collapses asynchronously when crossing its mobile breakpoint.
                expect(sidebar).to_have_attribute("aria-expanded", "false")
            for key in PAGE_LABELS:
                if sidebar.get_attribute("aria-expanded") == "false":
                    page.get_by_test_id("stExpandSidebarButton").click()
                    expect(sidebar).to_have_attribute("aria-expanded", "true")
                navigate(page, key)
                if width < 640:
                    page.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
                    expect(sidebar).to_have_attribute("aria-expanded", "false")
                    page.wait_for_function(
                        "() => document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().right <= 1"
                    )
                settled(page)
                report = page.evaluate(MEASURE_LAYOUT) | {"page": key}
                reports.append(report)
                (artifacts / "measurements.json").write_text(
                    json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                page.screenshot(path=str(artifacts / f"{key}-{width}.png"))
                assert not report["failures"], report
                expect(page.get_by_test_id("stException")).to_have_count(0)
                # This opens an existing step but never changes or submits its fields.
                if key == "Editor":
                    canvas_view = page.get_by_role("radio", name="Canvas", exact=True)
                    if not canvas_view.is_checked():
                        canvas_view.press("Space")
                        settled(page)
                    canvas = page.frame_locator('iframe[title="streamlit_flow.streamlit_flow"]')
                    query = canvas.locator('.react-flow__node[data-id="query"]')
                    expect(query).to_be_visible()
                    query.click()
                    dialog = page.get_by_role("dialog")
                    expect(
                        dialog.get_by_role("heading", name="Editar etapa", exact=True)
                    ).to_be_visible()
                    settled(page)
                    dialog_report = page.evaluate(MEASURE_LAYOUT) | {"page": "NodeDialog"}
                    reports.append(dialog_report)
                    page.screenshot(path=str(artifacts / f"NodeDialog-{width}.png"))
                    assert not dialog_report["failures"], dialog_report
                    dialog.get_by_role("button", name="Voltar ao fluxo", exact=True).click()
                    expect(dialog).to_have_count(0)
        (artifacts / "measurements.json").write_text(
            json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        if previous:
            page.set_viewport_size(previous)
            if page.get_by_test_id("stSidebar").get_attribute("aria-expanded") == "false":
                page.get_by_test_id("stExpandSidebarButton").click()
