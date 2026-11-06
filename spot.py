"""Spot market instead of sharing: the producers sell their whole surplus on the OTE
day-ahead market, the members buy all their electricity from their supplier.

Prices
------
The OTE public web service (SOAP, :data:`OTE_URL`, no registration) gives the Czech
day-ahead price:

* from the delivery day 1 Oct 2025 the 15-min price (``GetDamPricePeriodE``, PT15M) in
  EUR/MWh, converted to CZK with OTE's exchange rate of the day (``EurRate`` of
  ``GetDamIndexE``; the ČNB rate of the month as a fallback);
* before that the hourly price (``GetDamPriceE``) in CZK/MWh, the same for the four
  quarter-hours of the hour.

One call returns at most 31 days, so a report is fetched in chunks (a few in parallel).
Days that are over are kept in memory: the prices are public and never change. Period
``k`` of a day starts ``(k − 1) · 15 min`` (or hours) after midnight in absolute time, so
the 23- and 25-hour days come out right; the result is indexed by the local wall-clock
start, like the EDC report.

Comparison
----------
With sharing, the members' shared energy is worth their supplier price ``p`` (they do
not buy it) and the surplus nobody took the producer's feed-in price ``f``. On spot,
every kWh of the surplus earns the spot price ``s`` minus the trader's fee (or nothing,
when the producer curtails at a negative price). Per 15-min interval the group's gain
from sharing is

    G = Σ_j (p_j − v) · shared_j + Σ_i (f_i − v) · unshared_i,     v = s − fee,

and the producer's *break-even price* of the shared energy is what it must get per kWh
to earn as much as on spot: (spot revenue − f · unshared) / shared.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cached_property
from typing import Callable

import numpy as np
import pandas as pd

from edc_data import (
    SharingData, key_shared, key_unshared, memoized, shared_source,
)

OTE_URL = "https://www.ote-cr.cz/services/PublicDataService"
CNB_MONTH_URL = "https://api.cnb.cz/cnbapi/exrates/daily-currency-month"
_NS = "http://www.ote-cr.cz/schema/service/public"
TZ = "Europe/Prague"
#: first delivery day of the 15-min day-ahead market (before it: hourly prices)
QUARTER_FROM = date(2025, 10, 1)
#: the service returns at most this many days per call
MAX_DAYS = 31
TIMEOUT_S = 40
WORKERS = 4
USER_AGENT = "edc-report (+https://github.com/ottapav/edc-report)"

ProgressFn = Callable[[str, float], None]
Post = Callable[[bytes], bytes]
Get = Callable[[str], bytes]


class SpotError(Exception):
    """The prices could not be fetched or read."""


class Cancelled(SpotError):
    """The fetch was stopped (``cancelled()`` returned True)."""


def _noop(_phase: str, _frac: float) -> None:
    pass


# ---------------------------------------------------------------------------
# Talking to OTE (and ČNB)
# ---------------------------------------------------------------------------


def envelope(method: str, **params) -> bytes:
    """SOAP 1.1 request of the OTE public data service."""
    body = "".join(f"<pub:{k}>{v}</pub:{k}>" for k, v in params.items())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:pub="{_NS}"><soapenv:Header/><soapenv:Body>'
        f"<pub:{method}>{body}</pub:{method}></soapenv:Body></soapenv:Envelope>"
    ).encode("utf-8")


def http_post(body: bytes) -> bytes:
    req = urllib.request.Request(OTE_URL, data=body, method="POST", headers={
        "Content-Type": "text/xml; charset=utf-8", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:      # a SOAP fault comes back as HTTP 500
        content = exc.read()
        if content and b"Fault" in content:
            return content
        raise SpotError(f"OTE: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SpotError(f"OTE: {getattr(exc, 'reason', exc)}") from exc


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SpotError(f"ČNB: {getattr(exc, 'reason', exc)}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def items(xml: bytes, tag: str) -> list[dict[str, str]]:
    """The ``tag`` elements of a response as {child name: text}; a SOAP fault raises."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SpotError(f"OTE: unreadable response ({exc})") from exc
    for el in root.iter():
        if _local(el.tag) == "Fault":
            msg = next((c.text for c in el.iter() if _local(c.tag) == "faultstring"), None)
            raise SpotError(f"OTE: {(msg or 'SOAP fault').strip()}")
    return [{_local(c.tag): (c.text or "").strip() for c in el}
            for el in root.iter() if _local(el.tag) == tag]


def _starts(days, index, step_min: int) -> pd.DatetimeIndex:
    """Local wall-clock start of period ``index`` (1-based, ``step_min`` long) of each
    day: midnight in Prague plus the elapsed time (absolute, so DST days come out right)."""
    midnight = pd.DatetimeIndex(pd.to_datetime(list(days))).tz_localize(TZ)
    elapsed = pd.to_timedelta((np.asarray(index, dtype=np.int64) - 1) * step_min, unit="min")
    return (midnight + elapsed).tz_convert(TZ).tz_localize(None)


def _series(values, starts: pd.DatetimeIndex) -> pd.Series:
    """Sorted by start; the repeated hour of the 25-hour day is averaged."""
    s = pd.Series(np.asarray(values, dtype=float), index=starts)
    return s.groupby(level=0).mean().sort_index()


def parse_quarter_prices(xml: bytes) -> pd.Series:
    """``GetDamPricePeriodE`` (PT15M) → EUR/MWh by local start."""
    rows = [r for r in items(xml, "Item") if r.get("Price") not in (None, "")]
    if not rows:
        return pd.Series(dtype=float)
    starts = _starts([r["Date"] for r in rows], [int(r["PeriodIndex"]) for r in rows], 15)
    return _series([float(r["Price"]) for r in rows], starts)


def parse_hourly_prices(xml: bytes) -> pd.Series:
    """``GetDamPriceE`` (CZK) → CZK/MWh by local start of every quarter-hour."""
    rows = [r for r in items(xml, "Item") if r.get("Price") not in (None, "")]
    if not rows:
        return pd.Series(dtype=float)
    hours = np.array([int(r["Hour"]) for r in rows])
    days = [r["Date"] for r in rows]
    price = np.array([float(r["Price"]) for r in rows])
    # quarter q of hour h is period 4 (h − 1) + q + 1 of 15 min
    parts = [_series(price, _starts(days, 4 * (hours - 1) + q + 1, 15)) for q in range(4)]
    return pd.concat(parts).groupby(level=0).mean().sort_index()


def parse_eur_rates(xml: bytes) -> pd.Series:
    """``GetDamIndexE`` → CZK per EUR by delivery day."""
    out = {}
    for r in items(xml, "DamIndex"):
        try:
            out[pd.Timestamp(r["Date"])] = float(r["EurRate"])
        except (KeyError, ValueError):
            continue
    return pd.Series(out, dtype=float).sort_index()


def parse_cnb_month(content: bytes) -> pd.Series:
    """ČNB ``daily-currency-month`` (EUR) → CZK per EUR by day."""
    try:
        rates = json.loads(content.decode("utf-8")).get("rates", [])
    except (ValueError, AttributeError) as exc:
        raise SpotError("ČNB: unreadable response") from exc
    out = {pd.Timestamp(r["validFor"]): float(r["rate"]) / float(r.get("amount") or 1)
           for r in rates if r.get("validFor") and r.get("rate") is not None}
    return pd.Series(out, dtype=float).sort_index()


# ---------------------------------------------------------------------------
# A period: chunks, cache, fetch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    kind: str           # "quarter" (15-min, EUR) or "hourly" (CZK)
    first: date
    last: date

    def calls(self) -> int:
        return 2 if self.kind == "quarter" else 1


def chunks(days: list[date]) -> list[Chunk]:
    """Consecutive runs of ``days`` cut at the start of the 15-min market and into at
    most :data:`MAX_DAYS` days."""
    out: list[Chunk] = []
    for d in sorted(set(days)):
        kind = "quarter" if d >= QUARTER_FROM else "hourly"
        last = out[-1] if out else None
        if (last is not None and last.kind == kind and d == last.last + timedelta(days=1)
                and (d - last.first).days < MAX_DAYS):
            out[-1] = Chunk(kind, last.first, d)
        else:
            out.append(Chunk(kind, d, d))
    return out


#: CZK/MWh per 15 min of the days that are over, by day (public data: shared by all users)
_CACHE: "OrderedDict[date, pd.Series]" = OrderedDict()
_CACHE_DAYS = 4 * 366
_LOCK = threading.Lock()


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


def _today() -> date:
    return pd.Timestamp.now(tz=TZ).date()


def _rates_for(days: pd.DatetimeIndex, ote: pd.Series, get: Get) -> pd.Series:
    """CZK per EUR for ``days``: OTE's rate of the day; days it lacks take the ČNB rate,
    and a day without any (weekend at ČNB) the last rate before it."""
    rates = ote.reindex(days)
    if rates.isna().any():
        months = sorted({d.strftime("%Y-%m") for d in days[rates.isna()]})
        cnb = []
        for m in months:
            try:
                q = urllib.parse.urlencode({"currency": "EUR", "yearMonth": m})
                cnb.append(parse_cnb_month(get(f"{CNB_MONTH_URL}?{q}")))
            except SpotError:
                continue
        known = pd.concat([ote, *cnb]).groupby(level=0).first().sort_index()
        if not known.empty:
            full = known.reindex(known.index.union(days)).sort_index().ffill().bfill()
            rates = rates.fillna(full.reindex(days))
    if rates.isna().any():
        raise SpotError("no EUR/CZK exchange rate for "
                        + ", ".join(d.strftime("%d.%m.%Y") for d in days[rates.isna()][:3]))
    return rates


def _fetch_chunk(ch: Chunk, post: Post, get: Get) -> pd.Series:
    """CZK/MWh per 15 min for the days of ``ch``."""
    a, b = ch.first.isoformat(), ch.last.isoformat()
    if ch.kind == "hourly":
        return parse_hourly_prices(post(envelope("GetDamPriceE", StartDate=a, EndDate=b,
                                                 InEur="false")))
    eur = parse_quarter_prices(post(envelope("GetDamPricePeriodE", StartDate=a, EndDate=b,
                                             PeriodResolution="PT15M")))
    if eur.empty:
        return eur
    try:
        ote = parse_eur_rates(post(envelope("GetDamIndexE", StartDate=a, EndDate=b)))
    except SpotError:
        ote = pd.Series(dtype=float)
    days = eur.index.normalize()
    return eur * _rates_for(days.unique(), ote, get).reindex(days).to_numpy()


def fetch_prices(first: date, last: date, *, progress: ProgressFn = _noop,
                 cancelled: Callable[[], bool] = lambda: False,
                 post: Post | None = None, get: Get | None = None) -> pd.Series:
    """Day-ahead prices in CZK/MWh per 15 min (local start) from ``first`` to ``last``.
    Days that are over come from the cache when fetched before. ``post`` / ``get`` talk
    to OTE / ČNB (default: :func:`http_post`, :func:`http_get`)."""
    post, get = post or http_post, get or http_get
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    with _LOCK:
        have = {d: _CACHE[d] for d in days if d in _CACHE}
    todo = chunks([d for d in days if d not in have])
    total = sum(c.calls() for c in todo) or 1
    done = 0
    progress("spot", 0.0)
    parts = list(have.values())
    if todo:
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(todo))) as pool:
            futures = {pool.submit(_fetch_chunk, c, post, get): c for c in todo}
            try:
                for fut in as_completed(futures):
                    if cancelled():
                        raise Cancelled()
                    part = fut.result()
                    done += futures[fut].calls()
                    progress("spot", done / total)
                    parts.append(part)
                    _remember(part)
            finally:
                for f in futures:
                    f.cancel()
    progress("spot", 1.0)
    if not parts:
        return pd.Series(dtype=float)
    out = pd.concat(parts)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out


def _remember(prices: pd.Series) -> None:
    """Cache the complete days that are over."""
    if prices.empty:
        return
    today = _today()
    with _LOCK:
        for day, part in prices.groupby(prices.index.normalize()):
            d = day.date()
            if d < today and len(part) >= 92:            # 92 / 96 / 100 quarter-hours
                _CACHE[d] = part
                _CACHE.move_to_end(d)
        while len(_CACHE) > _CACHE_DAYS:
            _CACHE.popitem(last=False)


# ---------------------------------------------------------------------------
# Prices of a report
# ---------------------------------------------------------------------------


@dataclass(eq=False)                # hashed by identity: a key of the memoised comparison
class SpotPrices:
    """Spot price of every 15-min interval of a report."""

    price: np.ndarray               # Kč/kWh; NaN where OTE has no price
    index: pd.DatetimeIndex         # the report's intervals
    n_hourly: int = 0               # intervals priced by the hourly market (before 10/2025)

    @classmethod
    def build(cls, czk_mwh: pd.Series, index: pd.DatetimeIndex) -> "SpotPrices":
        price = czk_mwh.reindex(index).to_numpy(dtype=float) / 1000
        hourly = int(((index < pd.Timestamp(QUARTER_FROM)) & ~np.isnan(price)).sum())
        return cls(price=price, index=index, n_hourly=hourly)

    @property
    def n_missing(self) -> int:
        return int(np.isnan(self.price).sum())

    @property
    def series(self) -> pd.Series:
        return pd.Series(self.price, index=self.index)


def fetch_for(data: SharingData, **kw) -> SpotPrices:
    """The spot prices of the report's period."""
    idx = data.frame.index
    first, last = idx.min().date(), idx.max().date()
    return SpotPrices.build(fetch_prices(first, last, **kw), idx)


# ---------------------------------------------------------------------------
# Sharing vs spot
# ---------------------------------------------------------------------------


def _nan(values) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)


@dataclass
class Comparison:
    """Sharing as in the report vs selling the whole surplus on spot (Kč, kWh). Intervals
    without a spot price are left out of both."""

    index: pd.DatetimeIndex
    spot: np.ndarray                # Kč/kWh (NaN unknown)
    value: np.ndarray               # Kč/kWh the producer gets for a kWh on spot (0 unknown)
    valid: np.ndarray               # interval has a spot price
    fee: float                      # Kč/kWh
    curtail: bool
    prices: np.ndarray              # supplier price per member (NaN not entered)
    feed_ins: np.ndarray            # feed-in price per producer (NaN not entered)
    SH: np.ndarray                  # (T, n) kWh shared to each member
    UN: np.ndarray                  # (T, np) kWh unshared per producer
    SU: np.ndarray                  # (T, np) kWh each producer shared

    # --- per member ---
    @cached_property
    def shared(self) -> np.ndarray:
        return self.SH.sum(axis=0)

    @cached_property
    def at_supplier(self) -> np.ndarray:
        """Kč: what the members did not have to buy from their supplier."""
        return self.prices * self.shared

    @cached_property
    def shared_at_spot(self) -> np.ndarray:
        """Kč: the members' shared energy sold on spot instead."""
        return self.value @ self.SH

    @property
    def member_gain(self) -> np.ndarray:
        return self.at_supplier - self.shared_at_spot

    # --- per producer ---
    @cached_property
    def unshared(self) -> np.ndarray:
        return self.UN.sum(axis=0)

    @cached_property
    def supplied(self) -> np.ndarray:
        return self.SU.sum(axis=0)

    @cached_property
    def at_feed_in(self) -> np.ndarray:
        return self.feed_ins * self.unshared

    @cached_property
    def unshared_at_spot(self) -> np.ndarray:
        return self.value @ self.UN

    @cached_property
    def revenue(self) -> np.ndarray:
        """Kč each producer would get on spot for its whole surplus."""
        return self.value @ (self.SU + self.UN)

    @property
    def unshared_gain(self) -> np.ndarray:
        return self.at_feed_in - self.unshared_at_spot

    @property
    def break_even(self) -> np.ndarray:
        """Kč/kWh of shared electricity at which each producer earns as much as on spot."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.supplied > 0,
                            (self.revenue - self.at_feed_in) / self.supplied, np.nan)

    # --- the group ---
    @property
    def spot_revenue(self) -> float:
        return float(self.revenue.sum())

    @property
    def sharing_value(self) -> float:
        """Kč: members' savings + feed-in revenue of the unshared surplus."""
        return float(self.at_supplier.sum() + self.at_feed_in.sum())

    @property
    def gain(self) -> float:
        return self.sharing_value - self.spot_revenue

    @property
    def gain_shared(self) -> float:
        return float(self.member_gain.sum())

    @property
    def gain_unshared(self) -> float:
        return float(self.unshared_gain.sum())

    @property
    def surplus_kwh(self) -> float:
        return float(self.supplied.sum() + self.unshared.sum())

    @property
    def priced(self) -> bool:
        """Every supplier and feed-in price is known (else the sharing side is NaN)."""
        return not (np.isnan(self.prices).any() or np.isnan(self.feed_ins).any())

    def _avg(self, num: float, den: float) -> float:
        return num / den if den > 0 else float("nan")

    @property
    def mean_spot(self) -> float:
        """Time average of the spot price over the intervals with a price."""
        return float(np.nanmean(self.spot)) if self.valid.any() else float("nan")

    @property
    def capture_shared(self) -> float:
        """Kč/kWh the shared energy would have got on spot."""
        return self._avg(float(self.shared_at_spot.sum()), float(self.shared.sum()))

    @property
    def capture_unshared(self) -> float:
        return self._avg(float(self.unshared_at_spot.sum()), float(self.unshared.sum()))

    @property
    def capture(self) -> float:
        """Kč/kWh the whole surplus would have got on spot (fee and curtailment included)."""
        return self._avg(self.spot_revenue, self.surplus_kwh)

    @property
    def supplier_avg(self) -> float:
        """Supplier price weighted by the shared energy."""
        return self._avg(float(self.at_supplier.sum()), float(self.shared.sum()))

    @property
    def feed_in_avg(self) -> float:
        return self._avg(float(self.at_feed_in.sum()), float(self.unshared.sum()))

    @property
    def break_even_avg(self) -> float:
        return self._avg(self.spot_revenue - float(self.at_feed_in.sum()),
                         float(self.supplied.sum()))

    # --- negative prices ---
    @cached_property
    def _negative(self) -> np.ndarray:
        """Intervals in which a sold kWh would cost money (spot price below the fee)."""
        surplus = self.SU.sum(axis=1) + self.UN.sum(axis=1)
        with np.errstate(invalid="ignore"):
            return self.valid & (self.spot - self.fee < 0) & (surplus > 0)

    @property
    def negative_intervals(self) -> int:
        return int(self._negative.sum())

    @property
    def negative_kwh(self) -> float:
        return float((self.SU.sum(axis=1) + self.UN.sum(axis=1))[self._negative].sum())

    @property
    def negative_cost(self) -> float:
        """Kč the surplus of those intervals costs on spot (0 when curtailed)."""
        if self.curtail:
            return 0.0
        surplus = self.SU.sum(axis=1) + self.UN.sum(axis=1)
        return float(-((self.spot - self.fee)[self._negative] * surplus[self._negative]).sum())

    # --- per 15 min (the group) ---
    @cached_property
    def per_interval(self) -> pd.DataFrame:
        """Kč per 15 min: the gain on the shared energy and on the unshared surplus, the
        spot revenue; kWh shared and unshared; the spot price (Kč/kWh)."""
        v = self.value[:, None]
        return pd.DataFrame({
            "gain_shared": ((self.prices[None, :] - v) * self.SH).sum(axis=1),
            "gain_unshared": ((self.feed_ins[None, :] - v) * self.UN).sum(axis=1),
            "spot_revenue": self.value * (self.SU.sum(axis=1) + self.UN.sum(axis=1)),
            "shared": self.SH.sum(axis=1),
            "unshared": self.UN.sum(axis=1),
            "spot": self.spot,
        }, index=self.index)


def _supplied(data: SharingData, SH_total: np.ndarray, UN: np.ndarray) -> np.ndarray:
    """(T, np) kWh each producer shared: its production minus its unshared surplus,
    scaled per interval to what the members received (they differ by the report's
    rounding); one producer supplies all of it."""
    T, npr = UN.shape
    if npr == 1:
        return SH_total[:, None].copy()
    P = np.stack([data.productions[e].to_numpy(dtype=float) for e in data.source_eans], axis=1)
    w = np.clip(np.nan_to_num(P) - UN, 0, None)
    tot = w.sum(axis=1, keepdims=True)
    share = np.where(tot > 0, w / np.where(tot > 0, tot, 1), 1.0 / npr)
    return share * SH_total[:, None]


def compare(data: SharingData, spot: SpotPrices, prices, feed_ins, fee_mwh: float = 0.0,
            curtail: bool = False) -> Comparison:
    """Sharing in the report vs the whole surplus on spot. ``prices`` (supplier, per
    member) and ``feed_ins`` (per producer) in Kč/kWh, None = not entered; ``fee_mwh``
    the trader's fee in Kč/MWh; ``curtail``: the producer does not sell when a kWh
    would cost money."""
    return _compare(data, spot, tuple(prices), tuple(feed_ins), float(fee_mwh or 0.0),
                    bool(curtail))


@memoized
def _compare(data: SharingData, spot: SpotPrices, prices: tuple, feed_ins: tuple,
             fee_mwh: float, curtail: bool) -> Comparison:
    if data.fmt != "all":
        raise ValueError("The spot comparison needs an all report.")
    frame = data.frame
    src = shared_source(data)
    s = np.asarray(spot.price, dtype=float)
    if len(s) != len(frame):
        s = pd.Series(s, index=spot.index).reindex(frame.index).to_numpy(dtype=float)
    valid = ~np.isnan(s)
    fee = fee_mwh / 1000
    value = np.where(valid, s - fee, 0.0)
    if curtail:
        value = np.clip(value, 0, None)
    keep = valid[:, None]
    SH = frame[[key_shared(src, e) for e in data.dest_eans]].to_numpy(dtype=float)
    UN = frame[[key_unshared(e) for e in data.source_eans]].to_numpy(dtype=float)
    SH, UN = np.nan_to_num(SH) * keep, np.nan_to_num(UN) * keep
    SU = _supplied(data, SH.sum(axis=1), UN)
    return Comparison(index=frame.index, spot=s, value=value, valid=valid, fee=fee,
                      curtail=curtail, prices=_nan(prices), feed_ins=_nan(feed_ins),
                      SH=SH, UN=UN, SU=SU)


def missing_surplus(data: SharingData, spot: SpotPrices) -> float:
    """kWh of surplus in intervals without a spot price (not compared)."""
    gap = np.isnan(np.asarray(spot.price, dtype=float))
    if not gap.any() or data.production is None:
        return 0.0
    return float(np.nan_to_num(data.production.to_numpy(dtype=float))[gap].sum())


def monthly(cmp: Comparison) -> pd.DataFrame:
    """Per month (Kč/kWh): the average spot price, what the surplus got on spot (energy
    weighted), the supplier price of the shared energy and the feed-in price."""
    pi = cmp.per_interval
    surplus = pi["shared"] + pi["unshared"]
    month = pi.index.to_period("M")
    g = pd.DataFrame({
        "spot": pi["spot"], "rev": pi["spot_revenue"], "surplus": surplus,
        "sup": cmp.SH @ np.nan_to_num(cmp.prices), "sh": pi["shared"],
        "fin": cmp.UN @ np.nan_to_num(cmp.feed_ins), "un": pi["unshared"],
    }).groupby(month)
    out = pd.DataFrame({
        "mean_spot": g["spot"].mean(),
        "capture": g["rev"].sum() / g["surplus"].sum().replace(0, np.nan),
        "supplier": g["sup"].sum() / g["sh"].sum().replace(0, np.nan),
        "feed_in": g["fin"].sum() / g["un"].sum().replace(0, np.nan),
        "surplus": g["surplus"].sum(),
    })
    if np.isnan(cmp.prices).any():
        out["supplier"] = np.nan
    if np.isnan(cmp.feed_ins).any():
        out["feed_in"] = np.nan
    return out
