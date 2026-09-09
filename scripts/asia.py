"""The Asia session, read at 06:30 UK.

By the time the morning job runs, Asia has done most of its trading and London
has not started. That gap is where the overnight story lives: what moved, what
moved it, and whether London is likely to extend it or fade it.

Honest framing throughout - Tokyo closes around 07:00 UK and Hong Kong around
09:00, so this is a session finishing, not one that has finished.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import assets as assetlib
import config
import sources


def _window(today, tz, now=None):
    """Asia session bounds in UTC: Tokyo's open to whenever this is running."""
    start_local = datetime.combine(today, datetime.min.time(), tzinfo=tz).replace(
        hour=config.ASIA_START_HOUR)
    end_local = now or datetime.now(tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _symbols(spec):
    out = [spec.get("overnight")] if spec.get("overnight") else []
    out.append(spec["symbol"])
    out.extend(spec.get("alt") or [])
    return [s for s in out if s]


def session_moves(today, tz, now=None):
    """Per-asset move and range across the Asia session so far."""
    start, end = _window(today, tz, now)
    rows, skipped = [], []
    for key, spec in assetlib.load_assets().items():
        bars = None
        used = None
        for symbol in _symbols(spec):
            try:
                got = sources.fetch_chart(symbol, "5m", "2d")
            except Exception:               # noqa: BLE001
                continue
            window = [b for b in got if start <= b["t"] <= end]
            if len(window) >= 6:
                bars, used = window, symbol
                break
        if not bars:
            skipped.append(key)
            continue
        bars.sort(key=lambda b: b["t"])
        open_, last = bars[0]["o"] or bars[0]["c"], bars[-1]["c"]
        hi = max(b["h"] for b in bars)
        lo = min(b["l"] for b in bars)
        if not open_:
            skipped.append(key)
            continue
        pos = ((last - lo) / (hi - lo) * 100) if hi > lo else 50
        rows.append({
            "key": key, "name": spec["name"], "symbol": used,
            "decimals": spec["decimals"],
            "open": round(open_, spec["decimals"]),
            "last": round(last, spec["decimals"]),
            "high": round(hi, spec["decimals"]),
            "low": round(lo, spec["decimals"]),
            "change_pct": round((last - open_) / open_ * 100, 2),
            "range_pct": round((hi - lo) / open_ * 100, 2),
            "position": round(pos),        # where in the overnight range it sits
            "primary": bool(spec.get("primary")),
        })
    rows.sort(key=lambda r: (not r["primary"], -abs(r["change_pct"])))
    return rows, skipped


def index_moves():
    """The Asian cash indices themselves."""
    out, failed = [], []
    for symbol, label, country in config.ASIA_INDICES:
        try:
            bars = sources.fetch_chart(symbol, "1d", "1mo")
            if len(bars) < 2 or not bars[-2]["c"]:
                raise RuntimeError("too few bars")
            last, prev = bars[-1]["c"], bars[-2]["c"]
            out.append({"symbol": symbol, "label": label, "country": country,
                        "last": round(last, 2),
                        "change_pct": round((last - prev) / prev * 100, 2)})
        except Exception:                   # noqa: BLE001
            failed.append(label)
    return out, failed


def overnight_events(raw_calendar, today, tz, now=None):
    """Asia-region releases in the window - the calendar the USD filter hides."""
    if not raw_calendar:
        return []
    start, end = _window(today, tz, now)
    start = start - timedelta(hours=config.ASIA_LOOKBACK_HOURS)
    out = []
    for e in raw_calendar:
        if e.get("country") not in config.ASIA_CURRENCIES:
            continue
        try:
            dt = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if not (start <= dt.astimezone(timezone.utc) <= end):
            continue
        impact = (e.get("impact") or "").strip()
        out.append({
            "title": e.get("title", "").strip(),
            "currency": e.get("country"),
            "local_time": dt.astimezone(tz).strftime("%H:%M"),
            "impact": impact,
            "folder": {"high": "RED", "medium": "ORANGE",
                       "low": "YELLOW"}.get(impact.lower(), "GREY"),
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
        })
    out.sort(key=lambda x: x["local_time"])
    return out


def read(rows, indices, events, gold_key="gold"):
    """What the overnight session is actually telling you."""
    if not rows and not indices:
        return None
    idx_avg = None
    if indices:
        vals = [i["change_pct"] for i in indices if i["change_pct"] is not None]
        idx_avg = round(sum(vals) / len(vals), 2) if vals else None

    bits = []
    if idx_avg is not None:
        if idx_avg <= -0.6:
            bits.append(f"Asian equities are broadly lower, averaging "
                        f"{idx_avg:+.2f}%. Risk came off overnight, which "
                        "normally gives gold a small bid into London.")
        elif idx_avg >= 0.6:
            bits.append(f"Asian equities are broadly higher, averaging "
                        f"{idx_avg:+.2f}%. A confident overnight tape usually "
                        "means haven demand is not the story today.")
        else:
            bits.append(f"Asian equities are mixed, averaging {idx_avg:+.2f}% - "
                        "no clear overnight lead for London.")

    gold = next((r for r in rows if r["key"] == gold_key), None)
    if gold:
        where = ("the top" if gold["position"] >= 70 else
                 "the bottom" if gold["position"] <= 30 else "the middle")
        bits.append(
            f"Gold moved {gold['change_pct']:+.2f}% overnight in a "
            f"{gold['range_pct']:.2f}% range, and comes into London near "
            f"{where} of it. "
            + ("Holding the highs into the European open more often extends "
               "than fades, though a thin Asian range is weak evidence either way."
               if gold["position"] >= 70 else
               "Sitting on the lows into the open leaves it vulnerable to a "
               "flush if London sells it."
               if gold["position"] <= 30 else
               "Mid-range is the least informative place it can be."))

    big = [e for e in events if e["folder"] in ("RED", "ORANGE")]
    if big:
        names = ", ".join(f"{e['currency']} {e['title']} at {e['local_time']}"
                          for e in big[:3])
        bits.append(f"Overnight releases worth knowing about: {names}.")
    elif events:
        bits.append(f"{len(events)} minor Asian releases overnight, none of them "
                    "the kind that reaches gold.")

    return " ".join(bits)


def summarise(raw_calendar, today, tz, now=None):
    rows, skipped = session_moves(today, tz, now)
    indices, failed = index_moves()
    events = overnight_events(raw_calendar, today, tz, now)
    cutoff = (now or datetime.now(tz)).strftime("%H:%M")
    return {
        "cutoff": cutoff,
        "moves": rows, "indices": indices, "events": events,
        "skipped": skipped, "failed": failed,
        "read": read(rows, indices, events),
        "caveat": (f"Measured from 00:00 UK to {cutoff}. Tokyo closes around "
                   "07:00 UK and Hong Kong around 09:00, so this is a session "
                   "finishing rather than one that has finished."),
    }
