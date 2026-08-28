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

# stub the context layer's two network calls
import context                                    # noqa: E402

FOMC_PAGE = b"""<h4>2026 FOMC Meetings</h4>
January 27-28 | Minutes: February 18
March 17-18 | Minutes: April 8
April 28-29 | Minutes: May 20
June 16-17 | Minutes: July 8
July 28-29 | Minutes: August 19
September 15-16 | Minutes: October 7
October 27-28 | Minutes: November 18
December 8-9 | Minutes: December 30
"""
_real_get = sources._get
sources._get = lambda url, **kw: (FOMC_PAGE if "fomccalendar" in url
                                  else _real_get(url, **kw))


def fake_fred(series_id, years=3):
    base = {"CPIAUCSL": 320.0, "PCEPILFE": 128.0, "PAYEMS": 160000.0,
            "UNRATE": 4.2, "ICSA": 220000.0, "UMCSENT": 51.0, "MICH": 4.3}.get(series_id, 100.0)
    out = []
    for i in range(30):
        out.append((f"2026-{(i % 12) + 1:02d}-01", round(base * (1 + i * 0.002), 2)))
    return out


context.fred_series = fake_fred

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

# --- event context layer ---------------------------------------------------
ctx = latest["context"]
warsh_ctx = ctx["Fed Chairman Warsh Speaks"]
assert warsh_ctx["profile"]["name"] == "Fed Chair Speaks", warsh_ctx["profile"]
assert "opportunity cost" in warsh_ctx["profile"]["why_gold"] or \
       "narrative" in warsh_ctx["profile"]["why_gold"]
print("ok  profile attached      (Fed Chair Speaks)")

assert "Fed Chair Speaks" in html and "What to watch" in html
assert "Why gold cares" in html
print("ok  briefing card rendered")

fomc = latest["fomc"]
assert fomc["source"] == "federalreserve.gov", fomc["source"]
assert fomc["status"]["next"] == "2026-09-16", fomc["status"]
assert fomc["status"]["days_away"] == 19, fomc["status"]
assert fomc["status"]["has_projections"] is True
print(f"ok  FOMC calendar scraped (next {fomc['status']['next']}, "
      f"{fomc['status']['days_away']} days, dot plot)")
assert "FOMC cycle" in html and "Next meeting" in html
print("ok  FOMC cycle card")

gs = fomc.get("gold_summary")
assert gs and gs["samples"] >= 2, gs
print(f"ok  gold measured on past decision days (n={gs['samples']}, "
      f"avg ${gs['avg_abs_move']})")

uom = ctx["Revised UoM Inflation Expectations"]
assert uom["readings"] and len(uom["readings"]["points"]) == 8, uom["readings"]
assert uom["readings"]["series"] == "MICH", uom["readings"]
assert "FRED" in html and "spark" in html
print("ok  recent readings series (8 points + sparkline)")

assert not ctx["Chicago PMI"].get("readings"), "immaterial event fetched a series"
print("ok  no readings fetched for immaterial events")

assert "## Event briefings" in md and "Why gold cares" in md
assert "## FOMC cycle" in md
print("ok  briefings in markdown archive")

print("\nALL CHECKS PASSED")
