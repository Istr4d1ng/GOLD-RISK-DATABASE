"""The cross-asset layer.

The database used to store "how does event X move gold". This module turns that
into a matrix: events and flashpoints map to DRIVERS, assets carry a signed
sensitivity to each driver, and the effect on any asset is derived rather than
hardcoded. One mechanism, applied across everything.
"""

import json
import math
import os
import statistics
from datetime import datetime

import config
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_PATH = os.path.join(ROOT, "data", "assets.json")
DRIVERS_PATH = os.path.join(ROOT, "data", "drivers.json")

_assets = _drivers = None


def load_assets():
    global _assets
    if _assets is None:
        with open(ASSETS_PATH, encoding="utf-8") as fh:
            _assets = json.load(fh)["assets"]
    return _assets


def load_drivers():
    global _drivers
    if _drivers is None:
        with open(DRIVERS_PATH, encoding="utf-8") as fh:
            _drivers = json.load(fh)["drivers"]
    return _drivers


def primary_key():
    for key, a in load_assets().items():
        if a.get("primary"):
            return key
    return "gold"


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def _pct(bars, back):
    if len(bars) <= back or not bars[-1 - back]["c"]:
        return None
    return round((bars[-1]["c"] - bars[-1 - back]["c"]) / bars[-1 - back]["c"] * 100, 2)


def fetch_bars(rng="1y"):
    """Daily bars for every tracked asset. Failures are reported, not fatal."""
    out, failed = {}, []
    for key, spec in load_assets().items():
        bars = None
        for symbol in [spec["symbol"]] + list(spec.get("alt") or []):
            try:
                bars = sources.fetch_chart(symbol, "1d", rng)
                if len(bars) > 20:
                    break
                bars = None
            except Exception:               # noqa: BLE001
                bars = None
        if bars:
            out[key] = bars
        else:
            failed.append(key)
    return out, failed


def snapshot(bars_by_asset):
    """Last level and recent change for each asset, in its own units."""
    rows = []
    for key, spec in load_assets().items():
        bars = bars_by_asset.get(key)
        if not bars:
            continue
        rows.append({
            "key": key, "name": spec["name"], "symbol": spec["symbol"],
            "unit": spec["unit"], "decimals": spec["decimals"],
            "last": round(bars[-1]["c"], spec["decimals"]),
            "change_pct": _pct(bars, 1),
            "change_5d_pct": _pct(bars, 5),
            "change_20d_pct": _pct(bars, 20),
            "primary": bool(spec.get("primary")),
        })
    return rows


# ---------------------------------------------------------------------------
# Correlations - because the relationships themselves move
# ---------------------------------------------------------------------------

def _returns(bars):
    out = {}
    for i in range(1, len(bars)):
        prev = bars[i - 1]["c"]
        if not prev:
            continue
        day = bars[i]["t"]
        key = day.date().isoformat() if hasattr(day, "date") else str(day)
        out[key] = (bars[i]["c"] - prev) / prev
    return out


def _corr(a, b):
    common = sorted(set(a) & set(b))
    if len(common) < 10:
        return None
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    try:
        return round(statistics.correlation(xs, ys), 2)
    except (statistics.StatisticsError, ValueError, ZeroDivisionError):
        return None


def correlations(bars_by_asset, window=60):
    """Rolling correlation matrix of daily returns, plus what it implies."""
    rets = {k: dict(list(_returns(v).items())[-window:])
            for k, v in bars_by_asset.items()}
    keys = [k for k in load_assets() if k in rets]
    matrix = {a: {b: (1.0 if a == b else _corr(rets[a], rets[b])) for b in keys}
              for a in keys}

    primary = primary_key()
    notable, regime = [], None
    if primary in matrix:
        row = {k: v for k, v in matrix[primary].items()
               if k != primary and v is not None}
        for k, v in sorted(row.items(), key=lambda kv: -abs(kv[1]))[:5]:
            notable.append({"asset": k, "name": load_assets()[k]["name"], "corr": v})
        eq = row.get("sp500")
        dollar = row.get("dollar")
        bits = []
        if dollar is not None:
            bits.append(
                f"Gold and the dollar are running at {dollar:+.2f}. "
                + ("That is the textbook inverse relationship, so dollar moves "
                   "are doing real work on the price."
                   if dollar <= -0.3 else
                   "The usual inverse link has weakened, which normally means "
                   "something other than the currency is setting gold - haven "
                   "flow or official buying."))
        if eq is not None:
            bits.append(
                f"Against the S&P it is {eq:+.2f}. "
                + ("Gold is trading WITH risk assets rather than against them, "
                   "so it is behaving as a liquidity asset right now, not a "
                   "hedge - do not rely on it to offset an equity drawdown "
                   "while that holds."
                   if eq >= 0.3 else
                   "It is behaving as a diversifier, which is the relationship "
                   "most people assume is permanent. It is not."
                   if eq <= -0.15 else
                   "Effectively uncorrelated with equities at the moment."))
        regime = " ".join(bits) or None

    return {"window": window, "assets": keys, "matrix": matrix,
            "notable": notable, "regime": regime}


# ---------------------------------------------------------------------------
# The derivation: driver -> every asset
# ---------------------------------------------------------------------------

STRENGTH = [(0.7, "strongly"), (0.4, "clearly"), (0.15, "mildly")]


def _word(v):
    for cut, word in STRENGTH:
        if abs(v) >= cut:
            return word
    return "barely"


def effect_of(driver, direction=1):
    """If this driver rises (or falls), what is each asset expected to do?

    This is derived from the sensitivity matrix, so adding an asset or revising
    one number updates every explanation on the site at once.
    """
    rows = []
    for key, spec in load_assets().items():
        s = spec["sensitivity"].get(driver, 0) * direction
        if abs(s) < 0.1:
            continue
        rows.append({"key": key, "name": spec["name"], "score": round(s, 2),
                     "direction": "up" if s > 0 else "down",
                     "strength": _word(s)})
    rows.sort(key=lambda r: -abs(r["score"]))
    return rows


def explain(drivers_moved):
    """Plain-English expected effect across the book.

    `drivers_moved` is {driver_key: +1 | -1}. Sensitivities are summed, which
    is crude but honest - and it makes conflicts visible rather than hiding
    them, which is the interesting case.
    """
    assets = load_assets()
    names = load_drivers()
    totals = {}
    for key, spec in assets.items():
        total, parts = 0.0, []
        for driver, direction in drivers_moved.items():
            s = spec["sensitivity"].get(driver, 0) * direction
            if abs(s) < 0.1:
                continue
            total += s
            parts.append({"driver": driver, "name": names[driver]["name"],
                          "score": round(s, 2)})
        if parts:
            conflict = (max(p["score"] for p in parts) > 0.25
                        and min(p["score"] for p in parts) < -0.25)
            totals[key] = {"name": spec["name"], "net": round(total, 2),
                           "parts": parts, "conflict": conflict,
                           "direction": "up" if total > 0 else "down",
                           "strength": _word(total)}
    return dict(sorted(totals.items(), key=lambda kv: -abs(kv[1]["net"])))
