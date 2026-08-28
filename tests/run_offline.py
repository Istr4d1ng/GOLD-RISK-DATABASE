"""Offline smoke test: runs the whole morning pipeline against fixtures.

No network needed. Proves the parsing, scoring, narrative and rendering all
work end to end before the thing ever runs on GitHub.
"""
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import sources                                    # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "calendar.json")

# --- stub the network ------------------------------------------------------
sources.fetch_calendar = lambda: json.load(open(FIX, encoding="utf-8"))


def fake_daily():
    bars, price = [], 3400.0
    start = datetime.now(timezone.utc) - timedelta(days=120)
    for i in range(120):
        price += 14 * math.sin(i / 3.1) + 3 * math.cos(i / 1.7)
        hi, lo = price + 18 + 6 * abs(math.sin(i / 5)), price - 17 - 6 * abs(math.cos(i / 4))
        bars.append({"t": start + timedelta(days=i), "o": price - 4,
                     "h": hi, "l": lo, "c": price})
    return "GC=F (fixture)", bars


sources.gold_daily = fake_daily
sources.fetch_news = lambda hours=36, limit=25: [
    {"source": "Federal Reserve", "title": "Fed officials signal patience on rate cuts as inflation cools",
     "link": "https://example.invalid/1", "published": "", "relevance": 9,
     "summary": "Policymakers said they want more evidence before easing."},
    {"source": "CNBC Economy", "title": "Dollar slips as traders price a September cut",
     "link": "https://example.invalid/2", "published": "", "relevance": 8,
     "summary": "The dollar index fell for a third session."},
    {"source": "Yahoo Gold", "title": "Gold holds near record as yields retreat",
     "link": "https://example.invalid/3", "published": "", "relevance": 10,
     "summary": "Bullion steadied with the 10-year yield lower."},
]

import morning                                    # noqa: E402
import risk as riskmod                            # noqa: E402

rc = morning.main()
assert rc == 0

# --- assertions ------------------------------------------------------------
latest = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
ev = latest["events"]
titles = [e["title"] for e in ev]
score = latest["risk"]["score"]

print("\n--- checks ---")
assert all(e["currency"] == "USD" for e in ev), "non-USD event leaked in"
print(f"ok  USD filter          ({len(ev)} events)")
assert "Retail Sales q/q" not in titles
print("ok  NZD event excluded")

warsh = next(e for e in ev if "Warsh" in e["title"])
assert warsh["folder"] == "RED", warsh
assert warsh["weight"] >= 8, warsh
assert warsh["local_time"] == "15:00", warsh["local_time"]   # 10:00 ET -> 15:00 UK
print(f"ok  red folder + UK time (Fed Chair at {warsh['local_time']})")

chicago = next(e for e in ev if e["title"] == "Chicago PMI")
assert chicago["weight"] <= 2, chicago
print("ok  low-impact downweighted")

assert 0 <= score <= 100
assert score >= 50, f"two red folders should not score {score}"
print(f"ok  risk score           ({score}/100 {latest['risk']['band']})")

comp = latest["risk"]["components"]
assert comp["clustering"] == 5, "15:00 cluster not detected"
print("ok  clustering detected  (two heavyweights at 15:00)")
assert sum(comp.values()) >= score - 1
print("ok  score is explainable (components sum to the total)")

html = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
assert "Fed Chairman Warsh Speaks" in html
assert "<script" not in html.lower(), "page should need no javascript"
assert len(html) > 6000
print(f"ok  dashboard renders    ({len(html):,} bytes, zero JS)")

md = open(os.path.join(ROOT, "data", "reports",
                       latest["date"] + ".md"), encoding="utf-8").read()
assert "Fed Chairman Warsh" in md and "Risk" in md
print("ok  markdown archive")

# base-rate lookup should be silent with no history yet
assert riskmod.base_rate("Core PCE Price Index m/m", []) is None
print("ok  base rates degrade gracefully with no history")

# and should work once history exists
fake_hist = [{"event": "Core PCE Price Index m/m", "move_1h": v, "persistence": p}
             for v, p in [("12.4", "sustained"), ("-8.1", "faded"),
                          ("19.0", "sustained"), ("-4.2", "faded"),
                          ("22.5", "sustained")]]
br = riskmod.base_rate("Core PCE Price Index m/m", fake_hist)
assert br["samples"] == 5 and br["median_move_1h"] == 12.4 and br["sustained_rate"] == 60, br
print(f"ok  base rates compute   (median ${br['median_move_1h']}, {br['sustained_rate']}% held)")

print("\nALL CHECKS PASSED")
