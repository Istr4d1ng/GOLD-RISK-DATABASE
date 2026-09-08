"""Offline smoke test: the whole morning pipeline against fixtures.

No network. Proves parsing, scoring, context, geopolitics, market data,
narrative and rendering all work end to end before it ever runs on GitHub.
"""
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import context                                    # noqa: E402
import geopolitics                                # noqa: E402
import market                                     # noqa: E402
import sources                                    # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "calendar.json")

# --- stub every network call ----------------------------------------------
# The fixture is a real week captured on 2026-08-28; shift it onto today so the
# test keeps working whenever it is run.
ANCHOR = datetime(2026, 8, 28).date()


def shifted_calendar():
    from zoneinfo import ZoneInfo
    import config
    entries = json.load(open(FIX, encoding="utf-8"))
    today = datetime.now(ZoneInfo(config.DISPLAY_TZ)).date()
    offset = timedelta(days=(today - ANCHOR).days)
    out = []
    for e in entries:
        e = dict(e)
        dt = datetime.fromisoformat(e["date"]) + offset
        e["date"] = dt.isoformat()
        out.append(e)
    return out


sources.fetch_calendar = shifted_calendar


def fake_daily(rng="2y"):
    bars, price = [], 4400.0
    start = datetime.now(timezone.utc) - timedelta(days=240)
    for i in range(240):
        price += 14 * math.sin(i / 3.1) + 3 * math.cos(i / 1.7)
        hi = price + 18 + 6 * abs(math.sin(i / 5))
        lo = price - 17 - 6 * abs(math.cos(i / 4))
        bars.append({"t": start + timedelta(days=i), "o": price - 4,
                     "h": hi, "l": lo, "c": price})
    return "GC=F (fixture)", bars


sources.gold_daily = fake_daily
sources.fetch_news = lambda hours=36, limit=25: [
    {"source": "Federal Reserve", "title": "Fed officials signal patience on cuts",
     "link": "https://example.invalid/1", "published": "", "relevance": 9,
     "summary": "Policymakers want more evidence before easing."},
    {"source": "Yahoo Gold", "title": "Gold holds near record as yields retreat",
     "link": "https://example.invalid/3", "published": "", "relevance": 10,
     "summary": "Bullion steadied with the 10-year yield lower."},
]

FOMC_PAGE = b"""<h4>2026 FOMC Meetings</h4>
January 27-28 March 17-18 April 28-29 June 16-17
July 28-29 September 15-16 October 27-28 December 8-9
"""
_real_get = sources._get
sources._get = lambda url, **kw: (FOMC_PAGE if "fomccalendar" in url
                                  else _real_get(url, **kw))


def fake_fred(series_id, years=3):
    base = {"CPIAUCSL": 320.0, "PCEPILFE": 128.0, "PAYEMS": 160000.0,
            "UNRATE": 4.2, "ICSA": 220000.0, "UMCSENT": 51.0,
            "MICH": 4.3, "DFII10": 1.85}.get(series_id, 100.0)
    return [(f"2026-{(i % 12) + 1:02d}-01", round(base * (1 + i * 0.002), 2))
            for i in range(30)]


context.fred_series = fake_fred
market.fred_series = fake_fred
market.implied_vol = lambda spot: {
    "gvz": 18.4, "percentile_1y": 72, "daily_move_pct": 1.16,
    "year_low": 12.1, "year_high": 26.8,
    "daily_move_usd": round((spot or 4400) * 0.0116, 1),
    "one_sd_range_usd": round((spot or 4400) * 0.0232, 1)}
market.drivers = lambda: {
    "DXY": {"label": "Dollar index", "last": 98.4, "change_pct": -0.31,
            "change_5d_pct": -0.8},
    "US10Y": {"label": "US 10-year yield", "last": 4.05, "change_pct": -1.2,
              "change_5d_pct": -2.1},
    "REAL10Y": {"label": "US 10-year real yield (TIPS)", "last": 1.82,
                "change_pct": None, "change_5d_bp": -9.0, "as_of": "2026-08-27"}}
market.cot_gold = lambda: {
    "as_of": "2026-08-25", "net": 214500, "long": 260000, "short": 45500,
    "net_pct_oi": 41.2, "percentile_2y": 91, "change_4w": 18400, "samples": 104,
    "read": "Managed money is crowded long.", "crowded": True,
    "history": [{"date": f"2026-0{(i % 9) + 1}-01", "net": 180000 + i * 900}
                for i in range(26)]}
geopolitics.fetch_headlines = lambda hours=None: [
    dict(geopolitics.classify(t) or {}, source="BBC World", title=t,
         link="https://example.invalid/g", published="", summary="")
    for t in ["US airstrike on Iranian vessel near Strait of Hormuz",
              "Iran attacks US base in Iraq, casualties reported",
              "China conducts routine drills near Taiwan"]
    if geopolitics.classify(t)]

import morning                                    # noqa: E402
import risk as riskmod                            # noqa: E402

assert morning.main() == 0

latest = json.load(open(os.path.join(ROOT, "data", "latest.json"), encoding="utf-8"))
html = open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8").read()
md = open(os.path.join(ROOT, "data", "reports", latest["date"] + ".md"),
          encoding="utf-8").read()
ev = latest["events"]
comp = latest["risk"]["components"]

print("\n--- checks ---")

# --- calendar --------------------------------------------------------------
assert all(e["currency"] == "USD" for e in ev)
assert "Retail Sales q/q" not in [e["title"] for e in ev]
print(f"ok  USD filter            ({len(ev)} events, non-USD excluded)")

warsh = next(e for e in ev if "Warsh" in e["title"])
assert warsh["folder"] == "RED" and warsh["local_time"] == "15:00"
print("ok  red folder + UK time  (Fed Chair 10:00 ET -> 15:00 UK)")

# --- weighting bug ---------------------------------------------------------
assert sources.weight_for("ADP Non-Farm Employment Change", "Medium") == 6
assert sources.weight_for("Non-Farm Employment Change", "High") == 10
print("ok  longest-match weights (ADP no longer inherits payrolls' 10)")

# --- co-release grouping ---------------------------------------------------
groups = latest["groups"]
titles_in_groups = sum(1 + len(g["also"]) for g in groups)
assert len(groups) < titles_in_groups, groups
payrolls = [g for g in groups if g["lead"] == "Non-Farm Employment Change"]
assert payrolls and len(payrolls[0]["also"]) == 2, groups
print(f"ok  co-release grouping   ({titles_in_groups} titles -> {len(groups)} briefings;"
      f" payrolls trio is one)")
briefing_section = md[md.index("## Event briefings"):md.index("## Analysis")]
assert briefing_section.count("Net jobs added outside farming") == 1, \
    briefing_section.count("Net jobs added outside farming")
print("ok  no duplicated briefing (the same text printed 3x before)")
assert comp["clustering"] == 5, comp
print("ok  clustering is real     (two different reports at 15:00, not one report's parts)")

# --- geopolitics -----------------------------------------------------------
geo = latest["geo"]
assert geo["band"] in ("ELEVATED", "SEVERE"), geo
assert geo["points"] >= 35, geo
iran = next(f for f in geo["flashpoints"] if f["key"] == "us_iran")
assert iran["state"] == "escalating", iran
assert "Hormuz" in iran["why_gold"] or "strait" in iran["why_gold"].lower()
print(f"ok  geopolitical layer    ({geo['band']} {geo['points']}/70, Iran {iran['state']})")
assert geopolitics.classify("Manchester United sign new striker") is None
assert geopolitics.classify("Rail workers strike over pay") is None
print("ok  no false positives     (football and rail strikes ignored)")
assert "Unscheduled risk" in html and "How long it lasts" in html
print("ok  flashpoint panel rendered")

# --- the score can no longer read LOW on an unscheduled day ----------------
quiet = riskmod.score_day([], history=[], geo=geopolitics.assess([]))
warday = riskmod.score_day([], history=[], geo=geo)
assert quiet["score"] < 10 and warday["score"] >= 50, (quiet, warday)
print(f"ok  empty calendar + war  ({warday['score']}/100 {warday['band']}, "
      f"was 0 before)")
assert latest["risk"]["scheduled"] and latest["risk"]["unscheduled"]
print(f"ok  scheduled vs unsched  ({latest['risk']['scheduled']} / "
      f"{latest['risk']['unscheduled']})")

# --- implied vol, drivers, positioning ------------------------------------
assert "GVZ" in (latest["risk"]["range_source"] or "")
assert latest["risk"]["expected_range_usd"] > 50
print(f"ok  implied expected range (${latest['risk']['expected_range_usd']}, "
      f"{latest['risk']['range_source']})")
assert latest["attribution"]["channel"] == "real yields", latest["attribution"]
print(f"ok  driver attribution     ({latest['attribution']['channel']})")
assert comp["positioning"] == 5 and "91th" in html
print("ok  crowded positioning    (+5, 91st percentile flagged)")

# --- context ---------------------------------------------------------------
ctx = latest["context"]
assert ctx["Fed Chairman Warsh Speaks"]["profile"]["name"] == "Fed Chair Speaks"
assert latest["fomc"]["status"]["next"] == "2026-09-16"
print(f"ok  profiles + FOMC cycle  (next {latest['fomc']['status']['next']})")
uom_ctx = ctx["Revised UoM Inflation Expectations"]
assert uom_ctx["readings"]["series"] == "MICH"
print("ok  FRED readings attached")

# --- surprise-conditioned base rates --------------------------------------
hist = [{"event": "CPI m/m", "move_1h": v, "persistence": p, "surprise_label": l}
        for v, p, l in [("31", "sustained", "above"), ("27", "sustained", "above"),
                        ("6", "faded", "in line"), ("5", "faded", "in line"),
                        ("-24", "sustained", "below")]]
br = riskmod.base_rate("CPI m/m", hist)
assert br["by_surprise"]["above"]["median_move_1h"] == 29.0
assert br["by_surprise"]["in line"]["median_move_1h"] == 5.5
print(f"ok  surprise conditioning  (above ${br['by_surprise']['above']['median_move_1h']}"
      f" vs in line ${br['by_surprise']['in line']['median_move_1h']})")

import actuals                                    # noqa: E402
assert actuals.parse_number("208K") == 208000.0
assert actuals.surprise("0.2%", 0.3) == (0.1, "above")
assert actuals.surprise("0.2%", 0.2)[1] == "in line"
print("ok  actual + surprise parse")

# --- health ----------------------------------------------------------------
hs = latest["health"]
assert hs["ok"] >= 6 and hs["failed"] == 0, hs
assert "Data health" in html
print(f"ok  data health panel      ({hs['ok']} sources ok, {hs['failed']} failed)")

# --- output ----------------------------------------------------------------
assert "<script" not in html.lower() and len(html) > 12000
print(f"ok  dashboard renders      ({len(html):,} bytes, zero JS)")
assert "## Event briefings" in md and "## Data health" in md
print("ok  markdown archive")

print("\nALL CHECKS PASSED")
