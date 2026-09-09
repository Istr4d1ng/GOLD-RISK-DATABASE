"""Unscheduled risk: the geopolitical layer.

The economic calendar covers what is diarised. Gold's largest single-day moves
frequently are not. This module reads world-news feeds, matches headlines to
named flashpoints and escalation language, and produces a score the day-risk
model can use, so a day with a live military exchange cannot read LOW simply
because no US data is due.

It is a headline-frequency heuristic, not a geopolitical model. It says "this
is loud right now", not "this will happen".
"""

import csv
import json
import os
import re
import statistics
from datetime import datetime, timedelta, timezone

import config
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = os.path.join(ROOT, "data", "geopolitical_profiles.json")

_cache = None


def load():
    global _cache
    if _cache is None:
        with open(PROFILES, encoding="utf-8") as fh:
            _cache = json.load(fh)
    return _cache


def _hit(text, terms):
    return [t for t in terms if t in text]


def classify(title, summary=""):
    """Match one headline to a flashpoint and an escalation tier."""
    data = load()
    text = f"{title} {summary}".lower()
    text = re.sub(r"\s+", " ", text)

    best, best_terms = None, []
    for key, fp in data["flashpoints"].items():
        hits = _hit(text, fp["terms"])
        if hits and (best is None or fp["weight"] > data["flashpoints"][best]["weight"]):
            best, best_terms = key, hits
    if not best:
        return None

    esc = data["escalation"]
    fp = data["flashpoints"][best]
    # Some phrases are themselves the escalation - "fire Powell" needs no verb.
    if _hit(text, fp.get("severe_terms", [])) and not _hit(text, esc["de_escalation"]):
        return {"flashpoint": best, "flashpoint_name": fp["name"], "tier": "severe",
                "score": round(fp["weight"] * config.GEO_INTENSITY["severe"], 2),
                "matched": best_terms[:3],
                "esc_matched": _hit(text, fp.get("severe_terms", []))[:3]}
    if _hit(text, esc["de_escalation"]):
        tier, sign, hits = "de_escalation", -1, _hit(text, esc["de_escalation"])
    elif _hit(text, esc["severe"]):
        tier, sign, hits = "severe", 1, _hit(text, esc["severe"])
    elif _hit(text, esc["elevated"]):
        tier, sign, hits = "elevated", 1, _hit(text, esc["elevated"])
    else:
        tier, sign, hits = "background", 1, []

    weight = data["flashpoints"][best]["weight"]
    factor = config.GEO_INTENSITY.get(tier, 0.15) if sign > 0 else 0.4
    return {
        "flashpoint": best,
        "flashpoint_name": data["flashpoints"][best]["name"],
        "tier": tier,
        "score": round(weight * factor * sign, 2),
        "matched": best_terms[:3],
        "esc_matched": hits[:3],
    }


def fetch_headlines(hours=None):
    """Recent world-news headlines that match a flashpoint."""
    hours = hours or config.GEO_LOOKBACK_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    out = []
    for source, url in config.GEO_FEEDS:
        try:
            raw = sources._get(url, timeout=15, retries=2)
            root = sources.ET.fromstring(raw)
        except Exception as exc:            # noqa: BLE001
            print(f"[geo] {source} unavailable: {exc}")
            continue
        nodes = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry")
        for node in nodes:
            title = sources._text(node, "title",
                                  "{http://www.w3.org/2005/Atom}title")
            if not title:
                continue
            desc = re.sub(r"<[^>]+>", " ",
                          sources._text(node, "description", "summary"))[:300]
            pub = sources._parse_date(
                sources._text(node, "pubDate", "published", "updated"))
            if pub and pub < cutoff:
                continue
            hit = classify(title, desc)
            if not hit:
                continue
            link = sources._text(node, "link")
            if not link:
                el = node.find("{http://www.w3.org/2005/Atom}link")
                link = el.get("href") if el is not None else ""
            out.append({**hit, "source": source, "title": title.strip(),
                        "link": link, "published": pub.isoformat() if pub else "",
                        "summary": " ".join(desc.split())})
    seen, unique = set(), []
    for h in sorted(out, key=lambda x: -abs(x["score"])):
        key = h["title"].lower()[:70]
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)
    return unique


# ---------------------------------------------------------------------------
# History - the baseline each flashpoint is measured against
# ---------------------------------------------------------------------------

HISTORY_CSV = os.path.join(ROOT, "data", "geo_history.csv")
HISTORY_FIELDS = ["date", "flashpoint", "headlines", "events", "severe",
                  "elevated", "calming", "raw_score", "markers"]


def load_history():
    if not os.path.exists(HISTORY_CSV):
        return []
    with open(HISTORY_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def record(today, flashpoints):
    """Append today's per-flashpoint counts. Idempotent for a given date."""
    rows = load_history()
    if any(r.get("date") == str(today) for r in rows):
        return False
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    fresh = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_FIELDS)
        if fresh:
            w.writeheader()
        for fp in flashpoints:
            w.writerow({
                "date": str(today), "flashpoint": fp["key"],
                "headlines": fp["headlines"], "events": fp.get("events", 0),
                "severe": fp["severe"], "elevated": fp["elevated"],
                "calming": fp["calming"], "raw_score": fp["raw"],
                "markers": "|".join(fp.get("markers", [])),
            })
    return True


def _median(vals):
    return statistics.median(vals) if vals else 0.0


def series_for_key(key, history, today=None, days=None):
    """This flashpoint's daily intensity, oldest first - what the chart draws."""
    days = days or config.GEO_BASELINE_DAYS
    rows = [r for r in history if r.get("flashpoint") == key]
    rows.sort(key=lambda r: r.get("date", ""))
    if today:
        rows = [r for r in rows if r.get("date", "") < str(today)]
    out = []
    for r in rows[-days:]:
        try:
            out.append({"date": r.get("date"), "score": float(r.get("raw_score") or 0)})
        except (TypeError, ValueError):
            continue
    return out


def baseline_for(key, history, today=None, days=None):
    """Median and spread of this flashpoint's own recent daily intensity."""
    days = days or config.GEO_BASELINE_DAYS
    rows = [r for r in history if r.get("flashpoint") == key]
    rows.sort(key=lambda r: r.get("date", ""))
    if today:
        rows = [r for r in rows if r.get("date", "") < str(today)]
    rows = rows[-days:]
    vals = []
    for r in rows:
        try:
            vals.append(float(r.get("raw_score") or 0))
        except (TypeError, ValueError):
            continue
    if not vals:
        return {"baseline": 0.0, "mad": 0.0, "samples": 0, "days_active": 0,
                "ready": False}
    med = _median(vals)
    mad = _median([abs(v - med) for v in vals]) * 1.4826
    active = 0
    for v in reversed(vals):
        if v <= 0.01:
            break
        active += 1
    return {"baseline": round(med, 2), "mad": round(mad, 2),
            "samples": len(vals), "days_active": active,
            "ready": len(vals) >= config.GEO_BASELINE_MIN}


def seen_markers(key, history, today=None, lookback=None):
    lookback = lookback or config.GEO_NOVEL_LOOKBACK
    rows = [r for r in history if r.get("flashpoint") == key]
    rows.sort(key=lambda r: r.get("date", ""))
    if today:
        rows = [r for r in rows if r.get("date", "") < str(today)]
    out = set()
    for r in rows[-lookback:]:
        out.update(m for m in (r.get("markers") or "").split("|") if m)
    return out


# ---------------------------------------------------------------------------
# Story-level deduplication: several outlets on one event is signal, not volume
# ---------------------------------------------------------------------------

STOP = {"the", "a", "an", "of", "in", "on", "to", "for", "and", "as", "at",
        "by", "with", "is", "are", "says", "said", "after", "over", "from",
        "its", "his", "her", "they", "it", "new", "will", "has", "have"}


def _tokens(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in STOP and len(w) > 2}


def group_events(headlines):
    """Collapse the same story reported by several outlets into one event."""
    events = []
    for h in headlines:
        toks = _tokens(h["title"])
        placed = False
        for ev in events:
            if ev["flashpoint"] != h["flashpoint"]:
                continue
            overlap = len(toks & ev["tokens"]) / max(1, min(len(toks),
                                                           len(ev["tokens"])))
            if overlap >= 0.6:
                ev["items"].append(h)
                ev["tokens"] |= toks
                ev["sources"].add(h.get("source", ""))
                if abs(h["score"]) > abs(ev["score"]):
                    ev["score"], ev["tier"] = h["score"], h["tier"]
                    ev["title"] = h["title"]
                placed = True
                break
        if not placed:
            events.append({"flashpoint": h["flashpoint"], "tokens": toks,
                           "items": [h], "sources": {h.get("source", "")},
                           "score": h["score"], "tier": h["tier"],
                           "title": h["title"]})
    for ev in events:
        # Several independent outlets inside the window means something happened;
        # one outlet filing repeatedly means someone is writing about it.
        n = len([s for s in ev["sources"] if s])
        ev["source_count"] = n
        ev["weighted"] = round(ev["score"] * min(1.5, 1 + 0.15 * (n - 1)), 2)
        ev["burst"] = n >= 3
        ev.pop("tokens", None)
    return events


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def _state(sigma, raw, baseline, days_active, ready):
    """Named from the deviation, not the absolute level.

    A conflict running for months sits at "steady" on an ordinary day, however
    many severe headlines it generates, and only moves to "flaring" when it
    rises above its own normal.
    """
    if raw <= 0.01:
        return "quiet"
    if not ready:
        return "unbaselined"
    quieter = raw < baseline
    if sigma >= 2.0 and not quieter:
        return "escalating"
    if sigma >= 1.2 and not quieter:
        return "flaring"
    if sigma <= -1.0:
        return "de-escalating"
    return "steady" if days_active >= 4 else "simmering"


def assess(headlines=None, history=None, today=None):
    """Score each flashpoint against its own recent normal, not against zero."""
    data = load()
    headlines = fetch_headlines() if headlines is None else headlines
    history = load_history() if history is None else history

    events = group_events(headlines)
    by_fp = {}
    for ev in events:
        by_fp.setdefault(ev["flashpoint"], []).append(ev)
    for h in headlines:
        by_fp.setdefault(h["flashpoint"], [])

    flashpoints, any_ready = [], False
    for key, evs in by_fp.items():
        fp = data["flashpoints"][key]
        items = [i for ev in evs for i in ev["items"]]
        severe = sum(1 for i in items if i["tier"] == "severe")
        elevated = sum(1 for i in items if i["tier"] == "elevated")
        calming = sum(1 for i in items if i["tier"] == "de_escalation")
        raw = round(sum(ev["weighted"] for ev in evs), 2)

        base = baseline_for(key, history, today)
        any_ready = any_ready or base["ready"]
        spread = max(base["mad"], base["baseline"] * 0.35, 1.0)
        sigma = ((raw - base["baseline"]) / spread) if base["ready"] else None

        markers = sorted({m for i in items for m in i.get("esc_matched", [])})
        novel = sorted(set(markers) - seen_markers(key, history, today))
        burst = any(ev["burst"] for ev in evs)

        # New vocabulary is the strongest sign a story changed rather than simply
        # continued being covered - but only when the volume is at least normal.
        # A flashpoint quieter than its own baseline is not escalating, whatever
        # words appear in it.
        adj = sigma
        if adj is not None:
            bonus = 0.0
            if sigma >= -0.25:
                bonus += config.GEO_NOVEL_BONUS * min(len(novel), 3)
                if burst:
                    bonus += 0.4
            adj += min(bonus, config.GEO_BONUS_CAP)

        state = _state(sigma if sigma is not None else 0, raw,
                       base["baseline"], base["days_active"], base["ready"])
        wf = fp["weight"] / 10.0
        if adj is not None:
            capped = adj if raw >= base["baseline"] else min(adj, 0.9)
            escalation = max(0.0, min(1.0, capped / config.GEO_SIGMA_FULL)) * 70 * wf
        else:
            # No baseline yet: score conservatively and cap well below what a
            # measured deviation can reach, so an unknown cannot outrank a
            # flashpoint we can actually assess.
            escalation = min(config.GEO_BACKDROP_CAP * 2, raw * 2.0 * wf)
        backdrop = min(config.GEO_BACKDROP_CAP, base["baseline"] * 2.2 * wf)
        points = int(round(max(escalation, backdrop)))

        flashpoints.append({
            "key": key, "name": fp["name"], "weight": fp["weight"],
            "state": state, "headlines": len(items), "events": len(evs),
            "severe": severe, "elevated": elevated, "calming": calming,
            "raw": raw, "baseline": base["baseline"], "mad": base["mad"],
            "baseline_days": base["samples"], "baseline_ready": base["ready"],
            "days_active": base["days_active"] + (1 if raw > 0 else 0),
            "sigma": round(adj, 2) if adj is not None else None,
            "sigma_volume": round(sigma, 2) if sigma is not None else None,
            "novel_markers": novel, "markers": markers, "burst": burst,
            "points": points, "escalation": round(escalation, 1),
            "backdrop": round(backdrop, 1),
            "chain": fp.get("chain"),
            "drivers": fp.get("drivers") or {},
            "spoken": fp.get("spoken"), "spoken_why": fp.get("spoken_why"),
            "history": series_for_key(key, history, today)
                       + [{"date": str(today or ""), "score": raw}],
            "why_gold": fp["why_gold"], "counterweight": fp["counterweight"],
            "typical_duration": fp["typical_duration"],
            "escalation_markers": fp["escalation_markers"],
            "summary": _summary(fp, state, raw, base, novel, burst, len(items)),
            "top": sorted(items, key=lambda x: -abs(x["score"]))[:4],
            "all_headlines": sorted(items, key=lambda x: x.get("published", ""),
                                    reverse=True),
        })

    flashpoints.sort(key=lambda f: (-f["points"], -f["raw"]))
    top = flashpoints[0]["points"] if flashpoints else 0
    second = flashpoints[1]["points"] if len(flashpoints) > 1 else 0
    points = int(min(70, top + 0.25 * second))

    if points >= 50:
        band, note = "SEVERE", ("A flashpoint is far above its own normal. "
                                "Treat scheduled data as secondary today.")
    elif points >= 30:
        band, note = "ELEVATED", ("Something has genuinely changed rather than "
                                  "simply continued. Expect headline-driven moves.")
    elif points >= 12:
        band, note = "BACKGROUND", ("Standing tension, but at or near its usual "
                                    "level - largely in the price already.")
    else:
        band, note = "QUIET", "Nothing meaningfully above normal in the last 48 hours."

    return {
        "points": points, "band": band, "note": note,
        "flashpoints": flashpoints,
        "headline_count": len(headlines), "event_count": len(events),
        "baseline_ready": any_ready,
        "headlines": headlines[:12],
        "caveat": ("Each flashpoint is measured against its own trailing "
                   + str(config.GEO_BASELINE_DAYS) + "-day median, so a "
                   "long-running conflict does not sit at maximum forever. This "
                   "measures how loud a story is relative to its own normal - "
                   "not what will happen."),
    }


def _summary(fp, state, raw, base, novel, burst, n):
    if state == "quiet":
        return f"Nothing matched in the window. {fp['name']} is off the radar today."
    if not base["ready"]:
        return (f"{n} headlines. Not enough history yet to say whether that is "
                f"unusual - the baseline needs {config.GEO_BASELINE_MIN} days.")
    if state in ("escalating", "flaring"):
        bits = [f"{n} headlines against a normal of {base['baseline']:.1f}"]
        if novel:
            bits.append("and new language today (" + ", ".join(novel[:3]) + ")")
        if burst:
            bits.append("reported by several outlets at once")
        return ("Above its own baseline: " + ", ".join(bits)
                + ". That is a change, not just continuing coverage.")
    if state == "de-escalating":
        return ("Coverage is below its own normal and carrying de-escalation "
                "language. Any risk premium here should be fading.")
    if state == "steady":
        return (f"{n} headlines, which is about its normal of "
                f"{base['baseline']:.1f} after {base['days_active']} days running. "
                "Continuing coverage rather than escalation - gold has priced this.")
    return (f"{n} headlines against a normal of {base['baseline']:.1f}. "
            "Nothing that stands out from its own background.")
