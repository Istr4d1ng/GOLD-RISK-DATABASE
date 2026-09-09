"""The spoken brief.

Deliberately NOT the page read aloud. The dashboard is written to be scanned -
tables, two-decimal percentages, parenthetical caveats - and all of that is
unbearable in audio. This writes a separate ninety-second script for the ear:
what is going on, what it means for gold, what it means for everything else,
and the times that matter.

Rules it follows: short sentences, one idea each. Numbers rounded and spoken as
words. No brackets, no symbols, no lists. Gold leads, because that is what the
listener came for.
"""

import os
import re

import assets as assetlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEF_PATH = os.path.join(ROOT, "data", "brief.txt")

SPOKEN_NAME = {
    "sp500": "the S and P five hundred", "nasdaq": "the Nasdaq",
    "us10y": "the ten year yield", "dollar": "the dollar",
    "eurusd": "the euro", "usdjpy": "dollar yen", "vix": "the VIX",
    "oil": "oil", "gold": "gold", "silver": "silver", "copper": "copper",
    "bitcoin": "bitcoin",
}


def say_pct(v, precise=False):
    """0.62 -> 'about six tenths of a percent'. Speech hates decimals."""
    if v is None:
        return "unchanged"
    a = abs(v)
    if a < 0.05:
        return "flat"
    if precise or a >= 10:
        return f"{a:.0f} percent"
    if a < 0.15:
        return "a touch"
    if a < 0.35:
        return "a quarter of a percent"
    if a < 0.6:
        return "half a percent"
    if a < 0.85:
        return "three quarters of a percent"
    if a < 1.25:
        return "about one percent"
    if a < 1.75:
        return "about one and a half percent"
    if a < 2.5:
        return "about two percent"
    return f"about {a:.0f} percent"


def say_move(v):
    if v is None:
        return "was unchanged"
    if abs(v) < 0.05:
        return "was flat"
    return ("rose " if v > 0 else "fell ") + say_pct(v)


def say_money(v):
    if v is None:
        return ""
    if v >= 1000:
        return f"about {v/1000:.1f} thousand dollars".replace(".0 ", " ")
    if v >= 100:
        return f"about {round(v / 10) * 10:.0f} dollars"
    return f"about {v:.0f} dollars"


def say_time(hhmm):
    """'13:30' -> 'half past one this afternoon'."""
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except (ValueError, AttributeError):
        return hhmm
    part = ("this morning" if h < 12 else
            "this afternoon" if h < 18 else "this evening")
    h12 = h % 12 or 12
    if m == 0:
        spoken = f"{h12} o'clock"
    elif m == 15:
        spoken = f"quarter past {h12}"
    elif m == 30:
        spoken = f"half past {h12}"
    elif m == 45:
        spoken = f"quarter to {(h12 % 12) + 1}"
    else:
        spoken = f"{h12} {m:02d}"
    return f"{spoken} {part}"


def say_name(key, fallback=""):
    return SPOKEN_NAME.get(key, fallback or key)


def say_title(text):
    """Names written for the eye read badly aloud: slashes, dashes, brackets."""
    t = (text or "").replace("/", " and ").replace("\u2013", " and ")
    t = t.replace("\u2014", ", ").replace(" - ", ", ")
    t = re.sub(r"\s+and\s+and\s+", " and ", t)
    return re.sub(r"\s+", " ", t).strip()


def _first_sentence(text, min_words=5):
    """First sentence, but only if it is actually a sentence - the profiles
    contain fragments like 'Days.' that mean nothing spoken."""
    for part in re.split(r"(?<=[.!?])\s+", _clean(text) or ""):
        if len(re.findall(r"[A-Za-z']+", part)) >= min_words:
            return part.rstrip(".") + "."
    return ""


def _clean(text):
    """Strip anything that reads badly aloud."""
    text = re.sub(r"\([^)]*\)", "", text or "")
    text = text.replace(" - ", ", ").replace("&", "and").replace("%", " percent")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,")


def build_script(payload):
    """Return the spoken brief as plain text."""
    risk = payload.get("risk") or {}
    af = payload.get("affairs") or {}
    az = payload.get("asia") or {}
    geo = payload.get("geo") or {}
    board = {r["key"]: r for r in payload.get("board") or []}
    groups = payload.get("groups") or []

    lines = []

    # --- open --------------------------------------------------------------
    band = (risk.get("band") or "").lower()
    words = {"low": "quiet", "moderate": "moderate",
             "high": "high risk", "extreme": "extreme risk"}.get(band, band)
    lines.append(f"Good morning. Today is {words}, "
                 f"scoring {risk.get('score', 0)} out of 100.")
    if risk.get("expected_range_usd"):
        lines.append(f"The options market is pricing gold to travel "
                     f"{say_money(risk['expected_range_usd'])} today.")

    # --- overnight ---------------------------------------------------------
    idx = az.get("indices") or []
    if idx:
        vals = [i["change_pct"] for i in idx if i.get("change_pct") is not None]
        if vals:
            avg = sum(vals) / len(vals)
            tone = ("lower" if avg <= -0.3 else "higher" if avg >= 0.3 else "mixed")
            lines.append(f"Asia finished {tone} overnight.")
    gold_on = next((m for m in az.get("moves", []) if m["key"] == "gold"), None)
    if gold_on:
        where = ("near the top of its overnight range" if gold_on["position"] >= 70
                 else "near the lows" if gold_on["position"] <= 30
                 else "in the middle of its range")
        lines.append(f"Gold {say_move(gold_on['change_pct'])} and comes into "
                     f"London {where}.")

    # --- the story ---------------------------------------------------------
    story = next((s for s in af.get("stories", []) if s["kind"] == "geopolitical"),
                 None) or next(iter(af.get("stories", [])), None)
    if story:
        lines.append("The story driving things is "
                     + (story.get("spoken") or say_title(story["title"])) + ".")
        if story.get("kind") == "geopolitical":
            state = story.get("state")
            if state in ("escalating", "flaring"):
                lines.append("It has stepped up above its own recent level, so "
                             "this is a change rather than more of the same.")
            elif state == "de-escalating":
                lines.append("It is calming down, so the risk premium it built "
                             "should be coming out rather than going in.")
            elif state == "steady":
                lines.append("It is running at about its usual level of noise, "
                             "which means the market has largely priced it.")
        why = story.get("spoken_why") or _first_sentence(story.get("detail"))
        if why:
            lines.append(why)

        gold_row = next((r for r in story.get("rows", []) if r["key"] == "gold"), None)
        if gold_row:
            lines.append(f"On the model that argues for gold "
                         f"{gold_row['expected_dir']}.")
            if gold_row["verdict"] == "consistent":
                lines.append("And gold is doing exactly that.")
            elif gold_row["verdict"] == "not following":
                lines.append("Gold is not following, which usually means it is "
                             "already in the price, or something else is "
                             "setting the tone today.")

        # what it means for the rest of the book, named rather than listed
        for r in [x for x in story.get("rows", []) if x["key"] != "gold"][:3]:
            verdict = ("and that is happening" if r["verdict"] == "consistent"
                       else "but it is going the other way"
                       if r["verdict"] == "not following" else "")
            lines.append(f"It argues for {say_name(r['key'], r['name'])} "
                         f"{r['expected_dir']}, {verdict}.".replace(" ,", ",")
                         .replace(", .", "."))

        if story.get("counterweight"):
            cw = _first_sentence(story["counterweight"])
            if cw:
                lines.append("Working against that, " + cw[0].lower() + cw[1:])
        dur = _first_sentence(story.get("duration"), min_words=6)
        if dur:
            lines.append("On how long it lasts, " + dur[0].lower() + dur[1:])

    # --- unscheduled backdrop ---------------------------------------------
    hot = [f for f in geo.get("flashpoints", [])
           if f.get("state") in ("escalating", "flaring")]
    if hot and (not story or hot[0]["name"] != story.get("title")):
        lines.append(f"Also worth knowing, {say_title(hot[0]['name'])} is above "
                     "its own normal level of noise.")
    elif geo.get("band") == "QUIET":
        lines.append("Nothing unusual is happening geopolitically.")

    # --- the calendar ------------------------------------------------------
    if groups:
        first = groups[0]
        lines.append(f"On the calendar, {_clean(first['lead'])} at "
                     f"{say_time(first['time'])}.")
        if len(groups) > 1:
            lines.append(f"Then {_clean(groups[1]['lead'])} at "
                         f"{say_time(groups[1]['time'])}.")
        base = (payload.get("base_rates") or {}).get(first["lead"])
        if base and base.get("by_surprise"):
            above = base["by_surprise"].get("above")
            if above:
                lines.append(f"When that has come in above forecast, gold has "
                             f"typically moved {say_money(above['median_move_1h'])} "
                             "in the hour after.")
    else:
        lines.append("There is nothing material on the calendar today, so gold "
                     "is left to the dollar and to headlines.")

    # --- other markets -----------------------------------------------------
    movers = [r for r in payload.get("board", [])
              if r["key"] != "gold" and r.get("change_pct") is not None]
    movers.sort(key=lambda r: -abs(r["change_pct"]))
    if movers:
        m = movers[0]
        lines.append(f"Away from gold, {say_name(m['key'], m['name'])} "
                     f"{say_move(m['change_pct'])}.")

    # --- close -------------------------------------------------------------
    cot = payload.get("cot")
    if cot and cot.get("crowded"):
        lines.append("Positioning is crowded, so a surprise against the trade "
                     "would move faster than usual.")
    # what would change the picture
    if story and story.get("kind") == "geopolitical":
        marker = _first_sentence((geo.get("flashpoints") or [{}])[0]
                                 .get("escalation_markers"), min_words=6)
        if marker:
            marker = re.split(r"[;,]", marker)[0].rstrip(".") + "."
            lines.append("What would change it, " + marker[0].lower() + marker[1:])
    elif groups:
        lines.append("The thing that would change the day is a surprise on that "
                     "release, in either direction.")

    lines.append("That is the brief. The full detail is on the dashboard.")

    return "\n".join(lines)


def write(payload, path=None):
    path = path or BRIEF_PATH
    script = build_script(payload)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(script + "\n")
    return script


def word_count(script):
    return len(re.findall(r"[A-Za-z']+", script))


def duration_estimate(script, wpm=150):
    return round(word_count(script) / wpm * 60)
