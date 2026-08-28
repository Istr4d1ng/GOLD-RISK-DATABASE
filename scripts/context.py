"""Event context: what each release is, and what it has done before.

Three layers, each degrading quietly if its source is unavailable:
  1. Curated profiles   - data/event_profiles.json, always available
  2. Recent readings    - FRED CSV downloads, no API key required
  3. Gold's own history - measured from daily bars around past FOMC dates
"""

import csv
import gzip
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

import config
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_PATH = os.path.join(ROOT, "data", "event_profiles.json")
FOMC_CACHE = os.path.join(ROOT, "data", "fomc_dates.json")

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"

# Event title -> FRED series. Keyless CSV downloads, updated on release day.
EVENT_SERIES = {
    "cpi m/m": ("CPIAUCSL", "CPI index level", "index"),
    "core cpi m/m": ("CPILFESL", "Core CPI index level", "index"),
    "cpi y/y": ("CPIAUCSL", "CPI index level", "index"),
    "core pce price index": ("PCEPILFE", "Core PCE index level", "index"),
    "pce price index": ("PCEPI", "PCE index level", "index"),
    "non-farm employment change": ("PAYMS_DIFF", "Monthly change in payrolls (000s)", "diff"),
    "unemployment rate": ("UNRATE", "Unemployment rate (%)", "level"),
    "average hourly earnings": ("CES0500000003", "Avg hourly earnings ($)", "index"),
    "unemployment claims": ("ICSA", "Initial claims", "level"),
    "core retail sales": ("RSAFS", "Retail sales ($m)", "index"),
    "retail sales m/m": ("RSAFS", "Retail sales ($m)", "index"),
    "advance gdp q/q": ("A191RL1Q225SBEA", "Real GDP growth (% annualised)", "level"),
    "prelim gdp q/q": ("A191RL1Q225SBEA", "Real GDP growth (% annualised)", "level"),
    "final gdp q/q": ("A191RL1Q225SBEA", "Real GDP growth (% annualised)", "level"),
    "federal funds rate": ("DFEDTARU", "Fed funds target, upper (%)", "level"),
    "ism manufacturing pmi": ("MANEMP_NA", "", "skip"),
    "uom consumer sentiment": ("UMCSENT", "Michigan sentiment", "level"),
    "uom inflation expectations": ("MICH", "1-year inflation expectations (%)", "level"),
    "jolts job openings": ("JTSJOL", "Job openings (000s)", "level"),
    "core ppi m/m": ("PPIFIS", "PPI final demand", "index"),
    "ppi m/m": ("PPIFIS", "PPI final demand", "index"),
}


# ---------------------------------------------------------------------------
# Curated profiles
# ---------------------------------------------------------------------------

_profiles_cache = None


def load_profiles():
    global _profiles_cache
    if _profiles_cache is None:
        try:
            with open(PROFILES_PATH, encoding="utf-8") as fh:
                _profiles_cache = json.load(fh).get("profiles", {})
        except Exception:                   # noqa: BLE001
            _profiles_cache = {}
    return _profiles_cache


def profile_for(title):
    """Longest-matching curated profile for an event title, or None."""
    profiles = load_profiles()
    t = (title or "").lower()
    best_key, best_len = None, 0
    for key in profiles:
        if key.startswith("_"):
            continue
        if key in t and len(key) > best_len:
            best_key, best_len = key, len(key)
    if not best_key:
        return None
    prof = profiles[best_key]
    seen = set()
    while "alias_of" in prof and prof["alias_of"] not in seen:
        seen.add(prof["alias_of"])
        prof = profiles.get(prof["alias_of"], {})
    return dict(prof) if prof else None


def series_for(title):
    t = (title or "").lower()
    best, best_len = None, 0
    for key, val in EVENT_SERIES.items():
        if key in t and len(key) > best_len:
            best, best_len = val, len(key)
    if best and best[2] == "skip":
        return None
    return best


# ---------------------------------------------------------------------------
# FRED - recent readings, no API key
# ---------------------------------------------------------------------------

def fred_series(series_id, years=3):
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    raw = sources._get(FRED_CSV.format(sid=series_id, start=start), timeout=25, retries=2)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8-sig", "replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows) < 2:
        raise RuntimeError(f"no rows for {series_id}")
    out = []
    for r in rows[1:]:
        if len(r) < 2 or r[1] in ("", "."):
            continue
        try:
            out.append((r[0][:10], float(r[1])))
        except ValueError:
            continue
    if not out:
        raise RuntimeError(f"no usable values for {series_id}")
    return out


def recent_readings(title, count=8):
    """Last few published readings for an event, with period-on-period change."""
    spec = series_for(title)
    if not spec:
        return None
    sid, label, kind = spec
    diff = sid.endswith("_DIFF")
    if diff:
        sid = sid.replace("_DIFF", "").replace("PAYMS", "PAYEMS")
    try:
        obs = fred_series(sid)
    except Exception as exc:                # noqa: BLE001
        print(f"[context] FRED {sid} unavailable: {exc}")
        return None

    points = []
    for i in range(1, len(obs)):
        d, v = obs[i]
        prev = obs[i - 1][1]
        if diff:
            points.append({"date": d, "value": round(v - prev, 1), "change": None})
        else:
            chg = ((v - prev) / prev * 100) if prev else None
            points.append({"date": d, "value": round(v, 2),
                           "change": round(chg, 2) if chg is not None else None})
    points = points[-count:]
    if not points:
        return None
    return {"series": sid, "label": ("Monthly change in payrolls (000s)"
                                     if diff else label),
            "kind": "diff" if diff else kind, "points": points}


# ---------------------------------------------------------------------------
# FOMC calendar
# ---------------------------------------------------------------------------

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

# Fallback used if the Fed page cannot be parsed. Second day = decision day.
FOMC_FALLBACK = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29",
    "2026-09-16", "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28",
    "2027-09-15", "2027-10-27", "2027-12-08",
]
FOMC_SEP = {"2026-03-18", "2026-06-17", "2026-09-16", "2026-12-09",
            "2027-03-17", "2027-06-09", "2027-09-15", "2027-12-08"}


def _parse_fomc_html(html_text):
    """Pull scheduled FOMC meeting dates out of the Fed calendar page.

    Scheduled meetings run two days, so only *ranged* dates are accepted --
    that alone excludes the single-day minutes-release dates printed in the
    same table. The decision comes on the second day.
    """
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", text)
    MON = ("January|February|March|April|May|June|July|August|September"
           "|October|November|December")
    token = re.compile(
        rf"(20\d\d)\s+(?:FOMC\s+)?Meetings"                    # year heading
        rf"|({MON})\s+(\d{{1,2}})\s*[-\u2010-\u2015]\s*({MON})\s+(\d{{1,2}})"  # Jan 31-Feb 1
        rf"|({MON})\s+\d{{1,2}}\s*[-\u2010-\u2015]\s*(\d{{1,2}})",             # Mar 17-18
        re.I)
    found, year = [], None
    for m in token.finditer(text):
        if m.group(1):
            year = int(m.group(1))
            continue
        if not year:
            continue
        if m.group(2):                      # cross-month range
            month, day = MONTHS.get(m.group(4).lower()), int(m.group(5))
            yr = year + 1 if month == 1 and MONTHS.get(m.group(2).lower()) == 12 else year
        else:                               # same-month range
            month, day, yr = MONTHS.get(m.group(6).lower()), int(m.group(7)), year
        try:
            found.append(date(yr, month, day).isoformat())
        except (ValueError, TypeError):
            continue

    # The Fed holds exactly eight scheduled meetings a year. Any year that does
    # not parse to eight is discarded rather than trusted -- a stray date would
    # put the "next meeting" countdown out.
    by_year = {}
    for d in found:
        by_year.setdefault(d[:4], [])
        if d not in by_year[d[:4]]:
            by_year[d[:4]].append(d)
    good = []
    for yr, ds in sorted(by_year.items()):
        if len(ds) == 8:
            good.extend(ds)
        else:
            print(f"[context] discarding {yr}: parsed {len(ds)} meetings, expected 8")
    return sorted(good)


def fomc_dates(refresh=True):
    """Decision dates, newest source first: live page, cache, then fallback."""
    if refresh:
        try:
            html_text = sources._get(FOMC_URL, timeout=25, retries=2).decode(
                "utf-8", "replace")
            dates = _parse_fomc_html(html_text)
            if len(dates) >= 8:
                with open(FOMC_CACHE, "w", encoding="utf-8") as fh:
                    json.dump({"fetched": datetime.now(timezone.utc).isoformat(),
                               "dates": dates}, fh, indent=2)
                return dates, "federalreserve.gov"
            print(f"[context] FOMC page parsed only {len(dates)} dates, ignoring")
        except Exception as exc:            # noqa: BLE001
            print(f"[context] FOMC page unavailable: {exc}")
    try:
        with open(FOMC_CACHE, encoding="utf-8") as fh:
            return json.load(fh)["dates"], "cache"
    except Exception:                       # noqa: BLE001
        return list(FOMC_FALLBACK), "built-in fallback"


def fomc_status(today, dates):
    """Where we are in the meeting cycle - a standing piece of context."""
    future = [d for d in dates if d >= today.isoformat()]
    past = [d for d in dates if d < today.isoformat()]
    nxt = future[0] if future else None
    out = {"next": nxt, "last": past[-1] if past else None,
           "is_today": today.isoformat() in dates}
    if nxt:
        out["days_away"] = (date.fromisoformat(nxt) - today).days
        out["has_projections"] = nxt in FOMC_SEP
    return out


# ---------------------------------------------------------------------------
# Gold's measured reaction to past instances
# ---------------------------------------------------------------------------

def gold_on_dates(dates, daily_bars, limit=8):
    """Gold's open-to-close move and next-day follow-through on given dates."""
    if not daily_bars:
        return []
    by_day = {}
    for b in daily_bars:
        by_day[b["t"].date().isoformat()] = b
    ordered = sorted(by_day)
    out = []
    for d in sorted([x for x in dates if x in by_day], reverse=True)[:limit]:
        bar = by_day[d]
        move = round(bar["c"] - bar["o"], 2)
        idx = ordered.index(d)
        follow = None
        if idx + 1 < len(ordered):
            nxt = by_day[ordered[idx + 1]]
            follow = round(nxt["c"] - bar["c"], 2)
        out.append({
            "date": d,
            "range": round(bar["h"] - bar["l"], 2),
            "move": move,
            "next_day": follow,
            "held": (None if follow is None or abs(move) < 0.01
                     else ((move > 0) == (follow > 0)) or abs(follow) < abs(move) * 0.3),
        })
    return out


def summarise_gold_on_dates(rows):
    if not rows:
        return None
    moves = [abs(r["move"]) for r in rows]
    ranges = [r["range"] for r in rows]
    held = [r["held"] for r in rows if r["held"] is not None]
    return {
        "samples": len(rows),
        "avg_abs_move": round(sum(moves) / len(moves), 2),
        "avg_range": round(sum(ranges) / len(ranges), 2),
        "biggest": round(max(moves), 2),
        "held_pct": round(100 * sum(1 for h in held if h) / len(held)) if held else None,
    }


def enrich(events, today, daily_bars=None):
    """Attach profile, recent readings and FOMC context to each event."""
    dates, source = fomc_dates()
    status = fomc_status(today, dates)
    fomc_hist = gold_on_dates(dates, daily_bars or [])
    out = {}
    for e in events:
        entry = {"profile": profile_for(e["title"])}
        if e["weight"] >= config.MATERIAL_WEIGHT:
            entry["readings"] = recent_readings(e["title"])
        t = e["title"].lower()
        if "fomc" in t or "federal funds" in t or "fed chair" in t:
            entry["fomc"] = status
            entry["fomc_gold_history"] = fomc_hist
            entry["fomc_gold_summary"] = summarise_gold_on_dates(fomc_hist)
        out[e["title"]] = entry
    return out, {"status": status, "source": source,
                 "gold_history": fomc_hist,
                 "gold_summary": summarise_gold_on_dates(fomc_hist)}
