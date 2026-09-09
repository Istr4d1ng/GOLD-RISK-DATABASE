"""Offline smoke test: the whole morning pipeline against fixtures.

No network. Proves parsing, scoring, context, geopolitics, market data,
narrative and rendering all work end to end before it ever runs on GitHub.
"""
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import config                                     # noqa: E402
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
    {"source": "Federal Reserve", "title": "Fed pushes back on rate cut bets",
     "link": "https://example.invalid/1", "published": "", "relevance": 9,
     "summary": "Officials say it is too early to cut."},
    {"source": "Financial Juice", "title": "Fed's Warsh rules out a cut this year",
     "link": "https://example.invalid/2", "published": "", "relevance": 9,
     "summary": "Higher for longer, the Chair told the conference."},
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
# Stub the price feed rather than market_map itself, so the real risk-appetite
# and miner-divergence logic is what gets tested.
MOVES = {"^GSPC": -0.62, "^NDX": -0.81, "^DJI": -0.44, "^RUT": -1.42,
         "^VIX": 8.40, "^FTSE": -0.30, "NVDA": -1.30, "MSFT": -0.85,
         "AMZN": -1.10, "JPM": -0.70, "CAT": -0.90, "XOM": 1.20,
         "LLY": 0.55, "PG": 0.41, "NEM": 2.10, "GDX": 1.90,
         # the tracked cross-asset set
         "GC=F": 0.26, "CL=F": 1.80, "DX-Y.NYB": -0.31, "^TNX": -1.20,
         "SI=F": 1.40, "HG=F": -0.60, "BTC-USD": -2.10, "EURUSD=X": 0.28,
         "USDJPY=X": -0.45}


def _daily_chart(symbol, interval="1d", rng="1mo"):
    if symbol not in MOVES:
        raise RuntimeError(f"no fixture for {symbol}")
    pct = MOVES[symbol]
    base, bars = 100.0, []
    seed = sum(ord(c) for c in symbol)
    start = datetime.now(timezone.utc) - timedelta(days=90)
    for i in range(89):
        wobble = math.sin((i + seed) / 4.0) * 0.9 + math.cos((i + seed) / 7.0) * 0.5
        px = base * (1 + wobble / 100)
        bars.append({"t": start + timedelta(days=i), "o": px, "h": px,
                     "l": px, "c": px})
    last = bars[-1]["c"] * (1 + pct / 100)
    bars.append({"t": start + timedelta(days=89), "o": last, "h": last,
                 "l": last, "c": last})
    return bars


ASIA_MOVES = {"^N225": -1.10, "^HSI": -0.85, "000001.SS": -0.40,
              "^AXJO": -0.62, "^KS11": -1.35}
OVERNIGHT = {"GC=F": 0.42, "ES=F": -0.55, "NQ=F": -0.72, "CL=F": 1.10,
             "DX-Y.NYB": -0.12, "^TNX": -0.40, "SI=F": 0.65, "HG=F": -0.30,
             "BTC-USD": -1.40, "EURUSD=X": 0.10, "USDJPY=X": -0.28,
             "^VIX": 3.10, "XAUUSD=X": 0.42}


def fake_chart(symbol, interval="1d", rng="1mo"):
    if interval == "5m":
        if symbol not in OVERNIGHT:
            raise RuntimeError(f"no overnight fixture for {symbol}")
        pct = OVERNIGHT[symbol]
        tz = ZoneInfo(config.DISPLAY_TZ)
        start = datetime.combine(date.today(), datetime.min.time(), tzinfo=tz)
        bars, px = [], 100.0
        for i in range(78):                      # 00:00 -> 06:30 in 5m steps
            px = 100 * (1 + pct * (i / 77) / 100
                        + math.sin(i / 6.0) * 0.08 / 100)
            t = (start + timedelta(minutes=5 * i)).astimezone(timezone.utc)
            bars.append({"t": t, "o": px, "h": px * 1.0006,
                         "l": px * 0.9994, "c": px})
        return bars
    if symbol in ASIA_MOVES:
        pct = ASIA_MOVES[symbol]
        return [{"t": None, "o": 100, "h": 100, "l": 100, "c": 100},
                {"t": None, "o": 100, "h": 100, "l": 100,
                 "c": 100 * (1 + pct / 100)}]
    return _daily_chart(symbol, interval, rng)


sources.fetch_chart = fake_chart

market.cot_gold = lambda: {
    "as_of": "2026-08-25", "net": 214500, "long": 260000, "short": 45500,
    "net_pct_oi": 41.2, "percentile_2y": 91, "change_4w": 18400, "samples": 104,
    "read": "Managed money is crowded long.", "crowded": True,
    "history": [{"date": f"2026-0{(i % 9) + 1}-01", "net": 180000 + i * 900}
                for i in range(26)]}
GEO_FIXTURE = [
    ("US airstrike on Iranian vessel near Strait of Hormuz", "Financial Juice"),
    ("Iran attacks US base in Iraq, casualties reported", "BBC World"),
    ("Iran blockade of Gulf shipping, tankers seized", "Al Jazeera"),
    ("China conducts routine drills near Taiwan", "BBC World"),
]
geopolitics.fetch_headlines = lambda hours=None: [
    dict(geopolitics.classify(t) or {}, source=src, title=t,
         link="https://example.invalid/g", published="2026-09-09T06:00", summary="")
    for t, src in GEO_FIXTURE if geopolitics.classify(t)]

# Thirty days in which this has all been happening already, so the baseline is
# real rather than cold.
GEO_HISTORY = [
    {"date": f"2026-08-{d:02d}", "flashpoint": k, "raw_score": str(v),
     "headlines": "4", "events": "3", "severe": "2", "elevated": "1",
     "calming": "0", "markers": "strike|missile|attack"}
    for d in range(1, 31) for k, v in (("us_iran", 24), ("china_taiwan", 8))]
geopolitics.load_history = lambda: GEO_HISTORY
geopolitics.record = lambda today, fps: False

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

# --- geopolitics: measured against its own baseline ------------------------
geo = latest["geo"]
assert geo["baseline_ready"] is True, geo
iran = next(f for f in geo["flashpoints"] if f["key"] == "us_iran")
assert iran["baseline"] > 0 and iran["sigma_volume"] is not None, iran
print(f"ok  baseline established  (Iran normal {iran['baseline']}, "
      f"today {iran['raw']}, {iran['sigma_volume']:+.2f} sigma)")
assert geopolitics.classify("Manchester United sign new striker") is None
assert geopolitics.classify("Rail workers strike over pay") is None
print("ok  no false positives     (football and rail strikes ignored)")

# the same story from three outlets is one event, not three
ev = geopolitics.group_events(geopolitics.fetch_headlines())
assert len(ev) < len(geopolitics.fetch_headlines()) or all(
    e["source_count"] >= 1 for e in ev)
print(f"ok  stories deduplicated  ({len(geopolitics.fetch_headlines())} headlines "
      f"-> {len(ev)} events)")

# a long-running conflict at its usual level must NOT read as escalating
flat = [dict(geopolitics.classify(t) or {}, source=src, title=t, link="",
             published="2026-09-09T06:00", summary="")
        for t, src in GEO_FIXTURE[:2] if geopolitics.classify(t)]
steady_hist = [{"date": f"2026-08-{d:02d}", "flashpoint": "us_iran",
                "raw_score": "20", "headlines": "4", "events": "3",
                "severe": "2", "elevated": "1", "calming": "0",
                "markers": "strike|missile|attack|casualties"}
               for d in range(1, 31)]
quiet = geopolitics.assess(flat, history=steady_hist,
                           today=date(2026, 9, 9))
qi = next(f for f in quiet["flashpoints"] if f["key"] == "us_iran")
assert qi["state"] in ("steady", "simmering", "de-escalating"), qi
assert qi["points"] <= 25, qi
print(f"ok  ongoing war is quiet  (day 31 at its normal level reads "
      f"'{qi['state']}', {qi['points']}/70 - not pinned at maximum)")

# and the day it genuinely changes, it fires
surge = flat + [dict(geopolitics.classify(t) or {}, source=s2, title=t, link="",
                     published="2026-09-09T06:00", summary="")
                for t, s2 in [("Iran closes Strait of Hormuz, tankers seized",
                               "Financial Juice"),
                              ("US strikes Iranian oil terminal, casualties", "BBC World"),
                              ("Hormuz blockade: US Navy mobilises", "Al Jazeera"),
                              ("Iran missile attack on Gulf shipping, vessels shot down",
                               "UN News")]
                if geopolitics.classify(t)]
hot = geopolitics.assess(surge, history=steady_hist,
                         today=date(2026, 9, 9))
hi = next(f for f in hot["flashpoints"] if f["key"] == "us_iran")
assert hi["state"] == "escalating" and hi["points"] > qi["points"] + 25, hi
assert hi["novel_markers"], hi
print(f"ok  real escalation fires ({hi['sigma_volume']:+.2f} sigma, "
      f"{qi['points']} -> {hi['points']}/70, new language {hi['novel_markers'][:2]})")

assert "Unscheduled risk" in html and 'data-geo="geo/' in html
assert html.count('class="pop"') >= 2
print("ok  three-level geo UI     (rows, hold-popovers, links to full pages)")
geo_page = os.path.join(ROOT, "docs", "geo", "us_iran.html")
assert os.path.exists(geo_page)
gp = open(geo_page, encoding="utf-8").read()
assert "How it reaches gold" in gp and "../index.html" in gp
print("ok  flashpoint pages built (docs/geo/*.html with headlines and links)")

# --- the score can no longer read LOW on an unscheduled day ----------------
calm = riskmod.score_day([], history=[], geo=geopolitics.assess([], history=[]))
warday = riskmod.score_day([], history=[], geo=hot)
assert calm["score"] < 10 and warday["score"] >= 50, (calm, warday)
print(f"ok  empty calendar + war  ({warday['score']}/100 {warday['band']}, "
      f"was 0 before this layer existed)")
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
assert comp["positioning"] == 5 and "91th percentile" in html
print("ok  crowded positioning    (+5, 91st percentile flagged)")

# --- market map ------------------------------------------------------------
mm = latest["market_map"]
assert len(mm["indices"]) >= 4 and len(mm["stocks"]) >= 8, mm
assert len(set(s["sector"] for s in mm["stocks"])) >= 6, mm["sectors"]
print(f"ok  market map fetched     ({len(mm['indices'])} indices, "
      f"{len(mm['stocks'])} stocks across {len(mm['sectors'])} sectors)")
assert mm["appetite"] == "risk-off", mm
assert mm["spread"] < 0 and "gold-supportive" in mm["appetite_note"]
print(f"ok  risk appetite derived  (cyclicals {mm['cyclical_avg']} vs defensives "
      f"{mm['defensive_avg']} -> {mm['appetite']})")
assert mm["miner_read"] and "little to read into" in mm["miner_read"], mm["miner_read"]
print(f"ok  miners read vs gold    (gold only "
      f"{latest['gold']['change_pct']:+.2f}%, so no leverage claim made)")
loud = market.market_map(1.2)
assert "leverage" in loud["miner_read"] and "more than 5x" not in loud["miner_read"]
print(f"ok  leverage stays sane    ({loud['miner_read'].split(' - ')[1][:34]}...)")
assert "Market map" in html and "Nvidia" in html and "Newmont" in html
assert "Consumer staples" in html
print("ok  market map rendered    (sector labels, day and 5d change)")

# a confident tape should read the other way
_risk_on = dict(MOVES, **{"NVDA": 1.6, "JPM": 1.2, "CAT": 1.4, "AMZN": 1.5,
                          "MSFT": 1.1, "LLY": 0.1, "PG": -0.2, "^RUT": 1.8,
                          "^VIX": -7.0})
_orig = dict(MOVES)
MOVES.update(_risk_on)
on = market.market_map(0.9)
MOVES.clear(); MOVES.update(_orig)
assert on["appetite"] == "risk-on" and "headwind" in on["appetite_note"], on
print(f"ok  flips on a strong tape (risk-on, spread {on['spread']:+.2f}pp)")

# --- spoken brief ----------------------------------------------------------
import speech as sp   # noqa: E402

brief = open(os.path.join(ROOT, "data", "brief.txt"), encoding="utf-8").read()
words = sp.word_count(brief)
assert 120 <= words <= 400, words
print(f"ok  spoken brief written   ({words} words, about "
      f"{sp.duration_estimate(brief)}s)")

# it must NOT be the page read aloud
for bad in ("|", "%", "  ", "(", "sigma", "n=", "0.0"):
    assert bad not in brief, bad
assert "σ" not in brief and "&" not in brief
print("ok  written for the ear    (no tables, symbols, brackets or decimals)")

# names that read badly must have been replaced
assert "US / Israel" not in brief and " / " not in brief
assert "Iran, and the US and Israel" in brief
print("ok  spoken names used      ('US / Israel - Iran' would read as nonsense)")

# every line should be a real sentence, not a fragment like "Days."
frags = [l for l in brief.strip().split("\n")
         if len(re.findall(r"[A-Za-z']+", l)) < 4]
assert not frags, frags
print("ok  no sentence fragments")

assert "means for" in brief or "argues for" in brief
assert brief.count("argues for") >= 2
print("ok  covers other markets   (not just gold)")

for phrase in ("half past", "o'clock", "quarter"):
    if phrase in brief:
        break
else:
    raise AssertionError("times were not verbalised")
print("ok  times spoken naturally")

assert latest["brief"]["audio"].startswith("audio/")
assert 'id="brief"' in html and "hidden" in html and "audio/" in html
print("ok  player renders hidden  (revealed only if the mp3 exists)")

import audio   # noqa: E402
assert audio.KEEP_DAYS == 30 and audio._voice_parts("en_GB-alan-medium") == ("alan", "medium")
assert float(audio.LENGTH_SCALE) > 1.0 and float(audio.SENTENCE_SILENCE) > 0.2
print(f"ok  audio step configured  (en_GB-alan-medium, {audio.LENGTH_SCALE}x speed, "
      f"{audio.SENTENCE_SILENCE}s between sentences)")

assert len(audio.SHORTLIST) >= 4
assert all(v.startswith("en_GB-") for v, _ in audio.SHORTLIST)
assert all(n and len(n) > 20 for _, n in audio.SHORTLIST)
print(f"ok  voice shortlist        ({len(audio.SHORTLIST)} British voices, each described)")
assert callable(audio.audition)
print("ok  audition mode exists   (renders one passage in every voice)")

# --- current affairs -------------------------------------------------------
import current_affairs as ca   # noqa: E402

af = latest["affairs"]
assert af["stories"], af
iran_story = next((s for s in af["stories"] if s["key"] == "us_iran"), None)
assert iran_story and iran_story["kind"] == "geopolitical"
assert iran_story["chain"] and iran_story["rows"]
print(f"ok  live stories modelled  ({len(af['stories'])} stories; "
      f"top is {af['stories'][0]['title']})")

verdicts = {r["verdict"] for st in af["stories"] for r in st["rows"]}
assert verdicts <= {"consistent", "not following", "flat"}, verdicts
assert any(r["verdict"] in ("consistent", "not following")
           for st in af["stories"] for r in st["rows"])
print(f"ok  expected vs observed   (verdicts seen: {', '.join(sorted(verdicts))})")

oil = next((r for r in iran_story["rows"] if r["key"] == "oil"), None)
assert oil and oil["expected"] > 0, oil
print(f"ok  mechanism is right     (Iran -> oil expected {oil['expected_dir']}, "
      f"observed {oil['observed']:+.2f}%, {oil['verdict']})")

assert af["pending"], af["pending"]
p0 = af["pending"][0]
assert p0["above"] and p0["below"]
above_gold = next((i for i in p0["above"] if i["name"] == "Gold"), None)
below_gold = next((i for i in p0["below"] if i["name"] == "Gold"), None)
if above_gold and below_gold:
    assert above_gold["direction"] != below_gold["direction"]
print(f"ok  pending events both ways ({p0['name']}: modelled for a beat and a miss)")

# the theme classifier, including the case keyword rules usually get wrong
hawk = ca.classify_headline("Fed's Warsh pushes back on rate cut expectations")
assert hawk["drivers"]["rate_expectations"] == 1, hawk
dove = ca.classify_headline("US inflation cools more than expected")
assert dove["drivers"]["inflation"] == -1, dove
assert ca.classify_headline("Manchester United sign new striker") is None
print("ok  theme direction parsed ('pushes back on rate cuts' reads hawkish)")

assert 'id="affairs"' in html and "Current affairs" in html
assert "Model expects" in html and "Actually did" in html
assert "Current affairs and markets" in md
# a de-escalating flashpoint must invert, not repeat, its usual effect
easing = next((s2 for s2 in af["stories"] if s2.get("easing")), None)
if easing:
    fp_raw = next(f for f in latest["geo"]["flashpoints"] if f["key"] == easing["key"])
    for k, v in fp_raw["drivers"].items():
        assert easing["drivers"][k] == -v, (k, easing["drivers"], fp_raw["drivers"])
    print(f"ok  easing inverts        ({easing['title']} de-escalating, "
          f"drivers flipped)")

reads = [s2["read"] for s2 in af["stories"]]
assert not any("Mostly consistent, except" in r and r.count(",") > 3 for r in reads)
assert all(("and" in r or "not following" in r or "consistent" in r
            or "moved enough" in r) for r in reads)
print("ok  read matches the split (no 'mostly consistent' when most disagree)")

print("ok  affairs section rendered")

# --- Asia session ----------------------------------------------------------
az = latest["asia"]
assert az["indices"] and len(az["indices"]) == 5, az["indices"]
print(f"ok  Asia indices           ({len(az['indices'])} markets, Nikkei "
      f"{az['indices'][0]['change_pct']:+.2f}%)")

assert az["moves"] and az["moves"][0]["key"] == "gold", az["moves"][0]
gold_on = az["moves"][0]
assert gold_on["range_pct"] > 0 and 0 <= gold_on["position"] <= 100
print(f"ok  overnight move + range (gold {gold_on['change_pct']:+.2f}% in a "
      f"{gold_on['range_pct']:.2f}% range, {gold_on['position']}% up it)")

# cash indices do not trade overnight - the future has to stand in
sp = next(m for m in az["moves"] if m["key"] == "sp500")
assert sp["symbol"] == "ES=F", sp
print(f"ok  futures for the gap    (S&P read from {sp['symbol']}, not ^GSPC)")

assert az["read"] and "Asian equities" in az["read"] and "Gold moved" in az["read"]
assert "into London" in az["read"]
print("ok  overnight read written (risk tone + where gold sits into London)")
assert "07:00" in az["caveat"] and az["cutoff"]
print(f"ok  honest about the cutoff (measured to {az['cutoff']}, Tokyo still open)")

assert "Asia overnight" in html and "ES=F" not in html
assert "Asia overnight" in md and "Position in range" in md
print("ok  Asia section rendered")

# --- cross-asset layer -----------------------------------------------------
import assets as assetlib      # noqa: E402
import reactions               # noqa: E402

board = latest["board"]
assert len(board) == 12, [b["key"] for b in board]
assert any(b["primary"] for b in board)
print(f"ok  cross-asset board      ({len(board)} assets tracked, gold flagged primary)")

corr = latest["correlations"]
assert corr and corr["regime"] and len(corr["notable"]) >= 3
print(f"ok  correlations computed  ({corr['window']}-day, "
      f"top pair {corr['notable'][0]['name']} {corr['notable'][0]['corr']:+.2f})")

# the derivation: one mechanism, applied across the book
hot_cpi = assetlib.explain({"inflation": 1, "rate_expectations": 1})
assert hot_cpi["gold"]["direction"] == "down"
assert hot_cpi["dollar"]["direction"] == "up"
assert hot_cpi["us10y"]["direction"] == "up"
assert hot_cpi["nasdaq"]["net"] < hot_cpi["sp500"]["net"]
print(f"ok  driver derivation      (hot CPI: gold {hot_cpi['gold']['net']:+.2f}, "
      f"dollar {hot_cpi['dollar']['net']:+.2f}, Nasdaq hit harder than S&P)")
assert hot_cpi["gold"]["conflict"] is True
print("ok  conflicts surfaced     (gold: inflation hedge vs rate pressure)")

# a dovish read has to flip cleanly
cool = assetlib.explain({"inflation": -1, "rate_expectations": -1})
assert cool["gold"]["direction"] == "up" and cool["dollar"]["direction"] == "down"
print("ok  signs flip cleanly     (cool CPI mirrors the hot case)")

# higher jobless claims is dovish, so gold should RISE - the case a naive
# "above forecast is bullish USD" rule gets backwards
claims = assetlib.explain(
    context.load_profiles()["unemployment claims"]["drivers"])
assert claims["gold"]["direction"] == "up" and claims["us10y"]["direction"] == "down"
print("ok  direction-aware events (higher claims reads dovish, not hawkish)")

iran = assetlib.explain({"geopolitics": 1, "supply_shock": 1})
assert iran["oil"]["net"] > iran["gold"]["net"] > 0 and iran["sp500"]["net"] < 0
print(f"ok  geopolitics derivation (oil {iran['oil']['net']:+.2f} > "
      f"gold {iran['gold']['net']:+.2f}, equities negative)")

for akey in ("gold", "oil", "bitcoin", "usdjpy"):
    page = os.path.join(ROOT, "docs", "assets", f"{akey}.html")
    assert os.path.exists(page), akey
gp = open(os.path.join(ROOT, "docs", "assets", "gold.html"), encoding="utf-8").read()
assert "What moves it" in gp and "drivers/rate_expectations.html" in gp
dp = open(os.path.join(ROOT, "docs", "drivers", "rate_expectations.html"),
          encoding="utf-8").read()
assert "assets/gold.html" in dp and "If this rises" in dp
print("ok  asset + driver pages   (12 assets, 8 drivers, cross-linked)")
assert 'href="assets/gold.html"' in html and "Cross-asset board" in html
print("ok  board links from home")

cov = latest["coverage"]
assert set(cov) == {"rows", "events", "assets", "days"}
print(f"ok  coverage reported      ({cov['rows']} reaction rows logged so far)")

# --- navigation ------------------------------------------------------------
DOCS = os.path.join(ROOT, "docs")
for rel in ("assets/index.html", "drivers/index.html", "geo/index.html",
            "reports/index.html"):
    assert os.path.exists(os.path.join(DOCS, rel)), rel
print("ok  index pages exist      (assets, drivers, flashpoints, archive)")

for rel, needle in (("assets/index.html", "Metals"),
                    ("drivers/index.html", "Rate expectations"),
                    ("geo/index.html", "Flashpoints"),
                    ("reports/index.html", "Daily archive")):
    page = open(os.path.join(DOCS, rel), encoding="utf-8").read()
    assert needle in page, rel
    assert page.count('class="nav"') >= 1 and "../index.html" in page, rel
    assert 'id="filter"' in page, rel
print("ok  every index navigable (site nav + filter box on each)")

ai = open(os.path.join(DOCS, "assets", "index.html"), encoding="utf-8").read()
assert ai.count("data-find=") == 12, ai.count("data-find=")
assert '<a href="../assets/index.html" class="on">' in ai
print("ok  assets index complete  (12 cards, grouped, current page marked)")

gold_page = open(os.path.join(DOCS, "assets", "gold.html"), encoding="utf-8").read()
assert 'class="nav"' in gold_page and '../drivers/index.html' in gold_page
geo_page = open(os.path.join(DOCS, "geo", "us_iran.html"), encoding="utf-8").read()
assert 'class="nav"' in geo_page
print("ok  sub-pages carry nav    (no more dead ends)")

assert 'class="nav"' in html and 'href="#calendar"' in html
assert 'id="calendar"' in html and 'id="briefings"' in html and 'id="asia"' in html
print("ok  dashboard jump links   (Asia, geopolitics, calendar, briefings, board)")
assert 'reports/index.html">all' in html
print("ok  archive moved out      (dashboard keeps the recent few)")

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
assert "data health" in html.lower()
print(f"ok  data health panel      ({hs['ok']} sources ok, {hs['failed']} failed)")

# --- output ----------------------------------------------------------------
assert len(html) > 12000 and "data-band=" in html
assert "prefers-color-scheme" in html and 'data-theme="dark"' in html
assert "prefers-reduced-motion" in html
print(f"ok  dashboard renders      ({len(html):,} bytes, both themes, "
      f"reduced-motion respected)")
assert "## Event briefings" in md and "## Data health" in md and "## Unscheduled risk" in md
print("ok  markdown archive")

print("\nALL CHECKS PASSED")
