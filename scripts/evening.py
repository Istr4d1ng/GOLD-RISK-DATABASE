"""Evening job: measure what gold actually did around each event and log it.

This is the part that turns a daily briefing into a database. Every run adds
rows to data/events.csv, and the morning job reads those rows back as base
rates, so the model gets better the longer it runs.
"""

import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import risk as riskmod
import sources


def bar_at(bars, target, tolerance_min=20):
    """Closest bar at or after `target`, within tolerance. None if too far."""
    best, best_gap = None, None
    for b in bars:
        gap = (b["t"] - target).total_seconds()
        if gap < -300:
            continue
        if best_gap is None or abs(gap) < best_gap:
            best, best_gap = b, abs(gap)
    if best is None or best_gap > tolerance_min * 60:
        return None
    return best


def bar_before(bars, target, tolerance_min=30):
    best = None
    for b in bars:
        if b["t"] <= target:
            best = b
        else:
            break
    if best is None:
        return None
    if (target - best["t"]).total_seconds() > tolerance_min * 60:
        return None
    return best


def persistence(move_1h, move_close):
    if move_1h is None or move_close is None or abs(move_1h) < 0.01:
        return ""
    same = (move_1h > 0) == (move_close > 0)
    ratio = abs(move_close) / abs(move_1h)
    if same and ratio >= 0.6:
        return "sustained"
    if ratio < 0.4 or not same:
        return "faded"
    return "partial"


def existing_keys():
    rows = riskmod.load_history()
    return {(r.get("date"), r.get("event")) for r in rows}


def main():
    tz = ZoneInfo(config.DISPLAY_TZ)
    today = datetime.now(tz).date()

    raw_cal = sources.fetch_calendar()
    events = [e for e in sources.parse_events(raw_cal, today)
              if e["weight"] >= config.MATERIAL_WEIGHT]
    if not events:
        print("[evening] no material USD events today, nothing to record")
        return 0

    symbol, bars = sources.gold_intraday(days=5)
    bars.sort(key=lambda b: b["t"])
    day_bars = [b for b in bars if b["t"].astimezone(tz).date() == today]
    if not day_bars:
        print("[evening] no intraday bars for today, skipping")
        return 0
    session_close = day_bars[-1]["c"]
    print(f"[evening] {symbol}: {len(day_bars)} bars today, close {session_close:.2f}")

    seen = existing_keys()
    new_rows = []
    for e in events:
        if (str(today), e["title"]) in seen:
            continue
        t0 = datetime.fromisoformat(e["utc"])
        before = bar_before(bars, t0)
        if before is None:
            print(f"[evening] no pre-event bar for {e['title']}, skipping")
            continue
        b15 = bar_at(bars, t0 + timedelta(minutes=15))
        b60 = bar_at(bars, t0 + timedelta(minutes=60))
        base = before["c"]
        m15 = round(b15["c"] - base, 2) if b15 else None
        m60 = round(b60["c"] - base, 2) if b60 else None
        mcl = round(session_close - base, 2)
        new_rows.append({
            "date": str(today),
            "time_uk": e["local_time"],
            "event": e["title"],
            "impact": e["impact"],
            "weight": e["weight"],
            "forecast": e["forecast"],
            "previous": e["previous"],
            "actual": e.get("actual", ""),
            "gold_before": round(base, 2),
            "gold_15m": round(b15["c"], 2) if b15 else "",
            "gold_1h": round(b60["c"], 2) if b60 else "",
            "gold_close": round(session_close, 2),
            "move_15m": m15 if m15 is not None else "",
            "move_1h": m60 if m60 is not None else "",
            "move_close": mcl,
            "pct_close": round(mcl / base * 100, 3) if base else "",
            "persistence": persistence(m60, mcl),
        })

    if not new_rows:
        print("[evening] nothing new to append")
        return 0

    os.makedirs(os.path.dirname(riskmod.EVENTS_CSV), exist_ok=True)
    fresh = not os.path.exists(riskmod.EVENTS_CSV)
    with open(riskmod.EVENTS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=riskmod.CSV_FIELDS)
        if fresh:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)
            print(f"[evening] logged {r['event']}: 1h {r['move_1h']}, "
                  f"close {r['move_close']} ({r['persistence']})")
    print(f"[evening] appended {len(new_rows)} rows to data/events.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
