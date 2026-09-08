"""Risk scoring and the historical base-rate lookup.

The score answers one question: how violent is gold likely to be today?
It is deliberately explainable - every point is attributable to a component.
"""

import csv
import os
import statistics
from datetime import datetime

import config

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
EVENTS_CSV = os.path.join(DATA_DIR, "events.csv")

CSV_FIELDS = [
    "date", "time_uk", "event", "impact", "weight", "forecast", "previous",
    "actual", "surprise", "surprise_label", "co_released",
    "gold_before", "gold_15m", "gold_1h", "gold_close",
    "move_15m", "move_1h", "move_close", "pct_close", "persistence",
]

CALIBRATION_CSV = os.path.join(DATA_DIR, "calibration.csv")
CALIBRATION_FIELDS = [
    "date", "risk_score", "band", "predicted_range", "range_source",
    "realised_range", "error", "abs_error_pct", "scheduled", "unscheduled",
]


def ensure_schema(path=None, fields=None):
    """Widen an existing CSV in place when new columns are added.

    Appending wider rows under an older header would silently corrupt every
    read, so migrate the file rather than risk it.
    """
    path = path or EVENTS_CSV
    fields = fields or CSV_FIELDS
    if not os.path.exists(path):
        return False
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        existing = reader.fieldnames or []
        if existing == fields:
            return False
        rows = list(reader)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    print(f"[risk] migrated {os.path.basename(path)} "
          f"from {len(existing)} to {len(fields)} columns")
    return True


# ---------------------------------------------------------------------------
# Historical base rates - this is what makes it a database
# ---------------------------------------------------------------------------

def load_history():
    if not os.path.exists(EVENTS_CSV):
        return []
    with open(EVENTS_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _key(title):
    """Normalise an event title so 'CPI m/m' matches across months."""
    return " ".join((title or "").lower().split())


def base_rate(title, history=None):
    """What gold has actually done on this event before, from our own log.

    Split by whether the print came in above, below or on the forecast, because
    the unconditional average is a blend of two different events.
    """
    history = load_history() if history is None else history
    k = _key(title)
    rows = [r for r in history if _key(r.get("event")) == k]
    moves, persist, shared, buckets = [], [], [], {}
    for row in rows:
        try:
            move = abs(float(row["move_1h"]))
        except (KeyError, ValueError, TypeError):
            continue
        moves.append(move)
        persist.append(row.get("persistence", ""))
        try:
            shared.append(int(row.get("co_released") or 0))
        except (TypeError, ValueError):
            pass
        label = (row.get("surprise_label") or "").strip()
        if label:
            buckets.setdefault(label, []).append(move)
    if len(moves) < 3:
        return None
    sustained = sum(1 for p in persist if p == "sustained")
    by_surprise = {
        label: {"samples": len(vals),
                "median_move_1h": round(statistics.median(vals), 2)}
        for label, vals in buckets.items() if len(vals) >= 2
    }
    return {
        "samples": len(moves),
        "median_move_1h": round(statistics.median(moves), 2),
        "max_move_1h": round(max(moves), 2),
        "sustained_rate": round(100 * sustained / len(persist)) if persist else None,
        "by_surprise": by_surprise or None,
        "co_released": max(shared) if shared else 0,
    }


def calibration(limit=60):
    """How close the predicted range has been to the range that happened."""
    if not os.path.exists(CALIBRATION_CSV):
        return None
    with open(CALIBRATION_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))[-limit:]
    errs, over, pairs = [], 0, []
    for r in rows:
        try:
            pred, real = float(r["predicted_range"]), float(r["realised_range"])
        except (KeyError, ValueError, TypeError):
            continue
        if not real:
            continue
        errs.append(abs(pred - real) / real * 100)
        over += 1 if pred > real else 0
        pairs.append({"date": r.get("date"), "predicted": pred, "realised": real,
                      "score": r.get("risk_score")})
    if len(errs) < 5:
        return {"samples": len(errs), "ready": False}
    return {
        "samples": len(errs),
        "ready": True,
        "median_abs_error_pct": round(statistics.median(errs), 1),
        "over_predicted_pct": round(100 * over / len(errs)),
        "recent": pairs[-14:],
    }


# ---------------------------------------------------------------------------
# Day risk score
# ---------------------------------------------------------------------------

def score_day(events, atr14=None, atr_avg=None, history=None, geo=None,
              implied=None, cot=None, profile_names=None):
    """Return a 0-100 risk score with a full breakdown of where it came from.

    Two independent sources of danger - what is diarised, and what is not -
    combined so that neither can hide the other. A day with a live escalation
    and an empty calendar must not read LOW.
    """
    history = load_history() if history is None else history
    material = [e for e in events if e["weight"] >= config.MATERIAL_WEIGHT]
    top = max((e["weight"] for e in events), default=0)

    # Events published at the same minute are ONE release, not several: the
    # payrolls report carries three titles and moves gold once.
    releases = {}
    for e in material:
        releases.setdefault(e.get("release") or e["local_time"], []).append(e)

    # 1. The single biggest scheduled event drives most of the scheduled score.
    headline = min(70, top * 7)

    # 2. Breadth - separate releases through the day compound the noise.
    breadth = min(15, 3 * max(0, len(releases) - 1))

    # 3. Clustering - two heavyweight prints at the same minute is worse than
    #    the same two spread across the day.
    #    Components of ONE report published together (payrolls, the unemployment
    #    rate and earnings) are not a cluster - that is one shock, already
    #    reflected in the headline weight. Two different reports are.
    profile_names = profile_names or {}
    clustered = 0
    for items in releases.values():
        heavy = [e for e in items if e["weight"] >= config.MAJOR_WEIGHT - 2]
        distinct = {profile_names.get(e["title"], e["title"]) for e in heavy}
        if len(distinct) > 1:
            clustered = 5
            break

    scheduled = headline + breadth + clustered

    # 4. Unscheduled risk, from the geopolitical layer.
    geo_points = int((geo or {}).get("points", 0) or 0)

    # Neither source masks the other, and both at once is worse than either.
    hi, lo = max(scheduled, geo_points), min(scheduled, geo_points)
    both = int(min(15, round(0.35 * lo)))
    base = hi + both

    # 5. Ambient volatility. Prefer the options market's own expectation over a
    #    backward-looking ATR when it is available.
    vol = 0
    vol_ratio = None
    if implied and implied.get("percentile_1y") is not None:
        vol = max(-5, min(10, round((implied["percentile_1y"] - 50) / 5)))
        vol_ratio = round(implied["gvz"] / 100, 2)
    elif atr14 and atr_avg:
        vol_ratio = atr14 / atr_avg
        vol = max(-5, min(10, round((vol_ratio - 1) * 25)))
        vol_ratio = round(vol_ratio, 2)

    # 6. Crowded speculative positioning amplifies whatever else happens.
    crowding = 0
    if cot and cot.get("percentile_2y") is not None:
        if cot["percentile_2y"] >= 85 or cot["percentile_2y"] <= 15:
            crowding = 5

    score = int(max(0, min(100, base + vol + crowding)))

    band, note = "LOW", ""
    for lo_b, hi_b, name, desc in config.RISK_BANDS:
        if lo_b <= score < hi_b:
            band, note = name, desc
            break

    # Expected daily range: the options market's number if we have it, else ATR.
    expected_range = None
    range_source = None
    if implied and implied.get("one_sd_range_usd"):
        expected_range = implied["one_sd_range_usd"]
        range_source = f"GVZ {implied['gvz']} (implied, 1 s.d.)"
    elif atr14:
        expected_range = round(atr14 * (0.85 + score / 100 * 0.75), 1)
        range_source = "14-day ATR (historical)"

    return {
        "score": score,
        "band": band,
        "band_note": note,
        "expected_range_usd": expected_range,
        "range_source": range_source,
        "atr14": round(atr14, 2) if atr14 else None,
        "vol_ratio": vol_ratio,
        "scheduled": scheduled,
        "unscheduled": geo_points,
        "components": {
            "headline_event": headline,
            "breadth": breadth,
            "clustering": clustered,
            "geopolitical": geo_points,
            "both_at_once": both,
            "volatility": vol,
            "positioning": crowding,
        },
        "material_events": len(material),
        "releases": len(releases),
        "top_weight": top,
    }


def classify_event(event, history=None):
    """Plain-English expectation for one event, blended with our own history."""
    w = event["weight"]
    stats = base_rate(event["title"], history)
    if w >= 9:
        expectation = "Top-tier gold driver. Expect an immediate repricing on the print."
    elif w >= 7:
        expectation = "Strong gold driver. A surprise here moves the metal within seconds."
    elif w >= config.MATERIAL_WEIGHT:
        expectation = "Secondary driver. Usually a short spike unless it confirms a trend."
    else:
        expectation = "Background noise for gold. Rarely tradeable on its own."

    direction = ("Hotter than forecast is dollar-positive and gold-negative; "
                 "softer readings do the reverse.")
    t = event["title"].lower()
    if "unemployment rate" in t or "claims" in t:
        direction = ("Higher unemployment is read as dovish, which is normally "
                     "gold-positive; a strong labour print pressures gold.")
    elif "speaks" in t or "fomc member" in t:
        direction = ("No number to trade - the risk is a hawkish or dovish tone "
                     "shift, which moves gold through rate expectations.")
    elif "gdp" in t:
        direction = ("Growth beats support the dollar and weigh on gold, though "
                     "gold often shrugs off GDP unless it is a big miss.")

    return {"expectation": expectation, "direction": direction, "history": stats}
