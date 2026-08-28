"""The written analysis layer.

Works with no configuration at all (deterministic template). If a
GEMINI_API_KEY environment variable is present, the same inputs are sent to a
model for a properly reasoned write-up instead. Any failure silently falls
back to the template, so the pipeline can never break because of this file.
"""

import json
import os
import urllib.request

import config

SYSTEM = """You are a macro analyst writing a pre-session briefing on gold (XAUUSD).
You are given today's scheduled US economic events, the last 36 hours of USD news,
and gold's recent price behaviour.

Write four short sections, in plain British English, no bullet-point padding:

1. YESTERDAY - what actually happened in USD news and how gold responded.
2. DURATION - for each meaningful story, say whether the effect is likely to be
   short-lived (a day or less) or long-lasting (weeks), and why. Be explicit that
   this is a judgement, and say when you are unsure.
3. TODAY - the scheduled events that matter, what a beat or miss does to gold,
   and which times deserve attention.
4. VERDICT - two or three sentences on the day's character.

Be concrete and quantitative where the data supports it. Never invent numbers,
prices, or events that are not in the input. If the data is thin, say so.
Do not give trading advice or tell the reader what position to take."""


def _template(payload):
    """Deterministic write-up used when no model key is configured."""
    ev = payload["events"]
    risk = payload["risk"]
    news = payload["news"][:5]
    major = [e for e in ev if e["weight"] >= config.MAJOR_WEIGHT]
    material = [e for e in ev if e["weight"] >= config.MATERIAL_WEIGHT]

    parts = []

    if news:
        lines = "\n".join(f"- **{n['title']}** ({n['source']})" for n in news)
        parts.append("### Yesterday\n\nThe USD stories carrying the most weight "
                     f"into today:\n\n{lines}\n")
    else:
        parts.append("### Yesterday\n\nNo high-relevance USD headlines were "
                     "picked up in the last 36 hours. A quiet news backdrop "
                     "usually means gold trades off technicals and the dollar "
                     "rather than fresh catalysts.\n")

    gold = payload.get("gold", {})
    if gold.get("last"):
        chg = gold.get("change_pct")
        move = f"{chg:+.2f}%" if chg is not None else "little changed"
        parts.append(f"Gold closed the prior session at ${gold['last']:,.2f}, "
                     f"{move} on the day. 14-day ATR is "
                     f"${risk.get('atr14') or 0:,.2f}, which is the yardstick "
                     "for whether today's move is normal or not.\n")

    if major:
        names = ", ".join(f"{e['title']} at {e['local_time']}" for e in major)
        parts.append(f"### Today\n\nRed-folder risk: {names} (UK time). These "
                     "are the prints that reprice rate expectations, and gold "
                     "moves through real yields, so treat the minutes either "
                     "side of them as unreliable for anything but reaction.\n")
    elif material:
        names = ", ".join(f"{e['title']} at {e['local_time']}" for e in material)
        parts.append(f"### Today\n\nNo top-tier releases. Secondary events: "
                     f"{names} (UK time). Expect spikes rather than trends.\n")
    else:
        parts.append("### Today\n\nNothing material on the USD calendar. Gold "
                     "is left to drift on positioning, the dollar and any "
                     "unscheduled headline.\n")

    parts.append(f"### Verdict\n\n{risk['band_note']} Risk score {risk['score']}"
                 f"/100 ({risk['band']}). Expected daily range around "
                 f"${risk.get('expected_range_usd') or 0:,.1f}.\n")

    parts.append("_Written by the deterministic template. Add a GEMINI_API_KEY "
                 "secret to get a reasoned write-up instead._")
    return "\n".join(parts)


def _gemini(payload, key):
    model = os.environ.get("GEMINI_MODEL", config.GEMINI_MODEL)
    url = config.GEMINI_URL.format(model=model) + f"?key={key}"
    slim = {
        "date": payload["date"],
        "risk": payload["risk"],
        "gold": payload.get("gold"),
        "events": [
            {k: e[k] for k in ("title", "local_time", "impact", "forecast",
                               "previous", "weight")} for e in payload["events"]
        ],
        "news": [{"title": n["title"], "source": n["source"],
                  "summary": n["summary"]} for n in payload["news"][:15]],
        "historical_base_rates": payload.get("base_rates", {}),
    }
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(slim, default=str)}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1600},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    cands = data.get("candidates") or []
    text = "".join(p.get("text", "")
                   for p in (cands[0].get("content", {}).get("parts") or []))
    if not text.strip():
        raise RuntimeError("empty model response")
    return text.strip()


def write_up(payload):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        try:
            return _gemini(payload, key), "model"
        except Exception as exc:            # noqa: BLE001
            print(f"[narrate] model call failed, using template: {exc}")
    return _template(payload), "template"
