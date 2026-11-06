"""Spot market instead of sharing: OTE client (against a fake OTE that answers in the
documented format), alignment to the report, the comparison, the job and the tab."""
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

import numpy as np
import pandas as pd
import pytest

import edc_data as core
import jobs
import spot
import store
from conftest import all_report_csv, synthetic_group
from figures import (
    fig_spot_daily, fig_spot_intraday, fig_spot_members, fig_spot_monthly, fig_spot_waterfall,
)
from ui import compute, layout, views
from ui import spot as ui_spot

RATE = 24.5          # CZK per EUR in the fake OTE


def _eur(ts: pd.Timestamp) -> float:
    """A day-ahead-like price (EUR/MWh): cheap at noon (negative on Sundays), dear in
    the evening."""
    h = ts.hour + ts.minute / 60
    p = 95 + 45 * np.exp(-((h - 19) / 2.5) ** 2) - 110 * np.exp(-((h - 13) / 2.5) ** 2)
    return round(p - (40 if ts.dayofweek == 6 else 0), 2)


def _day_periods(day: str, minutes: int) -> int:
    start = pd.Timestamp(day).tz_localize(spot.TZ)
    end = (pd.Timestamp(day) + pd.Timedelta(days=1)).tz_localize(spot.TZ)
    return int((end - start) / pd.Timedelta(minutes=minutes))


class FakeOTE:
    """Answers GetDamPricePeriodE, GetDamPriceE and GetDamIndexE like the OTE service."""

    def __init__(self, fault: bool = False, no_rates: bool = False):
        self.calls: list[tuple[str, str, str]] = []
        self.fault, self.no_rates = fault, no_rates

    def __call__(self, body: bytes) -> bytes:
        root = ET.fromstring(body)
        call = next(el for el in root.iter() if el.tag.endswith("}Body"))[0]
        method = call.tag.rsplit("}", 1)[-1]
        params = {c.tag.rsplit("}", 1)[-1]: c.text for c in call}
        self.calls.append((method, params["StartDate"], params["EndDate"]))
        if self.fault:
            return (b'<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
                    b"<SOAP-ENV:Body><SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode>"
                    b"<faultstring>Invalid date</faultstring></SOAP-ENV:Fault></SOAP-ENV:Body>"
                    b"</SOAP-ENV:Envelope>")
        days = pd.date_range(params["StartDate"], params["EndDate"], freq="D")
        items = []
        for d in days:
            ds = d.strftime("%Y-%m-%d")
            if method == "GetDamPricePeriodE":
                midnight = d.tz_localize(spot.TZ)
                for k in range(1, _day_periods(ds, 15) + 1):
                    ts = (midnight + pd.Timedelta(minutes=15 * (k - 1))).tz_convert(spot.TZ)
                    items.append(
                        f"<Item><Date>{ds}</Date><PeriodResolution>PT15M</PeriodResolution>"
                        f"<PeriodIndex>{k}</PeriodIndex><PeriodInterval>x</PeriodInterval>"
                        f"<Price>{_eur(ts.tz_localize(None)):.2f}</Price><HourlyPrice>1</HourlyPrice>"
                        f"<VolumeTotal>1.000</VolumeTotal></Item>")
            elif method == "GetDamPriceE":
                assert params["InEur"] == "false"
                midnight = d.tz_localize(spot.TZ)
                for h in range(1, _day_periods(ds, 60) + 1):
                    ts = (midnight + pd.Timedelta(hours=h - 1)).tz_convert(spot.TZ)
                    items.append(f"<Item><Date>{ds}</Date><Hour>{h}</Hour>"
                                 f"<Price>{_eur(ts.tz_localize(None)) * RATE:.2f}</Price>"
                                 f"<Volume>1.0</Volume></Item>")
            elif method == "GetDamIndexE" and not self.no_rates:
                items.append(f"<DamIndex><Date>{ds}</Date><EurRate>{RATE}</EurRate>"
                             f"<BaseLoad>1</BaseLoad></DamIndex>")
        tag = "DamIndex" if method == "GetDamIndexE" else "Item"
        assert all(i.startswith(f"<{tag}>") for i in items)
        return ('<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<SOAP-ENV:Body><{method}Response xmlns="http://www.ote-cr.cz/schema/service/public">'
                f"<Result>{''.join(items)}</Result></{method}Response></SOAP-ENV:Body>"
                "</SOAP-ENV:Envelope>").encode()


@pytest.fixture(autouse=True)
def _fresh_cache():
    spot.clear_cache()
    yield
    spot.clear_cache()


# ---------------------------------------------------------------------------
# OTE client
# ---------------------------------------------------------------------------


def test_request_is_the_documented_soap_envelope():
    body = spot.envelope("GetDamPricePeriodE", StartDate="2025-10-01", EndDate="2025-10-31",
                         PeriodResolution="PT15M")
    root = ET.fromstring(body)
    call = next(el for el in root.iter() if el.tag.endswith("}Body"))[0]
    assert call.tag == "{http://www.ote-cr.cz/schema/service/public}GetDamPricePeriodE"
    assert [c.tag.rsplit("}", 1)[-1] for c in call] == ["StartDate", "EndDate", "PeriodResolution"]


@pytest.mark.parametrize("day, n, unique", [("2026-03-29", 92, 92), ("2026-10-25", 100, 96),
                                            ("2026-06-01", 96, 96)])
def test_quarter_prices_land_on_local_wall_clock_also_on_dst_days(day, n, unique):
    fake = FakeOTE()
    prices = spot.parse_quarter_prices(fake(spot.envelope(
        "GetDamPricePeriodE", StartDate=day, EndDate=day, PeriodResolution="PT15M")))
    assert len(prices) == unique and prices.index.is_unique
    assert prices.index[0] == pd.Timestamp(f"{day} 00:00")
    assert prices.index[-1] == pd.Timestamp(f"{day} 23:45")
    if n == 92:                                  # 02:00–02:59 does not exist
        assert pd.Timestamp(f"{day} 02:30") not in prices.index
        assert prices[pd.Timestamp(f"{day} 03:00")] == _eur(pd.Timestamp(f"{day} 03:00"))
    noon = pd.Timestamp(f"{day} 12:15")
    assert prices[noon] == pytest.approx(_eur(noon))


def test_hourly_prices_cover_the_four_quarters():
    fake = FakeOTE()
    prices = spot.parse_hourly_prices(fake(spot.envelope(
        "GetDamPriceE", StartDate="2025-09-01", EndDate="2025-09-01", InEur="false")))
    assert len(prices) == 96
    hour = prices["2025-09-01 13:00":"2025-09-01 13:45"]
    assert len(hour) == 4 and hour.nunique() == 1
    assert hour.iloc[0] == pytest.approx(_eur(pd.Timestamp("2025-09-01 13:00")) * RATE, abs=0.01)


def test_chunks_split_at_the_15_min_market_and_at_31_days():
    days = list(pd.date_range("2025-08-20", "2025-12-05").date)
    ch = spot.chunks(days)
    assert [c.kind for c in ch] == ["hourly", "hourly", "quarter", "quarter", "quarter"]
    assert ch[1].last == date(2025, 9, 30) and ch[2].first == date(2025, 10, 1)
    assert all((c.last - c.first).days < spot.MAX_DAYS for c in ch)
    assert sum((c.last - c.first).days + 1 for c in ch) == len(days)


def test_fetch_converts_at_the_ote_rate_and_caches_finished_days():
    fake = FakeOTE()
    prices = spot.fetch_prices(date(2025, 9, 25), date(2025, 10, 10), post=fake)
    assert len(prices) == 16 * 96
    ts = pd.Timestamp("2025-10-05 13:15")                  # Sunday, 15-min market
    assert prices[ts] == pytest.approx(_eur(ts) * RATE)
    ts = pd.Timestamp("2025-09-28 19:45")                  # hourly market, CZK
    assert prices[ts] == pytest.approx(_eur(pd.Timestamp("2025-09-28 19:00")) * RATE, abs=0.01)
    methods = sorted(m for m, *_ in fake.calls)
    assert methods == ["GetDamIndexE", "GetDamPriceE", "GetDamPricePeriodE"]
    fake.calls.clear()
    again = spot.fetch_prices(date(2025, 9, 25), date(2025, 10, 10), post=fake)
    assert not fake.calls and again.equals(prices)          # all from the cache


def test_a_soap_fault_is_reported():
    with pytest.raises(spot.SpotError, match="Invalid date"):
        spot.fetch_prices(date(2025, 11, 1), date(2025, 11, 2), post=FakeOTE(fault=True))


def test_missing_ote_rates_fall_back_to_cnb():
    asked = []

    def cnb(url):
        asked.append(url)
        m = re.search(r"yearMonth=(\d{4}-\d{2})", url).group(1)
        days = pd.date_range(f"{m}-01", periods=10, freq="B")   # business days only
        rates = ",".join(f'{{"validFor":"{d:%Y-%m-%d}","currencyCode":"EUR","amount":1,'
                         f'"rate":25.0}}' for d in days)
        return f'{{"rates":[{rates}]}}'.encode()

    prices = spot.fetch_prices(date(2025, 11, 1), date(2025, 11, 3), post=FakeOTE(no_rates=True),
                               get=cnb)
    ts = pd.Timestamp("2025-11-01 10:00")                  # a Saturday: the last rate before
    assert prices[ts] == pytest.approx(_eur(ts) * 25.0)
    assert len(asked) == 1 and "currency=EUR" in asked[0]


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------


def _data(n=5, days=40, start="2025-09-20", producers=1, seed=3):
    P, D, S, _ = synthetic_group(n, 96 * days, 5, seed=seed)
    if producers > 1:
        P = np.stack([P // 2, P - P // 2], axis=1)
    return core.load_report(all_report_csv(P, D, S, start=start))


def _prices(data):
    idx = data.frame.index
    return spot.SpotPrices.build(pd.Series([_eur(ts) * RATE for ts in idx], index=idx), idx)


@pytest.mark.parametrize("producers", [1, 2])
def test_the_gain_adds_up(producers):
    data = _data(producers=producers)
    sp = _prices(data)
    p = [4.2, 3.9, 5.1, 4.4, 4.0]
    f = [1.2] * producers
    c = spot.compare(data, sp, p, f, fee_mwh=300)
    assert c.priced
    assert c.gain == pytest.approx(c.sharing_value - c.spot_revenue)
    assert c.gain == pytest.approx(c.gain_shared + c.gain_unshared)
    pi = c.per_interval
    assert pi["gain_shared"].sum() == pytest.approx(c.gain_shared)
    assert pi["gain_unshared"].sum() == pytest.approx(c.gain_unshared)
    assert pi["spot_revenue"].sum() == pytest.approx(c.spot_revenue)
    # each producer supplied what the members got, interval by interval
    assert np.allclose(c.SU.sum(axis=1), c.SH.sum(axis=1))
    # at the break-even price of the shared energy the producer earns as on spot
    assert (c.break_even * c.supplied + c.at_feed_in) == pytest.approx(c.revenue)
    # the members' saving is their price times their shared energy
    assert c.at_supplier == pytest.approx(np.array(p) * core.per_destination(data)["shared"])


def test_fee_and_curtailment():
    data = _data()
    sp = _prices(data)
    p, f = [4.0] * 5, [1.0]
    free = spot.compare(data, sp, p, f)
    fee = spot.compare(data, sp, p, f, fee_mwh=250)
    assert free.spot_revenue - fee.spot_revenue == pytest.approx(0.25 * free.surplus_kwh)
    cut = spot.compare(data, sp, p, f, fee_mwh=250, curtail=True)
    assert (cut.value >= 0).all() and cut.spot_revenue >= fee.spot_revenue
    assert fee.negative_intervals > 0 and fee.negative_cost > 0      # Sundays at noon
    assert cut.negative_cost == 0 and cut.negative_kwh == fee.negative_kwh
    assert spot.compare(data, sp, p, f, 250) is fee                 # memoised


def test_missing_prices_leave_intervals_out_and_unknown_prices_give_nan():
    data = _data()
    sp = _prices(data)
    sp.price[:96] = np.nan
    c = spot.compare(data, sp, [4.0, None, 4.0, 4.0, 4.0], [1.0])
    assert not c.priced and np.isnan(c.gain) and np.isfinite(c.spot_revenue)
    assert c.SH[:96].sum() == 0 and sp.n_missing == 96
    assert spot.missing_surplus(data, sp) == pytest.approx(
        float(data.production.iloc[:96].sum()))
    m = spot.monthly(c)
    assert m["supplier"].isna().all() and m["mean_spot"].notna().all()


def test_hourly_and_quarter_intervals_are_counted():
    data = _data(days=20, start="2025-09-25")
    sp = spot.SpotPrices.build(spot.fetch_prices(date(2025, 9, 25), date(2025, 10, 14),
                                                 post=FakeOTE()), data.frame.index)
    assert sp.n_missing == 0 and sp.n_hourly == 6 * 96


def test_figures_views_and_table_build():
    data = _data()
    sp = _prices(data)
    names = {**{e: e[-3:] for e in data.dest_eans}, **{e: "PV" for e in data.source_eans},
             core.POOL: "pool"}
    enabled = set(data.dest_eans[:3])
    for prices in ([4.0] * 5, [None] * 5):
        c = spot.compare(data, sp, prices, [1.0])
        for fig in (fig_spot_waterfall(c, "cs"), fig_spot_members(c, data, names, enabled),
                    fig_spot_daily(c, sel_day="2025-10-05"),
                    fig_spot_intraday(c, "2025-10-05", lang="de"), fig_spot_monthly(c)):
            assert fig.layout.title.text
        views.spot_tiles(c, None, "en")
        views.spot_table(c, data, names, "cs", None, enabled)
        views.spot_info(sp, data, "cs")


# ---------------------------------------------------------------------------
# Job and tab
# ---------------------------------------------------------------------------


@pytest.fixture
def entry_key():
    data = _data(days=10, start="2025-10-02")
    key = store.put("t.csv", data)
    yield key
    store.drop(key)


class _NoSlots:
    def acquire(self, *a, **k):
        raise RuntimeError("the spot job took a CPU slot")

    def release(self):
        pass


def test_job_fetches_the_prices_without_a_cpu_slot(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "_SLOTS", _NoSlots())
    fake = FakeOTE()
    real = spot.fetch_for
    monkeypatch.setattr(spot, "fetch_for", lambda data, **kw: real(data, post=fake, **kw))
    job_id = jobs.start_spot(entry_key)
    job = jobs.JOBS[job_id]
    t0 = time.perf_counter()
    while not job.done and time.perf_counter() - t0 < 10:
        time.sleep(0.02)
    assert job.done and job.error is None and not job.error_key
    entry = store.get(entry_key)
    assert entry.spot is not None and entry.spot.n_missing == 0
    state = compute.poll_state(job_id, 0, "cs")
    assert state[2] == "progress done" and state[5] == 1


def test_an_unreachable_ote_is_shown_with_the_reason(entry_key, monkeypatch):
    def down(data, **kw):
        raise spot.SpotError("OTE: timed out")
    monkeypatch.setattr(spot, "fetch_for", down)
    job_id = jobs.start_spot(entry_key)
    job = jobs.JOBS[job_id]
    t0 = time.perf_counter()
    while not job.done and time.perf_counter() - t0 < 5:
        time.sleep(0.02)
    state = compute.poll_state(job_id, 0, "en")
    assert state[2] == "progress error" and "OTE: timed out" in state[4]


def test_the_tab_fetches_once_and_renders(entry_key, monkeypatch):
    started = []
    monkeypatch.setattr(jobs, "start_spot", lambda key: started.append(key) or "job")
    import dash
    from contextvars import copy_context
    from dash._callback_context import context_value
    from dash._utils import AttributeDict

    def run(fn, trigger, **kw):
        def inner():
            context_value.set(AttributeDict(triggered_inputs=[{"prop_id": trigger, "value": 1}]))
            return fn(**kw)
        return copy_context().run(inner)

    out = run(ui_spot.start_spot, "tabs.value", n=0, tab="spot", key=entry_key, job_id=None,
              lang="cs")
    assert started == [entry_key] and out["job"] == "job"
    with pytest.raises(dash.exceptions.PreventUpdate):     # on the sharing tab: nothing
        run(ui_spot.start_spot, "tabs.value", n=0, tab="sharing", key=entry_key, job_id=None,
            lang="cs")
    entry = store.get(entry_key)
    entry.spot = _prices(entry.data)
    with pytest.raises(dash.exceptions.PreventUpdate):     # prices there: no new fetch
        run(ui_spot.start_spot, "tabs.value", n=0, tab="spot", key=entry_key, job_id=None,
            lang="cs")
    out = ui_spot.render_spot(entry_key, 1, "spot", None, None, None, "1,1", "4,2", "200",
                              ["on"], "cs", "light", None, None, "2025-10-05")
    assert out["body"] == {} and out["tiles"] and out["table"]
    assert all(out[n].layout.title.text for n in ("waterfall", "members", "daily", "monthly"))
    fig, _style = ui_spot.spot_hourly("2025-10-05", entry_key, 1, "spot", None, None, None,
                                      "1,1", "4,2", "200", [], "en", "dark", None, None)
    assert len(fig.data) >= 4


def test_layout_has_the_tabs_and_the_spot_card():
    ids = set()

    def walk(c):
        if getattr(c, "id", None):
            ids.add(c.id)
        kids = getattr(c, "children", None)
        for k in kids if isinstance(kids, list) else [kids] if kids is not None else []:
            if hasattr(k, "to_plotly_json"):
                walk(k)
    walk(layout.layout())
    assert {"tabs", "tab-sharing", "tab-spot", "pane-sharing", "pane-spot", "spot-btn",
            "spot-fee", "spot-curtail", "spot-feed-in", "spot-price-default", "spot-table"} <= ids
    assert {layout.spot_fig_id(n) for n in layout.SPOT_FIGURES} <= ids


def test_the_export_has_a_spot_sheet_once_the_prices_are_there(entry_key):
    import io
    from openpyxl import load_workbook
    from ui import export as ui_export
    entry = store.get(entry_key)
    args = (entry_key, None, None, None, "cs", "", [])
    url = ui_export.summary_file(*args)
    content = store.get_file(url.split("/")[2]).content
    assert "Spot" not in load_workbook(io.BytesIO(content)).sheetnames
    entry.spot = _prices(entry.data)
    url = ui_export.summary_file(*args, None, ("1,2", "4,5", "250", ["on"]))
    wb = load_workbook(io.BytesIO(store.get_file(url.split("/")[2]).content))
    ws = wb["Spot"]
    values = {r[0]: r[1] for r in ws.iter_rows(values_only=True) if r and r[0]}
    c = ui_spot.comparison(entry, None, None, "1,2", "4,5", "250", ["on"])
    assert values["Sdílení − spot [Kč]"] == pytest.approx(c.gain)
    assert values["Poplatek obchodníka [Kč/MWh]"] == pytest.approx(250)
