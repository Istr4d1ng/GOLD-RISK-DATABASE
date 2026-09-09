"""Current affairs, and what they are doing to markets.

Everything needed for this already existed separately: flashpoints and events
carry driver mappings, and assets carry sensitivities to those drivers. This
module points that machinery at what is actually in the news today, derives the
expected effect across the book, and then - the part that makes it worth
reading - checks it against what the market actually did.

Disagreement is the interesting output, not an error. Many things move at once
and this is not attribution; it is "here is what this story implies, and here is
whether prices are behaving that way".
"""

import json
import os
import re

import assets as assetlib
import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES_PATH = os.path.join(ROOT, "data", "themes.json")

_themes = None


def load_themes():
    global _themes
    if _themes is None:
        with open(THEMES_PATH, encoding="utf-8") as fh:
            _themes = json.load(fh)["themes"]
    return _themes


def _hits(text, terms):
    return [t for t in terms if t in text]


def classify_headline(title, summary=""):
    """Match a headline to a theme and work out which way it pushes."""
    text = re.sub(r"\s+", " ", f"{title} {summary}".lower())
    best, best_hits = None, []
    for key, spec in load_themes().items():
        hits = _hits(text, spec["terms"])
        if len(hits) > len(best_hits):
            best, best_hits = key, hits
    if not best:
        return None
    spec = load_themes()[best]
    ov_up = _hits(text, spec.get("override_hawkish", []))
    ov_down = _hits(text, spec.get("override_dovish", []))
    if ov_up and not ov_down:
        up, down = ov_up, []
    elif ov_down and not ov_up:
        up, down = [], ov_down
    else:
        up = _hits(text, spec.get("hawkish", []))
        down = _hits(text, spec.get("dovish", []))
    if up and not down:
        sign, tone = 1, "pushes it up"
    elif down and not up:
        sign, tone = -1, "pushes it down"
    else:
        sign, tone = 0, "direction unclear from the headline"
    return {"theme": best, "name": spec["name"], "sign": sign, "tone": tone,
            "matched": best_hits[:3],
            "drivers": {k: v * sign for k, v in spec["drivers"].items()}}


def _observed(board, asia):
    """Today's move per asset, preferring the overnight session at 06:30."""
    out = {}
    for row in (asia or {}).get("moves", []):
        out[row["key"]] = {"pct": row["change_pct"], "window": "overnight"}
    for row in board or []:
        if row["key"] not in out and row.get("change_pct") is not None:
            out[row["key"]] = {"pct": row["change_pct"], "window": "last close"}
    return out


def _check(expected, observed, floor=0.1):
    """Is the market behaving the way this story implies?"""
    rows, agree, disagree = [], 0, 0
    for key, exp in expected.items():
        obs = observed.get(key)
        if not obs or obs["pct"] is None:
            continue
        seen = obs["pct"]
        if abs(seen) < floor:
            verdict = "flat"
        elif (exp["net"] > 0) == (seen > 0):
            verdict = "consistent"
            agree += 1
        else:
            verdict = "not following"
            disagree += 1
        rows.append({"key": key, "name": exp["name"], "expected": exp["net"],
                     "expected_dir": exp["direction"], "observed": seen,
                     "window": obs["window"], "verdict": verdict,
                     "conflict": exp.get("conflict", False)})
    rows.sort(key=lambda r: -abs(r["expected"]))
    if agree + disagree == 0:
        read = "Nothing has moved enough to say whether prices agree."
    elif disagree == 0:
        read = "Prices are behaving as this story implies."
    elif agree == 0:
        read = ("Prices are not following this at all - either it is already "
                "priced, or the market disagrees that it matters.")
    else:
        off = [r["name"] for r in rows if r["verdict"] == "not following"]
        named = ", ".join(off[:3]) + (f" and {len(off) - 3} others" if len(off) > 3 else "")
        if disagree > agree:
            read = (f"Mostly not following - {named} are all going the other way. "
                    "Either this is already in the price, or something bigger is "
                    "driving the tape today.")
        else:
            read = (f"Broadly consistent, though {named} "
                    + ("are" if len(off) > 1 else "is")
                    + " not playing along. One asset out of line is usually its "
                      "own story; several is a reason to doubt the read.")
    return rows, read


def build(geo, news, board, asia, events=None, profiles=None):
    """The current-affairs board: live stories, their mechanism, and the check."""
    observed = _observed(board, asia)
    stories = []

    # 1. Geopolitical flashpoints that are actually doing something
    for fp in (geo or {}).get("flashpoints", []):
        if fp.get("state") in ("quiet",) or not fp.get("drivers"):
            continue
        if fp.get("points", 0) < 12 and fp.get("state") not in (
                "escalating", "flaring"):
            continue
        easing = fp.get("state") == "de-escalating"
        drivers = ({k: -v for k, v in fp["drivers"].items()} if easing
                   else fp["drivers"])
        expected = assetlib.explain(drivers)
        rows, read = _check(expected, observed)
        stories.append({
            "kind": "geopolitical", "key": fp["key"], "title": fp["name"],
            "easing": easing,
            "state": fp.get("state"), "detail": fp.get("summary") or fp["why_gold"],
            "chain": fp.get("chain"), "drivers": drivers,
            "why": fp.get("why_gold"), "counterweight": fp.get("counterweight"),
            "duration": fp.get("typical_duration"),
            "spoken": fp.get("spoken"), "spoken_why": fp.get("spoken_why"),
            "link": f"geo/{fp['key']}.html",
            "rows": rows[:6], "read": read,
            "weight": fp.get("points", 0),
        })

    # 2. Themes running through the news
    counts = {}
    for item in news or []:
        hit = classify_headline(item.get("title", ""), item.get("summary", ""))
        if not hit or hit["sign"] == 0:
            continue
        d = counts.setdefault((hit["theme"], hit["sign"]),
                              {"hit": hit, "items": []})
        d["items"].append(item)
    for (theme, sign), d in counts.items():
        if len(d["items"]) < 2:
            continue
        hit = d["hit"]
        expected = assetlib.explain(hit["drivers"])
        rows, read = _check(expected, observed)
        stories.append({
            "kind": "theme", "key": theme, "title": hit["name"],
            "state": hit["tone"], "detail": None,
            "chain": None, "drivers": hit["drivers"],
            "link": f"drivers/{list(hit['drivers'])[0]}.html",
            "headlines": d["items"][:4],
            "rows": rows[:6], "read": read,
            "weight": 10 + len(d["items"]),
        })

    # 3. Today's scheduled events, which have not happened yet
    pending = []
    for ev in (events or []):
        if ev.get("weight", 0) < config.MATERIAL_WEIGHT:
            continue
        prof = None
        for spec in (profiles or {}).values():
            if isinstance(spec, dict) and spec.get("drivers") and \
                    spec.get("name") and spec["name"].lower() in ev["title"].lower():
                prof = spec
                break
        if not prof:
            continue
        up = assetlib.explain(prof["drivers"])
        down = assetlib.explain({k: -v for k, v in prof["drivers"].items()})
        pending.append({
            "time": ev["local_time"], "title": ev["title"],
            "name": prof["name"],
            "above": [{"name": v["name"], "direction": v["direction"],
                       "net": v["net"]} for v in list(up.values())[:5]],
            "below": [{"name": v["name"], "direction": v["direction"],
                       "net": v["net"]} for v in list(down.values())[:5]],
        })

    stories.sort(key=lambda s: -s["weight"])
    return {
        "stories": stories[:6], "pending": pending[:4],
        "caveat": ("Expected direction is derived from the driver model; observed "
                   "is what prices have actually done. Many things move at once, "
                   "so this is a consistency check rather than attribution."),
    }
