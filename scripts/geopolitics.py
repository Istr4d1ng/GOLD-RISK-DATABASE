"""Unscheduled risk: the geopolitical layer.

The economic calendar covers what is diarised. Gold's largest single-day moves
frequently are not. This module reads world-news feeds, matches headlines to
named flashpoints and escalation language, and produces a score the day-risk
model can use, so a day with a live military exchange cannot read LOW simply
because no US data is due.

It is a headline-frequency heuristic, not a geopolitical model. It says "this
is loud right now", not "this will happen".
"""

import json
import os
import re
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
                "matched": best_terms[:3]}
    if _hit(text, esc["de_escalation"]):
        tier, sign = "de_escalation", -1
    elif _hit(text, esc["severe"]):
        tier, sign = "severe", 1
    elif _hit(text, esc["elevated"]):
        tier, sign = "elevated", 1
    else:
        tier, sign = "background", 1

    weight = data["flashpoints"][best]["weight"]
    factor = config.GEO_INTENSITY.get(tier, 0.15) if sign > 0 else 0.4
    return {
        "flashpoint": best,
        "flashpoint_name": data["flashpoints"][best]["name"],
        "tier": tier,
        "score": round(weight * factor * sign, 2),
        "matched": best_terms[:3],
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


def assess(headlines=None):
    """Aggregate headlines into per-flashpoint states and a 0-70 risk figure."""
    data = load()
    headlines = fetch_headlines() if headlines is None else headlines

    by_fp = {}
    for h in headlines:
        by_fp.setdefault(h["flashpoint"], []).append(h)

    flashpoints = []
    for key, items in by_fp.items():
        fp = data["flashpoints"][key]
        severe = sum(1 for i in items if i["tier"] == "severe")
        elevated = sum(1 for i in items if i["tier"] == "elevated")
        calming = sum(1 for i in items if i["tier"] == "de_escalation")
        if severe >= 2:
            state = "escalating"
        elif severe >= 1 or elevated >= 3:
            state = "active"
        elif elevated >= 1:
            state = "simmering"
        else:
            state = "quiet"
        if calming and calming >= severe:
            state = "de-escalating"
        flashpoints.append({
            "key": key, "name": fp["name"], "weight": fp["weight"],
            "state": state, "headlines": len(items),
            "severe": severe, "elevated": elevated, "calming": calming,
            "score": round(sum(i["score"] for i in items), 2),
            "why_gold": fp["why_gold"],
            "counterweight": fp["counterweight"],
            "typical_duration": fp["typical_duration"],
            "escalation_markers": fp["escalation_markers"],
            "top": sorted(items, key=lambda x: -abs(x["score"]))[:4],
        })
    flashpoints.sort(key=lambda f: -f["score"])

    scores = sorted((h["score"] for h in headlines), reverse=True)
    positive = [s for s in scores if s > 0]
    raw = 0.0
    if positive:
        raw = positive[0] + 0.4 * sum(positive[1:4])
    raw += sum(s for s in scores if s < 0)          # de-escalation pulls it down
    raw = max(0.0, raw)

    points = int(min(70, round(raw * 4)))
    if points >= 55:
        band = "SEVERE"
        note = ("Multiple severe headlines on a flashpoint gold is highly sensitive "
                "to. Treat scheduled data as secondary today.")
    elif points >= 35:
        band = "ELEVATED"
        note = ("A live escalation is running. Expect gold to react to headlines "
                "rather than to the calendar.")
    elif points >= 15:
        band = "BACKGROUND"
        note = ("Some geopolitical noise, nothing gold usually trades on its own.")
    else:
        band = "QUIET"
        note = "No meaningful unscheduled risk detected in the last 48 hours."

    return {
        "points": points,
        "raw": round(raw, 2),
        "band": band,
        "note": note,
        "flashpoints": flashpoints,
        "headline_count": len(headlines),
        "headlines": headlines[:12],
        "caveat": ("Derived from how loud the news is, not from any assessment of "
                   "what will happen. It measures attention, which is what moves "
                   "price in the short run."),
    }
