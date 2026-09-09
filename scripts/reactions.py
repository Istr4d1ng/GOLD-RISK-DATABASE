"""Multi-asset reaction logging.

data/events.csv keeps the original gold record. This adds data/reactions.csv in
long format - one row per event per asset - which is what turns the base rates
from "CPI moves gold $29" into a matrix across the whole book.
"""

import csv
import os
from datetime import timedelta

import assets as A
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REACTIONS_CSV = os.path.join(ROOT, "data", "reactions.csv")
FIELDS = ["date", "time_uk", "event", "kind", "weight", "forecast", "actual",
          "surprise", "surprise_label", "asset", "before", "m15", "m1h",
          "close", "move_1h", "pct_15m", "pct_1h", "pct_close", "persistence"]


def load():
    if not os.path.exists(REACTIONS_CSV):
        return []
    with open(REACTIONS_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def intraday_bars(days=5):
    """5-minute bars for every tracked asset. Missing ones are skipped."""
    out, failed = {}, []
    for key, spec in A.load_assets().items():
        got = None
        for symbol in [spec["symbol"]] + list(spec.get("alt") or []):
            try:
                bars = sources.fetch_chart(symbol, "5m", f"{days}d")
                if len(bars) > 40:
                    got = bars
                    break
            except Exception:               # noqa: BLE001
                continue
        if got:
            got.sort(key=lambda b: b["t"])
            out[key] = got
        else:
            failed.append(key)
    return out, failed


def _before(bars, target, tolerance_min=30):
    best = None
    for b in bars:
        if b["t"] <= target:
            best = b
        else:
            break
    if best is None or (target - best["t"]).total_seconds() > tolerance_min * 60:
        return None
    return best


def _at(bars, target, tolerance_min=20):
    best, gap = None, None
    for b in bars:
        d = (b["t"] - target).total_seconds()
        if d < -300:
            continue
        if gap is None or abs(d) < gap:
            best, gap = b, abs(d)
    return best if best is not None and gap <= tolerance_min * 60 else None


def persistence(pct_1h, pct_close, floor=0.05):
    """Held, half held, or evaporated - in percent, so it works across assets."""
    if pct_1h is None or pct_close is None or abs(pct_1h) < floor:
        return ""
    same = (pct_1h > 0) == (pct_close > 0)
    ratio = abs(pct_close) / abs(pct_1h)
    if same and ratio >= 0.6:
        return "sustained"
    if ratio < 0.4 or not same:
        return "faded"
    return "partial"


def record(today, events, bars_by_asset, tz, kind="event"):
    """Append one row per (event, asset). Idempotent for a given date."""
    existing = {(r["date"], r["event"], r["asset"]) for r in load()}
    specs = A.load_assets()
    rows = []
    for ev in events:
        t0 = ev["utc"] if not isinstance(ev["utc"], str) else None
        from datetime import datetime as _dt
        t0 = _dt.fromisoformat(ev["utc"]) if t0 is None else t0
        for key, bars in bars_by_asset.items():
            if (str(today), ev["title"], key) in existing:
                continue
            day_bars = [b for b in bars if b["t"].astimezone(tz).date() == today]
            if not day_bars:
                continue
            before = _before(bars, t0)
            if before is None or not before["c"]:
                continue
            base = before["c"]
            b15, b60 = _at(bars, t0 + timedelta(minutes=15)), _at(bars, t0 + timedelta(minutes=60))
            close = day_bars[-1]["c"]
            dec = specs[key]["decimals"]

            def pct(bar):
                return round((bar["c"] - base) / base * 100, 3) if bar else None

            p15, p1h = pct(b15), pct(b60)
            pcl = round((close - base) / base * 100, 3)
            rows.append({
                "date": str(today), "time_uk": ev["local_time"],
                "event": ev["title"], "kind": kind, "weight": ev.get("weight", ""),
                "forecast": ev.get("forecast", ""), "actual": ev.get("actual", ""),
                "surprise": ev.get("surprise", ""),
                "surprise_label": ev.get("surprise_label", ""),
                "asset": key,
                "before": round(base, dec),
                "m15": round(b15["c"], dec) if b15 else "",
                "m1h": round(b60["c"], dec) if b60 else "",
                "close": round(close, dec),
                "move_1h": round(b60["c"] - base, dec) if b60 else "",
                "pct_15m": p15 if p15 is not None else "",
                "pct_1h": p1h if p1h is not None else "",
                "pct_close": pcl,
                "persistence": persistence(p1h, pcl),
            })
    if not rows:
        return 0
    os.makedirs(os.path.dirname(REACTIONS_CSV), exist_ok=True)
    fresh = not os.path.exists(REACTIONS_CSV)
    with open(REACTIONS_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if fresh:
            w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


# ---------------------------------------------------------------------------
# Reading it back: the matrix
# ---------------------------------------------------------------------------

def _median(vals):
    vals = sorted(vals)
    n = len(vals)
    if not n:
        return None
    return vals[n // 2] if n % 2 else round((vals[n // 2 - 1] + vals[n // 2]) / 2, 3)


def matrix_for_event(title, rows=None, min_samples=3):
    """Measured median move per asset for one event, split by surprise."""
    rows = load() if rows is None else rows
    key = " ".join((title or "").lower().split())
    hits = [r for r in rows if " ".join(r["event"].lower().split()) == key]
    if not hits:
        return None
    per_asset = {}
    for r in hits:
        try:
            pct = float(r["pct_1h"])
        except (ValueError, TypeError, KeyError):
            continue
        d = per_asset.setdefault(r["asset"], {"all": [], "by_surprise": {},
                                              "held": []})
        d["all"].append(pct)
        d["held"].append(r.get("persistence") == "sustained")
        label = (r.get("surprise_label") or "").strip()
        if label:
            d["by_surprise"].setdefault(label, []).append(pct)
    out = {}
    names = A.load_assets()
    for asset, d in per_asset.items():
        if len(d["all"]) < min_samples:
            continue
        out[asset] = {
            "name": names.get(asset, {}).get("name", asset),
            "samples": len(d["all"]),
            "median_pct_1h": _median([abs(v) for v in d["all"]]),
            "median_signed": _median(d["all"]),
            "sustained_rate": round(100 * sum(d["held"]) / len(d["held"])),
            "by_surprise": {k: {"samples": len(v), "median": _median(v)}
                            for k, v in d["by_surprise"].items() if len(v) >= 2},
        }
    return dict(sorted(out.items(), key=lambda kv: -abs(kv[1]["median_pct_1h"]))) or None


def coverage(rows=None):
    """How much history exists, so the page can be honest about it."""
    rows = load() if rows is None else rows
    if not rows:
        return {"rows": 0, "events": 0, "assets": 0, "days": 0}
    return {"rows": len(rows),
            "events": len({r["event"] for r in rows}),
            "assets": len({r["asset"] for r in rows}),
            "days": len({r["date"] for r in rows})}
