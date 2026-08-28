"""Morning job: build today's risk report, dashboard and archive entry."""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
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
    daily = safe(sources.gold_daily, None, "gold daily")
    if daily:
        symbol, bars = daily
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
