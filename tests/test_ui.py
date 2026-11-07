"""Every button of the page in a real browser (Playwright + Chromium), against the app
served from this process: upload, key estimate, the exact method, the billing (its card
and the spot tab), the spot prices (a fake OTE), the tabs and their right column, days, the heat-map
metric, the grids, export, print, theme, language, the article link, a bad file, and the
reload offer after a deploy. The tests run in order on one page and fail on any console
error or HTTP error.

Skipped without Playwright or its browser, except in CI (``CI`` set), which installs
both::

    pip install -r requirements-dev.txt
    python -m playwright install --with-deps chromium
"""
from __future__ import annotations

import os
import threading
from datetime import date, timedelta

import numpy as np
import openpyxl
import pytest

CI = bool(os.environ.get("CI"))            # GitHub Actions: a missing browser is an error
try:
    from playwright import sync_api
except ImportError:
    if CI:
        raise
    pytest.skip("Playwright is not installed", allow_module_level=True)

import app as webapp  # noqa: E402
import spot  # noqa: E402
from conftest import all_report_csv, synthetic_group  # noqa: E402
from test_spot import FakeOTE  # noqa: E402

JOB_TIMEOUT = 120_000          # ms: a computation, on a slow CI runner
LABELS = {"cs": "Spočítat vyúčtování podle přínosu",
          "en": "Compute the billing by contribution",
          "de": "Abrechnung nach Beitrag berechnen"}


class UI:
    """The page, the errors it reported, and the steps the tests repeat."""

    def __init__(self, page, base_url: str):
        self.page, self.base_url, self.errors = page, base_url, []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(f"page error: {e}"))
        page.on("response", lambda r: self.errors.append(f"HTTP {r.status} {r.url}")
                if r.status >= 400 else None)

    def text(self, sel: str) -> str:
        return self.page.inner_text(sel)

    def wait_filled(self, sel: str, empty: bool = False) -> None:
        """Until the element has some text (or, ``empty``, none)."""
        self.page.wait_for_function(
            "([sel, empty]) => !(document.querySelector(sel).innerText.trim()) === empty",
            arg=[sel, empty])

    def wait_text(self, sel: str, part: str) -> None:
        """Until the element shows ``part`` (a re-render may hide it a moment)."""
        self.page.wait_for_function(
            "([sel, part]) => (document.querySelector(sel) || {}).innerText?.includes(part)",
            arg=[sel, part])

    def visible(self, sel: str) -> bool:
        return self.page.locator(sel).is_visible()

    def type_number(self, sel: str, value: str) -> None:
        """A number field (debounced: applied on Enter)."""
        self.page.fill(sel, value)
        self.page.press(sel, "Enter")

    def upload(self, path) -> None:
        self.page.set_input_files("#upload input", str(path))
        self.wait_text("#upload-status", path.name)
        self.idle("exact")                                # the key estimate

    def idle(self, kind: str) -> None:
        """Wait until the card's button is enabled again (its job finished)."""
        self.page.wait_for_selector(f"#{kind}-btn:not([disabled])", state="attached",
                                    timeout=JOB_TIMEOUT)

    def run(self, kind: str, button: str | None = None) -> tuple[str, str]:
        """Click the button (by default the card's own), wait until the card's job
        started and finished; (class, text) of its progress bar."""
        self.page.click(button or f"#{kind}-btn")
        self.page.wait_for_selector(f"#{kind}-btn[disabled]", state="attached",
                                    timeout=15_000)
        self.idle(kind)
        return (self.page.get_attribute(f"#{kind}-progress", "class"),
                self.text(f"#{kind}-text"))

    def option(self, group: str, value: str | None = None, nth: int | None = None):
        """The label of an option of a radio group / checklist (its input is hidden)."""
        labels = self.page.locator(f"#{group} label")
        if nth is not None:
            return labels.nth(nth)
        return labels.filter(has=self.page.locator(f"input[value='{value}']"))

    def checked(self, group: str, value: str) -> bool:
        return self.page.is_checked(f"#{group} input[value='{value}']")

    def day(self) -> date:
        d, m, y = self.page.input_value(".day-picker input").split(".")
        return date(int(y), int(m), int(d))

    def settle(self, ms: int = 800) -> None:
        """Let the callbacks a click started answer (and report any error)."""
        self.page.wait_for_timeout(ms)
        self.page.wait_for_function(
            "() => !document.querySelector('[data-dash-is-loading=\"true\"]')")


@pytest.fixture(scope="module")
def csvs(tmp_path_factory):
    """One producer (spot prices: hourly in CZK before 2025-10, then 15 min in EUR), and
    two producers (pair keys, the pool)."""
    d = tmp_path_factory.mktemp("ui")
    P, D, S, _ = synthetic_group(5, 96 * 40, 5, seed=4)
    one = d / "skupina.csv"
    one.write_bytes(all_report_csv(P, D, S, start="2025-09-15"))
    P, D, S, _ = synthetic_group(6, 96 * 21, 5, seed=8)
    pool = d / "bazen.csv"
    pool.write_bytes(all_report_csv(np.stack([P // 2, P - P // 2], axis=1), D, S,
                                    start="2026-03-01"))
    bad = d / "spatny.csv"
    bad.write_bytes(b"this is not an EDC report\n1;2;3\n")
    return one, pool, bad


@pytest.fixture(scope="module")
def ui():
    import logging

    from werkzeug.serving import make_server
    logging.getLogger("werkzeug").setLevel(logging.WARNING)      # no line per request
    http_post = spot.http_post
    spot.http_post = FakeOTE()                    # the real OTE is not reachable in CI
    spot._CACHE.clear()
    srv = make_server("127.0.0.1", 0, webapp.server, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as exc:              # browser not installed
                if CI:
                    raise
                pytest.skip(f"no Chromium for Playwright: {exc}")
            page = browser.new_page(viewport={"width": 1500, "height": 1000},
                                    accept_downloads=True)
            page.set_default_timeout(30_000)
            ui = UI(page, f"http://127.0.0.1:{srv.server_port}")
            page.goto(ui.base_url)
            page.wait_for_selector("#upload input", state="attached")
            yield ui
            browser.close()
    finally:
        srv.shutdown()
        spot.http_post = http_post
        spot._CACHE.clear()


@pytest.fixture(autouse=True)
def no_errors(ui):
    ui.errors.clear()
    yield
    ui.settle(300)
    assert ui.errors == []


# --- sharing tab ------------------------------------------------------------------------


def test_page_and_icon(ui):
    page = ui.page
    assert page.title() == "EDC sharing report"
    assert page.get_attribute('meta[name="app-version"]', "content") == webapp.VERSION
    for href in ("/assets/favicon.svg", "/assets/favicon.ico", "/favicon.ico"):
        assert page.request.get(ui.base_url + href).status == 200


def test_upload(ui, csvs):
    ui.upload(csvs[0])
    assert ui.visible("#report")
    ui.wait_text("#upload-status", "✓")
    ui.wait_filled("#fit-info")                          # the key estimate is shown


def test_theme_button(ui):
    html = ui.page.locator("html")
    before = html.get_attribute("data-theme")
    ui.page.click("#theme-btn")
    ui.settle()
    assert html.get_attribute("data-theme") != before
    ui.page.click("#theme-btn")
    ui.settle()
    assert html.get_attribute("data-theme") == before


@pytest.mark.parametrize("lang", ["en", "de", "cs"])
def test_language(ui, lang):
    ui.option("lang", lang).click()
    ui.page.wait_for_function(
        "t => document.getElementById('bill-btn').innerText.trim() === t", arg=LABELS[lang])
    assert ui.text("#spot-bill-btn").strip() == LABELS[lang]


def test_exact(ui):
    cls, text = ui.run("exact")
    assert "done" in cls, text
    ui.wait_filled("#exact-result")


def test_bill_tab(ui):
    """The billing has its own tab: its card above the columns, the sharing tab's card
    hidden; the right column waits for the billing (only the EDC report is drawn)."""
    ui.page.click("#tab-bill")
    ui.page.wait_for_selector("#pane-bill", state="visible")
    assert not ui.visible("#pane-sharing") and ui.visible("#pane-columns")
    ui.page.wait_for_selector("#compare.single", state="attached")
    assert not ui.visible("#cmp-card") and not ui.visible("#settle-card")


def test_bill_without_prices(ui):
    """Refused (the button never gets busy): says which price is missing."""
    ui.page.click("#bill-btn")
    ui.page.wait_for_selector("#bill-progress.error", state="attached")
    assert "cen" in ui.text("#bill-text")                  # "výkupní cenu" / "cenu od …"


def test_bill(ui):
    ui.type_number("#feed-in", "1,2")
    ui.type_number("#price-default", "4,5")
    ui.settle()
    assert ui.page.input_value("#spot-feed-in") == "1,2"   # the same field on the spot tab
    cls, text = ui.run("bill")
    assert "done" in cls, text
    ui.page.wait_for_selector("#settle-card", state="visible")
    ui.wait_filled("#bill-result")


def test_tabs_choose_the_right_column(ui):
    """Both computations exist: each tab draws its own next to the EDC report."""
    ui.page.wait_for_selector("#compare.right-bill", state="attached")
    ui.page.click("#tab-sharing")
    ui.page.wait_for_selector("#compare.right-exact", state="attached")
    ui.page.wait_for_selector("#cmp-card", state="visible")
    assert not ui.visible("#settle-card") and not ui.visible("#pane-bill")
    ui.page.click("#tab-bill")
    ui.page.wait_for_selector("#compare.right-bill", state="attached")
    ui.page.wait_for_selector("#settle-card", state="visible")
    assert not ui.visible("#cmp-card")
    ui.page.click("#tab-sharing")                          # the next tests start there
    ui.page.wait_for_selector("#pane-sharing", state="visible")


def test_day_buttons(ui):
    day = ui.day()
    before = ui.page.input_value(".day-picker input")      # read before the click: the
    ui.page.click("#btn-prev-day")                         # answer may come at once
    ui.page.wait_for_function(
        "d => document.querySelector('.day-picker input').value !== d", arg=before)
    assert ui.day() == day - timedelta(days=1)
    ui.page.click("#btn-next-day")
    ui.settle()
    assert ui.day() == day


def test_heat_metric(ui):
    inputs = ui.page.locator("#heat-metric input")
    assert inputs.count() >= 2
    for i in (1, 0):
        ui.option("heat-metric", nth=i).click()
        ui.settle()
        assert inputs.nth(i).is_checked()


def test_untick_member(ui):
    box = ui.page.locator("#members .ag-row[row-index='0'] input.ag-checkbox-input")
    box.click()
    ui.settle()
    assert not box.is_checked()
    box.click()
    ui.settle()
    assert box.is_checked()


def test_key_edit_and_reset(ui):
    cell = ui.page.locator("#members .ag-row[row-index='0'] .ag-cell[col-id='key']")
    estimate = cell.inner_text()
    cell.click()
    ui.page.keyboard.type("33")
    ui.page.keyboard.press("Enter")
    ui.wait_filled("#exact-stale")                         # keys changed since the recompute
    ui.page.click("#btn-clear-keys")
    ui.wait_filled("#exact-stale", empty=True)
    assert cell.inner_text() == estimate


@pytest.mark.parametrize("full_ean", [False, True])
def test_export(ui, tmp_path, full_ean):
    ui.page.fill("#group", "Testovaci skupina")
    ui.page.press("#group", "Enter")
    if full_ean:
        ui.option("export-full-ean", "full").click()
    with ui.page.expect_download(timeout=JOB_TIMEOUT) as info:
        ui.page.click("#btn-export")
    name = info.value.suggested_filename
    assert name.endswith(".xlsx") and "Testovaci-skupina" in name
    path = tmp_path / name
    info.value.save_as(path)
    book = openpyxl.load_workbook(path, read_only=True)
    assert len(book.sheetnames) >= 3
    if full_ean:
        ui.option("export-full-ean", "full").click()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_print(ui, theme):
    """A dark page prints light, and returns to dark after printing."""
    html = ui.page.locator("html")
    if html.get_attribute("data-theme") != theme:
        ui.page.click("#theme-btn")
        ui.settle()
    ui.page.evaluate("() => { window.__printed = 0; window.print = () => { window.__printed++; }; }")
    ui.page.click("#btn-print")
    ui.page.wait_for_function("() => window.__printed > 0", timeout=15_000)
    assert html.get_attribute("data-theme") == "light"
    ui.page.evaluate("() => window.dispatchEvent(new Event('afterprint'))")
    ui.settle()
    assert html.get_attribute("data-theme") == theme
    if theme == "dark":
        ui.page.click("#theme-btn")
        ui.settle()


def test_article_link(ui):
    href = ui.page.get_attribute("#exact-article", "href")
    assert ui.page.request.get(ui.base_url + href).status == 200


# --- spot tab ---------------------------------------------------------------------------


def test_spot_tab(ui):
    ui.page.click("#tab-spot")
    ui.page.wait_for_selector("#spot-progress.done", state="attached", timeout=JOB_TIMEOUT)
    ui.page.wait_for_selector("#spot-body", state="visible")
    assert not ui.visible("#pane-sharing") and not ui.visible("#pane-columns")
    ui.wait_filled("#spot-verdict")
    assert not ui.visible("#spot-btn")                   # the prices come by themselves
    assert ui.visible("#spot-bill-btn")                  # always there …
    ui.page.wait_for_selector("#spot-bill-btn[disabled]", state="attached")  # … off: billed


def test_spot_fee_and_curtail(ui):
    before = ui.text("#spot-tiles")
    ui.type_number("#spot-fee", "300")
    ui.page.wait_for_function("t => document.getElementById('spot-tiles').innerText !== t",
                              arg=before)
    ui.option("spot-curtail", "on").click()
    ui.settle()
    assert ui.checked("spot-curtail", "on")
    ui.option("spot-curtail", "on").click()
    ui.type_number("#spot-fee", "0")
    ui.settle()


def test_spot_bill_button(ui):
    """Other prices: the billing is stale, the spot card's button turns on (it does not
    appear: the card does not move) and runs it; then it is off again."""
    top = ui.page.locator("#spot-verdict").bounding_box()["y"]
    ui.type_number("#spot-price-default", "5")
    ui.page.wait_for_selector("#spot-bill-btn:not([disabled])", state="visible")
    assert ui.page.locator("#spot-verdict").bounding_box()["y"] == top
    assert ui.page.input_value("#price-default") == "5"
    cls, text = ui.run("bill", button="#spot-bill-btn")
    assert "done" in cls, text
    ui.page.wait_for_selector("#spot-bill-btn[disabled]", state="visible")
    assert "done" in ui.page.get_attribute("#spot-bill-progress", "class")


def test_back_to_sharing(ui):
    ui.page.click("#tab-sharing")
    ui.page.wait_for_selector("#pane-sharing", state="visible")
    assert not ui.visible("#pane-spot")


# --- several producers, a bad file, a deploy -------------------------------------------


def test_pool(ui, csvs):
    ui.upload(csvs[1])
    ui.page.wait_for_selector("#pair-box", state="visible")
    cls, text = ui.run("exact")
    assert "done" in cls, text
    ui.page.click("#tab-bill")
    cls, text = ui.run("bill")                       # the prices typed above still hold
    assert "done" in cls, text
    ui.page.click("#tab-spot")
    ui.page.wait_for_selector("#spot-body", state="visible", timeout=JOB_TIMEOUT)
    ui.page.wait_for_selector("#spot-progress.done", state="attached", timeout=JOB_TIMEOUT)
    ui.wait_filled("#spot-verdict")
    ui.page.click("#tab-sharing")


def test_bad_file(ui, csvs):
    ui.page.set_input_files("#upload input", str(csvs[2]))
    ui.page.wait_for_selector(".status-error", state="visible")
    ui.wait_text("#upload-status", csvs[2].name)


def test_reload_offer_after_deploy(ui, monkeypatch):
    """The server answers with another code version: the page offers a reload."""
    assert not ui.visible("#stale-banner")
    monkeypatch.setattr(webapp, "VERSION", "deployed")
    ui.option("lang", "en").click()                     # any request to the server
    ui.page.wait_for_selector("#stale-banner", state="visible")
    assert "reload" in ui.text("#stale-banner").lower()
    monkeypatch.undo()
    ui.page.click("#stale-banner button")
    ui.page.wait_for_selector("#upload input", state="attached")
    ui.settle()
    assert ui.page.locator("#stale-banner").count() == 0
