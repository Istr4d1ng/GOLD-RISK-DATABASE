"""Market context beyond the calendar: implied volatility, gold's drivers,
and speculative positioning. All keyless, all free."""

import csv
import gzip
import io
import json
import math
from datetime import date, datetime, timedelta, timezone

import config
import health
import sources


# ---------------------------------------------------------------------------
# FRED - two endpoints, because the CSV one has been unreliable
# ---------------------------------------------------------------------------

def _parse_fred_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    out = []
    for r in rows[1:]:
        if len(r) < 2 or r[1] in ("", "."):
            continue
        try:
            out.append((r[0][:10], float(r[1])))
        except ValueError:
            continue
    return out


def _parse_fred_txt(text):
    """The .txt endpoint is a header block, then 'DATE  VALUE' lines."""
    out = []
    started = False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if not started:
            if parts[0].upper().startswith("DATE"):
                started = True
            continue
        if parts[1] in (".", "NA"):
            continue
        try:
            datetime.strptime(parts[0], "%Y-%m-%d")
            out.append((parts[0], float(parts[1])))
        except ValueError:
            continue
    return out


def _parse_dbnomics(raw):
    """DBnomics mirrors FRED without a key. Tolerant of shape changes."""
    data = json.loads(raw.decode("utf-8", "replace"))
    docs = ((data.get("series") or {}).get("docs")) or []
    if not docs:
        return []
    doc = docs[0]
    periods = doc.get("period") or doc.get("original_period") or []
    values = doc.get("value") or []
    out = []
    for d, v in zip(periods, values):
        if v is None or v == "NA":
            continue
        try:
            out.append((str(d)[:10], float(v)))
        except (TypeError, ValueError):
            continue
    return out


def fred_series(series_id, years=3):
    """Observations for a FRED series, trying every keyless endpoint."""
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    errors = []
    for template in config.FRED_SOURCES:
        url = template.format(sid=series_id, start=start)
        try:
            raw = sources._get(url, timeout=25, retries=2)
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8-sig", "replace")
            obs = _parse_fred_csv(text) if "," in text.split("\n")[0] \
                else _parse_fred_txt(text)
            if not obs:
                obs = _parse_fred_txt(text) or _parse_fred_csv(text)
            if obs:
                return obs
            errors.append(f"{url.split('?')[0]}: no rows")
        except Exception as exc:            # noqa: BLE001
            errors.append(f"{url.split('?')[0]}: {exc}")
    try:
        obs = _parse_dbnomics(sources._get(
            config.DBNOMICS_URL.format(sid=series_id), timeout=25, retries=2))
        if obs:
            cutoff = (date.today() - timedelta(days=365 * years)).isoformat()
            return [o for o in obs if o[0] >= cutoff] or obs
        errors.append("dbnomics: no rows")
    except Exception as exc:                # noqa: BLE001
        errors.append(f"dbnomics: {exc}")
    raise RuntimeError("; ".join(errors))


# ---------------------------------------------------------------------------
# Implied volatility - what the options market expects, not what happened
# ---------------------------------------------------------------------------

def implied_vol(spot):
    """GVZ-derived expected daily move for gold, plus where GVZ sits in range."""
    bars = None
    for sym in config.GVZ_SYMBOLS:
        try:
            bars = sources.fetch_chart(sym, "1d", "1y")
            if len(bars) > 30:
                break
        except Exception:                   # noqa: BLE001
            bars = None
    if not bars:
        raise RuntimeError("no GVZ data")

    level = bars[-1]["c"]
    closes = [b["c"] for b in bars]
    below = sum(1 for c in closes if c < level)
    pct_rank = round(100 * below / len(closes))

    daily_pct = level / 100 / math.sqrt(252)
    out = {
        "gvz": round(level, 2),
        "percentile_1y": pct_rank,
        "daily_move_pct": round(daily_pct * 100, 2),
        "year_low": round(min(closes), 2),
        "year_high": round(max(closes), 2),
    }
    if spot:
        # A one-standard-deviation day; the ~68% containment band.
        out["daily_move_usd"] = round(spot * daily_pct, 1)
        out["one_sd_range_usd"] = round(spot * daily_pct * 2, 1)
    return out


# ---------------------------------------------------------------------------
# Drivers - is gold moving on rates, on the dollar, or on fear?
# ---------------------------------------------------------------------------

def _change(bars, days=1):
    if len(bars) <= days:
        return None
    prev = bars[-1 - days]["c"]
    if not prev:
        return None
    return (bars[-1]["c"] - prev) / prev * 100


def drivers():
    out = {}
    for key, symbol, label in config.DRIVER_SYMBOLS:
        try:
            bars = sources.fetch_chart(symbol, "1d", "3mo")
            out[key] = {"label": label, "last": round(bars[-1]["c"], 3),
                        "change_pct": round(_change(bars) or 0, 2),
                        "change_5d_pct": round(_change(bars, 5) or 0, 2)}
        except Exception as exc:            # noqa: BLE001
            print(f"[market] driver {symbol} unavailable: {exc}")
    try:
        obs = fred_series(config.REAL_YIELD_SERIES, years=1)
        last = obs[-1][1]
        week = obs[-6][1] if len(obs) > 6 else obs[0][1]
        out["REAL10Y"] = {"label": "US 10-year real yield (TIPS)",
                          "last": round(last, 2),
                          "change_pct": None,
                          "change_5d_bp": round((last - week) * 100, 1),
                          "as_of": obs[-1][0]}
    except Exception as exc:                # noqa: BLE001
        print(f"[market] real yield unavailable: {exc}")
    return out


def attribute(gold_change_pct, drv):
    """Name the channel gold's last move came through. Descriptive, not a call."""
    if gold_change_pct is None or not drv:
        return None
    real = drv.get("REAL10Y", {}).get("change_5d_bp")
    dxy = drv.get("DXY", {}).get("change_pct")
    ten = drv.get("US10Y", {}).get("change_pct")
    up = gold_change_pct > 0

    if real is not None and abs(real) >= 5 and ((real < 0) == up):
        return {"channel": "real yields",
                "note": ("Gold moved with real yields going the other way - the "
                         "rate channel. This is the version that tends to persist, "
                         "because it reflects a changed policy path rather than a "
                         "mood.")}
    if dxy is not None and abs(dxy) >= 0.25 and ((dxy < 0) == up):
        return {"channel": "the dollar",
                "note": ("Gold moved inversely to the dollar with yields quiet - a "
                         "currency effect. Usually mean-reverting unless the dollar "
                         "move itself has a policy cause behind it.")}
    if dxy is not None and up and dxy > 0.1:
        return {"channel": "haven demand",
                "note": ("Gold and the dollar rose together, which normally means "
                         "flight-to-safety rather than rates. Haven bids historically "
                         "fade within days unless the underlying event changes the "
                         "policy outlook.")}
    if ten is not None and abs(ten) < 0.5 and (dxy is None or abs(dxy) < 0.15):
        return {"channel": "idiosyncratic",
                "note": ("Neither yields nor the dollar explain this one - look to "
                         "flows, positioning or physical demand.")}
    return {"channel": "mixed",
            "note": "No single driver dominates; the move has more than one cause."}


# ---------------------------------------------------------------------------
# Positioning - crowding is the fuel, the event is only the match
# ---------------------------------------------------------------------------

def _num(rec, *names):
    for n in names:
        v = rec.get(n)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def cot_gold():
    """Managed-money net length in COMEX gold, with two years of context."""
    url = config.COT_URL.format(code=config.COT_GOLD_CODE, limit=config.COT_HISTORY)
    raw = sources._get(url, timeout=30, retries=2)
    data = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("empty COT response")

    series = []
    for rec in data:
        long_ = _num(rec, "m_money_positions_long_all", "m_money_positions_long")
        short = _num(rec, "m_money_positions_short_all", "m_money_positions_short")
        oi = _num(rec, "open_interest_all", "open_interest")
        when = rec.get("report_date_as_yyyy_mm_dd") or rec.get("report_date")
        if long_ is None or short is None or not when:
            continue
        net = long_ - short
        series.append({"date": str(when)[:10], "long": long_, "short": short,
                       "net": net, "oi": oi,
                       "net_pct_oi": round(net / oi * 100, 1) if oi else None})
    if not series:
        raise RuntimeError("COT response had no managed-money fields")

    series.sort(key=lambda r: r["date"])
    latest = series[-1]
    nets = [r["net"] for r in series]
    below = sum(1 for n in nets if n < latest["net"])
    pct_rank = round(100 * below / len(nets))
    change_4w = (latest["net"] - series[-5]["net"]) if len(series) > 5 else None

    if pct_rank >= 85:
        read = ("Managed money is crowded long. Crowded books cut both ways, but "
                "they make downside surprises faster and deeper than upside ones, "
                "because the sellers are already in the trade.")
    elif pct_rank <= 15:
        read = ("Speculative length is unusually low. Less fuel for a flush, and "
                "more room for a squeeze if a print goes gold's way.")
    else:
        read = ("Positioning is unremarkable, so events should move gold roughly "
                "in line with their own weight rather than being amplified.")

    return {
        "as_of": latest["date"],
        "net": int(latest["net"]),
        "long": int(latest["long"]),
        "short": int(latest["short"]),
        "net_pct_oi": latest["net_pct_oi"],
        "percentile_2y": pct_rank,
        "change_4w": int(change_4w) if change_4w is not None else None,
        "samples": len(series),
        "read": read,
        "crowded": pct_rank >= 85 or pct_rank <= 15,
        "history": [{"date": r["date"], "net": int(r["net"])} for r in series[-26:]],
    }


# ---------------------------------------------------------------------------
# Market map - indices and sector leaders, read for what they say about gold
# ---------------------------------------------------------------------------

def _quote(symbol, label, **extra):
    bars = sources.fetch_chart(symbol, "1d", "1mo")
    if len(bars) < 2:
        raise RuntimeError(f"{symbol}: too few bars")
    last, prev = bars[-1]["c"], bars[-2]["c"]
    out = {"symbol": symbol, "label": label, "last": round(last, 2),
           "change_pct": round((last - prev) / prev * 100, 2) if prev else None}
    if len(bars) > 5 and bars[-6]["c"]:
        out["change_5d_pct"] = round((last - bars[-6]["c"]) / bars[-6]["c"] * 100, 2)
    out.update(extra)
    return out


def _mean(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def market_map(gold_change_pct=None):
    """Indices plus one liquid name per sector, and what they imply for gold.

    Quotes on their own would be decoration here. What earns their place is the
    read: whether the tape is risk-on or risk-off, whether the oil channel is
    live, and whether the miners confirm gold's move or disagree with it.
    """
    indices, stocks, failed = [], [], []
    for symbol, label, kind in config.INDICES:
        try:
            indices.append(_quote(symbol, label, kind=kind))
        except Exception as exc:            # noqa: BLE001
            failed.append(f"{symbol} ({exc.__class__.__name__})")
    for symbol, label, sector, kind in config.SECTOR_STOCKS:
        try:
            stocks.append(_quote(symbol, label, sector=sector, kind=kind))
        except Exception as exc:            # noqa: BLE001
            failed.append(f"{symbol} ({exc.__class__.__name__})")
    if not indices and not stocks:
        raise RuntimeError("no market map data: " + "; ".join(failed[:4]))

    by_kind = {}
    for row in stocks:
        by_kind.setdefault(row["kind"], []).append(row["change_pct"])

    cyclical = _mean(by_kind.get("cyclical", []))
    defensive = _mean(by_kind.get("defensive", []))
    miners = _mean(by_kind.get("miner", []))
    energy = _mean(by_kind.get("energy", []))
    spread = (round(cyclical - defensive, 2)
              if cyclical is not None and defensive is not None else None)
    vix = next((i for i in indices if i["symbol"] == "^VIX"), None)
    small = next((i for i in indices if i["symbol"] == "^RUT"), None)

    # --- risk appetite -----------------------------------------------------
    appetite, appetite_note = "mixed", (
        "No clear rotation between cyclicals and defensives, so equities are "
        "not saying much about gold today.")
    if spread is not None:
        vix_up = (vix or {}).get("change_pct", 0) or 0
        if spread <= -0.5 or (vix_up > 5 and spread < 0):
            appetite = "risk-off"
            appetite_note = (
                f"Defensives are outperforming cyclicals by {abs(spread):.2f}pp"
                + (f" with the VIX up {vix_up:.1f}%" if vix_up > 0 else "")
                + ". Risk-off tapes are usually gold-supportive, though the "
                  "dollar competes for the same haven flow.")
        elif spread >= 0.5:
            appetite = "risk-on"
            appetite_note = (
                f"Cyclicals are leading defensives by {spread:.2f}pp. A "
                "confident tape is a mild headwind for gold, since haven demand "
                "is the part of the bid that fades first.")
    if small and small.get("change_pct") is not None and appetite == "mixed":
        if small["change_pct"] <= -1.0:
            appetite, appetite_note = "risk-off", (
                f"Small caps are down {abs(small['change_pct']):.2f}% while the "
                "large-cap indices hold up - the classic early sign of risk "
                "coming off, and usually gold-supportive.")

    # --- miners: confirmation or divergence --------------------------------
    miner_read = None
    if miners is not None and gold_change_pct is not None:
        if abs(gold_change_pct) < 0.3:
            miner_read = (f"Miners {miners:+.2f}% on a flat day for gold - "
                          "little to read into.")
        elif (miners > 0) == (gold_change_pct > 0):
            lev = abs(miners) / abs(gold_change_pct)
            # A ratio computed off a tiny denominator is arithmetic, not insight.
            lev_txt = "more than 5x" if lev > 5 else f"about {lev:.1f}x"
            miner_read = (
                f"Miners {miners:+.2f}% against gold {gold_change_pct:+.2f}% - "
                f"{lev_txt} leverage, confirming the move. Miners generally "
                "amplify gold, so this is the normal relationship.")
        else:
            miner_read = (
                f"Miners {miners:+.2f}% while gold went {gold_change_pct:+.2f}% "
                "- a divergence. Worth noting rather than acting on: equity "
                "factors move miners too, so this is not automatically a signal "
                "about gold.")

    return {
        "indices": indices, "stocks": stocks,
        "sectors": sorted({s["sector"] for s in stocks}),
        "cyclical_avg": cyclical, "defensive_avg": defensive,
        "miner_avg": miners, "energy_avg": energy, "spread": spread,
        "appetite": appetite, "appetite_note": appetite_note,
        "miner_read": miner_read,
        "failed": failed,
    }
