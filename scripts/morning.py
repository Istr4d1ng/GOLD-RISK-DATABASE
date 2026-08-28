"""Morning job: build today's risk report, dashboard and archive entry."""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import context
import narrate
import render
import risk as riskmod
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "data", "reports")
DOCS = os.path.join(ROOT, "docs")
DOCS_REPORTS = os.path.join(DOCS, "reports")


def safe(fn, default, label):
    try:
        return fn()
    except Exception as exc:                # noqa: BLE001
        print(f"[morning] {label} failed: {exc}")
        return default


def main():
    tz = ZoneInfo(config.DISPLAY_TZ)
    now = datetime.now(tz)
    today = now.date()

    print(f"[morning] building for {today}")

    raw_cal = safe(sources.fetch_calendar, [], "calendar")
    events = sources.parse_events(raw_cal, today) if raw_cal else []
    yday_events = sources.parse_events(
        raw_cal, today - timedelta(days=1)) if raw_cal else []
    print(f"[morning] {len(events)} USD events today, {len(yday_events)} yesterday")

    # Prices
    atr14 = atr_avg = None
    gold = {}
    daily_bars = []
    daily = safe(sources.gold_daily, None, "gold daily")
    if daily:
        symbol, bars = daily
        daily_bars = bars
        atr14 = sources.atr(bars, 14)
        atr_avg = sources.atr(bars, 60) or atr14
        last, chg = bars[-1]["c"], None
        if len(bars) > 1 and bars[-2]["c"]:
            chg = (bars[-1]["c"] - bars[-2]["c"]) / bars[-2]["c"] * 100
        gold = {"symbol": symbol, "last": last, "change_pct": chg}
        print(f"[morning] gold {symbol} {last:.2f} atr14={atr14:.2f}")

    news = safe(lambda: sources.fetch_news(hours=36), [], "news")
    print(f"[morning] {len(news)} relevant headlines")

    history = riskmod.load_history()
    scored = riskmod.score_day(events, atr14, atr_avg, history)
    classified = {e["title"]: riskmod.classify_event(e, history) for e in events}
    base_rates = {t: c["history"] for t, c in classified.items() if c["history"]}

    # Event context: what each release is, and what it has done before.
    ctx, fomc = safe(lambda: context.enrich(events, today, daily_bars),
                     ({}, None), "event context")
    if fomc:
        print(f"[morning] FOMC calendar via {fomc['source']}; "
              f"next meeting {fomc['status'].get('next')} "
              f"({fomc['status'].get('days_away')} days)")

    payload = {
        "date": today.isoformat(),
        "generated": now.strftime("%H:%M %Z"),
        "risk": scored,
        "events": events,
        "yesterday_events": yday_events,
        "news": news,
        "gold": gold,
        "classified": classified,
        "base_rates": base_rates,
        "context": ctx,
        "fomc": fomc,
    }

    narrative, mode = narrate.write_up(payload)
    print(f"[morning] narrative source: {mode}")

    os.makedirs(REPORTS, exist_ok=True)
    os.makedirs(DOCS_REPORTS, exist_ok=True)

    # --- markdown archive entry -------------------------------------------
    lines = [f"# Gold / USD risk report - {today}", "",
             f"**Risk {scored['score']}/100 - {scored['band']}**  ",
             f"{scored['band_note']}", "",
             f"- Expected gold range today: ${scored.get('expected_range_usd') or 0:,.1f}",
             f"- 14-day ATR: ${scored.get('atr14') or 0:,.2f}",
             f"- Volatility vs normal: {scored.get('vol_ratio') or 'n/a'}x", ""]
    if gold.get("last"):
        lines.append(f"- Gold last close: ${gold['last']:,.2f} "
                     f"({gold.get('change_pct') or 0:+.2f}%)")
        lines.append("")
    lines += ["## Today's USD calendar (UK time)", ""]
    if events:
        lines += ["| Time | Folder | Event | Gold wt | Forecast | Previous |",
                  "|---|---|---|---|---|---|"]
        for e in events:
            lines.append(f"| {e['local_time']} | {e['folder']} | {e['title']} | "
                         f"{e['weight']} | {e['forecast'] or '-'} | {e['previous'] or '-'} |")
    else:
        lines.append("_No USD events scheduled._")

    # --- per-event briefings ----------------------------------------------
    briefed = [e for e in events if e["weight"] >= config.MATERIAL_WEIGHT]
    if briefed:
        lines += ["", "## Event briefings", ""]
        for e in briefed:
            c = ctx.get(e["title"], {})
            prof = c.get("profile")
            lines.append(f"### {e['local_time']} - {e['title']}")
            lines.append("")
            if prof:
                lines += [f"**{prof['name']}** - {prof['what']}", "",
                          f"- _Published by:_ {prof['who']}",
                          f"- _Why gold cares:_ {prof['why_gold']}",
                          f"- _What to watch:_ {prof['watch']}",
                          f"- _Catch:_ {prof['gotchas']}",
                          f"- _Rough prior expectation:_ ${prof['prior_move_usd']}"]
            else:
                cl = classified.get(e["title"], {})
                lines.append(cl.get("expectation", ""))
                lines.append("")
                lines.append(cl.get("direction", ""))
            r = c.get("readings")
            if r and r.get("points"):
                lines += ["", f"Recent readings - {r['label']} (FRED {r['series']}):", ""]
                for pt in r["points"]:
                    chg = (f" ({pt['change']:+.2f}% m/m)"
                           if pt.get("change") is not None else "")
                    lines.append(f"- {pt['date']}: {pt['value']}{chg}")
            bs = base_rates.get(e["title"])
            if bs:
                lines += ["", f"Measured in this database: median 1h gold move "
                              f"${bs['median_move_1h']}, max ${bs['max_move_1h']}, "
                              f"n={bs['samples']}, {bs['sustained_rate']}% held into the close."]
            fh = c.get("fomc_gold_summary")
            if fh:
                lines += ["", f"Gold on the last {fh['samples']} FOMC decision days: "
                              f"average move ${fh['avg_abs_move']}, average range "
                              f"${fh['avg_range']}, biggest ${fh['biggest']}"
                              + (f", {fh['held_pct']}% carried into the next day."
                                 if fh.get("held_pct") is not None else ".")]
            lines.append("")

    if fomc and fomc.get("status", {}).get("next"):
        st = fomc["status"]
        lines += ["", "## FOMC cycle", "",
                  f"- Next meeting: **{st['next']}**, {st.get('days_away')} days away"
                  + (" (with projections / dot plot)" if st.get("has_projections") else ""),
                  f"- Last meeting: {st.get('last')}",
                  f"- Calendar source: {fomc.get('source')}"]
        gs = fomc.get("gold_summary")
        if gs:
            lines.append(f"- Gold on the last {gs['samples']} decision days: average "
                         f"move ${gs['avg_abs_move']}, average range ${gs['avg_range']}, "
                         f"biggest ${gs['biggest']}")

    lines += ["", "## Analysis", "", narrative, "", "## News (last 36h)", ""]
    for n in news[:15]:
        lines.append(f"- [{n['title']}]({n['link']}) - {n['source']}")
    if base_rates:
        lines += ["", "## Historical base rates (from this database)", ""]
        for t, h in base_rates.items():
            lines.append(f"- **{t}**: median 1h gold move ${h['median_move_1h']}, "
                         f"max ${h['max_move_1h']}, n={h['samples']}, "
                         f"{h['sustained_rate']}% held into the close")

    md_path = os.path.join(REPORTS, f"{today}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # --- machine-readable snapshot ----------------------------------------
    with open(os.path.join(ROOT, "data", "latest.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in payload.items() if k != "classified"},
                  fh, indent=2, default=str)

    # --- dashboard ---------------------------------------------------------
    archive = sorted((f[:-5] for f in os.listdir(DOCS_REPORTS)
                      if f.endswith(".html")), reverse=True)
    archive = [d for d in archive if d != str(today)]
    page = render.build_page(payload, narrative, [str(today)] + archive)
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(DOCS_REPORTS, f"{today}.html"), "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"[morning] wrote {md_path} and docs/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
