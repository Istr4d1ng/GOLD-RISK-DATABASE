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
    "actual", "gold_before", "gold_15m", "gold_1h", "gold_close",
    "move_15m", "move_1h", "move_close", "pct_close", "persistence",
]


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
    """What gold has actually done on this event before, from our own log."""
    history = load_history() if history is None else history
    k = _key(title)
    moves, persist = [], []
    for row in history:
        if _key(row.get("event")) != k:
            continue
        try:
            moves.append(abs(float(row["move_1h"])))
        except (KeyError, ValueError, TypeError):
            continue
        persist.append(row.get("persistence", ""))
    if len(moves) < 3:
        return None
    sustained = sum(1 for p in persist if p == "sustained")
    return {
        "samples": len(moves),
        "median_move_1h": round(statistics.median(moves), 2),
        "max_move_1h": round(max(moves), 2),
        "sustained_rate": round(100 * sustained / len(persist)) if persist else None,
    }


# ---------------------------------------------------------------------------
# Day risk score
# ---------------------------------------------------------------------------

def score_day(events, atr14=None, atr_avg=None, history=None):
    """Return a 0-100 risk score with a full breakdown of where it came from."""
    history = load_history() if history is None else history
    material = [e for e in events if e["weight"] >= config.MATERIAL_WEIGHT]
    top = max((e["weight"] for e in events), default=0)

    # 1. The single biggest scheduled event drives most of the score.
    headline = min(70, top * 7)

    # 2. Breadth - several meaningful releases compound the noise.
    breadth = min(15, 3 * max(0, len(material) - 1))

    # 3. Clustering - two heavyweight prints at the same minute is worse
    #    than the same two spread across the day.
    clustered = 0
    times = {}
    for e in events:
        if e["weight"] >= config.MAJOR_WEIGHT - 2:
            times.setdefault(e["local_time"], []).append(e)
    if any(len(v) > 1 for v in times.values()):
        clustered = 5

    # 4. Ambient volatility - a hot tape makes any event more dangerous.
    vol = 0
    vol_ratio = None
    if atr14 and atr_avg:
        vol_ratio = atr14 / atr_avg
        vol = max(-5, min(10, round((vol_ratio - 1) * 25)))

    raw = headline + breadth + clustered + vol
    score = int(max(0, min(100, raw)))

    band, note = "LOW", ""
    for lo, hi, name, desc in config.RISK_BANDS:
        if lo <= score < hi:
            band, note = name, desc
            break

    # Expected daily range in dollars, widened by the risk score.
    expected_range = None
    if atr14:
        expected_range = round(atr14 * (0.85 + score / 100 * 0.75), 1)

    return {
        "score": score,
        "band": band,
        "band_note": note,
        "expected_range_usd": expected_range,
        "atr14": round(atr14, 2) if atr14 else None,
        "vol_ratio": round(vol_ratio, 2) if vol_ratio else None,
        "components": {
            "headline_event": headline,
            "breadth": breadth,
            "clustering": clustered,
            "volatility": vol,
        },
        "material_events": len(material),
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
