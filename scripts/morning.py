"""Morning job: build today's risk report, dashboard and archive entry."""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asia
import assets as assetlib
import config
import context
import current_affairs
import geopolitics
import health
import market
import narrate
import reactions
import render
import risk as riskmod
import speech
import sources

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(ROOT, "data", "reports")
DOCS = os.path.join(ROOT, "docs")
DOCS_REPORTS = os.path.join(DOCS, "reports")


def main():
    tz = ZoneInfo(config.DISPLAY_TZ)
    now = datetime.now(tz)
    today = now.date()
    health.reset()

    print(f"[morning] building for {today}")

    # --- calendar ----------------------------------------------------------
    raw_cal = health.guard("ForexFactory calendar", sources.fetch_calendar, [],
                           lambda v: f"{len(v)} entries this week")
    events = sources.parse_events(raw_cal, today) if raw_cal else []
    yday_events = sources.parse_events(
        raw_cal, today - timedelta(days=1)) if raw_cal else []
    print(f"[morning] {len(events)} USD events today, {len(yday_events)} yesterday")

    # --- prices ------------------------------------------------------------
    daily_bars, atr14, atr_avg, gold = [], None, None, {}
    daily = health.guard("Gold daily prices", sources.gold_daily, None,
                         lambda v: f"{v[0]}, {len(v[1])} bars")
    if daily:
        symbol, daily_bars = daily
        atr14 = sources.atr(daily_bars, 14)
        atr_avg = sources.atr(daily_bars, 60) or atr14
        last = daily_bars[-1]["c"]
        chg = None
        if len(daily_bars) > 1 and daily_bars[-2]["c"]:
            chg = (last - daily_bars[-2]["c"]) / daily_bars[-2]["c"] * 100
        gold = {"symbol": symbol, "last": last, "change_pct": chg}
        print(f"[morning] gold {symbol} {last:.2f} atr14={atr14:.2f}")

    # --- market context ----------------------------------------------------
    implied = health.guard("GVZ implied volatility",
                           lambda: market.implied_vol(gold.get("last")), None,
                           lambda v: f"GVZ {v['gvz']}, {v['percentile_1y']}th pct")
    drivers = health.guard("Drivers (DXY, yields, TIPS)", market.drivers, {},
                           lambda v: ", ".join(sorted(v)))
    attribution = market.attribute(gold.get("change_pct"), drivers)
    cot = health.guard("CFTC positioning", market.cot_gold, None,
                       lambda v: f"net {v['net']:,} as of {v['as_of']}")
    overnight = health.guard(
        "Asia session",
        lambda: asia.summarise(raw_cal, today, tz, now), None,
        lambda v: f"{len(v['moves'])} assets, {len(v['indices'])} indices, "
                  f"{len(v['events'])} overnight releases")

    cross = health.guard("Cross-asset prices",
                         lambda: assetlib.fetch_bars("1y"), (None, []),
                         lambda v: f"{len(v[0])} of "
                                   f"{len(assetlib.load_assets())} assets")
    asset_bars = (cross or (None, []))[0] or {}
    board = assetlib.snapshot(asset_bars) if asset_bars else []
    corr = (assetlib.correlations(asset_bars) if len(asset_bars) > 3 else None)

    mmap = health.guard("Indices and sector stocks",
                        lambda: market.market_map(gold.get("change_pct")), None,
                        lambda v: f"{len(v['indices'])} indices, "
                                  f"{len(v['stocks'])} stocks, {v['appetite']}"
                                  + (f", {len(v['failed'])} failed" if v['failed'] else ""))

    # --- news and unscheduled risk ----------------------------------------
    news = health.guard("USD news feeds", lambda: sources.fetch_news(hours=36), [],
                        lambda v: f"{len(v)} relevant headlines")
    geo = health.guard("Geopolitical feeds",
                       lambda: geopolitics.assess(today=today), None,
                       lambda v: f"{v['band']} ({v['points']}), "
                                 f"{v['headline_count']} headlines, "
                                 f"baseline {'ready' if v['baseline_ready'] else 'building'}")
    if geo:
        # Today's counts become tomorrow's baseline. This is what stops a
        # long-running conflict reading SEVERE every day forever.
        if geopolitics.record(today, geo["flashpoints"]):
            print(f"[morning] recorded {len(geo['flashpoints'])} flashpoints "
                  f"to geo_history.csv")

    # --- context, scoring --------------------------------------------------
    hist = riskmod.load_history()
    ctx, fomc = health.guard("Event context / FOMC calendar",
                             lambda: context.enrich(events, today, daily_bars),
                             ({}, None),
                             lambda v: f"FOMC via {v[1]['source']}" if v[1] else "")
    profile_names = {t: (c.get("profile") or {}).get("name")
                     for t, c in ctx.items() if (c.get("profile") or {}).get("name")}

    scored = riskmod.score_day(events, atr14, atr_avg, hist, geo=geo,
                               implied=implied, cot=cot,
                               profile_names=profile_names)
    classified = {e["title"]: riskmod.classify_event(e, hist) for e in events}
    base_rates = {t: c["history"] for t, c in classified.items() if c["history"]}
    calib = riskmod.calibration()

    # Group co-published titles so one report is briefed once, not three times.
    groups = []
    for e in events:
        if e["weight"] < config.MATERIAL_WEIGHT:
            continue
        key = (e.get("release") or e["local_time"],
               profile_names.get(e["title"], e["title"]))
        for g in groups:
            if g["key"] == key:
                g["events"].append(e)
                break
        else:
            groups.append({"key": key, "time": e["local_time"], "events": [e]})
    for g in groups:
        g["lead"] = max(g["events"], key=lambda e: e["weight"])
        g["also"] = [e["title"] for e in g["events"] if e is not g["lead"]]

    affairs = health.guard(
        "Current affairs board",
        lambda: current_affairs.build(geo, news, board, overnight, events,
                                      context.load_profiles()),
        None,
        lambda v: f"{len(v['stories'])} live stories, "
                  f"{len(v['pending'])} pending releases")

    payload = {
        "date": today.isoformat(),
        "generated": now.strftime("%H:%M %Z"),
        "risk": scored,
        "events": events,
        "groups": [{"time": g["time"], "lead": g["lead"]["title"],
                    "also": g["also"]} for g in groups],
        "yesterday_events": yday_events,
        "news": news,
        "gold": gold,
        "implied": implied,
        "drivers": drivers,
        "attribution": attribution,
        "cot": cot,
        "market_map": mmap,
        "affairs": affairs,
        "asia": overnight,
        "board": board,
        "correlations": corr,
        "coverage": reactions.coverage(),
        "geo": geo,
        "classified": classified,
        "base_rates": base_rates,
        "context": ctx,
        "fomc": fomc,
        "calibration": calib,
        "health": health.summary(),
    }

    # The spoken brief is written from the same payload but for the ear, not
    # the eye - the readable page would be unbearable read aloud.
    try:
        script = speech.write(payload)
        payload["brief"] = {"words": speech.word_count(script),
                            "seconds": speech.duration_estimate(script),
                            "audio": f"audio/{today}.mp3"}
        print(f"[morning] spoken brief: {payload['brief']['words']} words, "
              f"about {payload['brief']['seconds']}s")
    except Exception as exc:                # noqa: BLE001
        print(f"[morning] spoken brief failed: {exc}")

    narrative, mode = narrate.write_up(payload)
    print(f"[morning] narrative source: {mode}")

    os.makedirs(REPORTS, exist_ok=True)
    os.makedirs(DOCS_REPORTS, exist_ok=True)
    write_markdown(today, payload, narrative, groups)

    with open(os.path.join(ROOT, "data", "latest.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in payload.items() if k != "classified"},
                  fh, indent=2, default=str)

    archive = sorted((f[:-5] for f in os.listdir(DOCS_REPORTS)
                      if f.endswith(".html")), reverse=True)
    archive = [d for d in archive if d != str(today)]
    page = render.build_page(payload, narrative, [str(today)] + archive,
                             payload["groups"])
    for path in (os.path.join(DOCS, "index.html"),
                 os.path.join(DOCS_REPORTS, f"{today}.html")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)

    # One page per asset and one per driver - the browsable knowledge side.
    all_assets, all_drivers = assetlib.load_assets(), assetlib.load_drivers()
    reaction_rows = reactions.load()
    a_dir = os.path.join(DOCS, "assets")
    d_dir = os.path.join(DOCS, "drivers")
    os.makedirs(a_dir, exist_ok=True)
    os.makedirs(d_dir, exist_ok=True)

    measured_by_asset = {}
    for title in {r["event"] for r in reaction_rows}:
        m = reactions.matrix_for_event(title, reaction_rows)
        for akey, stats in (m or {}).items():
            measured_by_asset.setdefault(akey, {})[title] = stats

    for akey, spec in all_assets.items():
        with open(os.path.join(a_dir, f"{akey}.html"), "w", encoding="utf-8") as fh:
            fh.write(render.build_asset_page(
                akey, spec, all_drivers, payload,
                measured=measured_by_asset.get(akey), corr=corr,
                all_assets=all_assets))

    profiles = context.load_profiles()
    for dkey, spec in all_drivers.items():
        informs = sorted({p.get("name") for p in profiles.values()
                          if isinstance(p, dict) and dkey in (p.get("drivers") or {})})
        with open(os.path.join(d_dir, f"{dkey}.html"), "w", encoding="utf-8") as fh:
            fh.write(render.build_driver_page(dkey, spec, all_assets, payload,
                                              events=informs))
    with open(os.path.join(a_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render.build_assets_index(board, all_assets))
    with open(os.path.join(d_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render.build_drivers_index(all_drivers, all_assets))
    print(f"[morning] wrote {len(all_assets)} asset pages and "
          f"{len(all_drivers)} driver pages, plus their indexes")

    # One page per flashpoint - level three of the geopolitical view.
    geo_dir = os.path.join(DOCS, "geo")
    os.makedirs(geo_dir, exist_ok=True)
    for fp in (geo or {}).get("flashpoints", []):
        with open(os.path.join(geo_dir, f"{fp['key']}.html"), "w",
                  encoding="utf-8") as fh:
            fh.write(render.build_geo_page(fp, payload, geo))
    with open(os.path.join(geo_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(render.build_geo_index(geo))

    # the full archive gets its own page; the dashboard keeps only the recent few
    with open(os.path.join(DOCS_REPORTS, "index.html"), "w",
              encoding="utf-8") as fh:
        fh.write(render.build_archive_index([str(today)] + archive))

    hs = payload["health"]
    print(f"[morning] wrote report; {hs['ok']} sources ok, {hs['failed']} failed")
    return 0


def write_markdown(today, payload, narrative, groups):
    scored, gold, geo = payload["risk"], payload["gold"], payload["geo"]
    events, ctx = payload["events"], payload["context"]
    base_rates, news = payload["base_rates"], payload["news"]

    L = [f"# Gold / USD risk report - {today}", "",
         f"**Risk {scored['score']}/100 - {scored['band']}**  ",
         f"{scored['band_note']}", "",
         f"- Scheduled risk {scored['scheduled']}/70, "
         f"unscheduled {scored['unscheduled']}/70",
         f"- Expected gold range today: ${scored.get('expected_range_usd') or 0:,.1f}"
         f" ({scored.get('range_source') or 'n/a'})",
         f"- 14-day ATR: ${scored.get('atr14') or 0:,.2f}"]
    if gold.get("last"):
        L.append(f"- Gold last close: ${gold['last']:,.2f} "
                 f"({gold.get('change_pct') or 0:+.2f}%)")
    if payload.get("attribution"):
        L.append(f"- Last move came through **{payload['attribution']['channel']}** "
                 f"- {payload['attribution']['note']}")
    if payload.get("cot"):
        c = payload["cot"]
        L.append(f"- Managed money net long {c['net']:,} contracts "
                 f"({c['percentile_2y']}th percentile of 2 years)")
    L.append("")

    if geo and geo.get("flashpoints"):
        L += [f"## Unscheduled risk - {geo['band']} ({geo['points']}/70)", "",
              geo["note"], ""]
        if not geo.get("baseline_ready"):
            L += [f"_Baselines are still building - {config.GEO_BASELINE_MIN} days "
                  f"of history are needed before a flashpoint can be called "
                  f"unusual. Until then these are absolute levels._", ""]
        for f in geo["flashpoints"][:5]:
            dev = (f"{f['sigma_volume']:+.2f} sigma vs its own normal of "
                   f"{f['baseline']}" if f.get("sigma_volume") is not None
                   else "no baseline yet")
            L.append(f"- **{f['name']}** - {f['state']}, {f['headlines']} headlines "
                     f"({dev}). {f['summary']}")
            if f.get("novel_markers"):
                L.append(f"  - New language today: {', '.join(f['novel_markers'])}")
        L.append("")

    af = payload.get("affairs")
    if af and af.get("stories"):
        L += ["", "## Current affairs and markets", ""]
        for st in af["stories"]:
            L.append(f"### {st['title']} ({st.get('state') or st['kind']})")
            L.append("")
            if st.get("detail"):
                L += [st["detail"], ""]
            L += ["| Asset | Model expects | Actually did | |", "|---|---|---|---|"]
            for r in st["rows"]:
                L.append(f"| {r['name']} | {r['expected_dir']} "
                         f"({r['expected']:+.2f}) | {r['observed']:+.2f}% | "
                         f"{r['verdict']} |")
            L += ["", st["read"], ""]
        if af.get("pending"):
            L += ["### Not happened yet", ""]
            for p in af["pending"]:
                up = ", ".join(f"{i['name']} {i['direction']}" for i in p["above"][:4])
                dn = ", ".join(f"{i['name']} {i['direction']}" for i in p["below"][:4])
                L += [f"**{p['time']} {p['name']}** - above forecast: {up}. "
                      f"Below forecast: {dn}.", ""]
        L += [f"_{af['caveat']}_", ""]

    az = payload.get("asia")
    if az:
        L += ["", f"## Asia overnight (to {az['cutoff']} UK)", ""]
        if az.get("read"):
            L += [az["read"], ""]
        if az.get("indices"):
            L += ["| Index | Last | Change |", "|---|---|---|"]
            for i in az["indices"]:
                L.append(f"| {i['label']} ({i['country']}) | {i['last']:,.2f} | "
                         f"{i['change_pct']:+.2f}% |")
            L.append("")
        if az.get("moves"):
            L += ["| Asset | Overnight | Range | Position in range |",
                  "|---|---|---|---|"]
            for m in az["moves"]:
                L.append(f"| {m['name']} | {m['change_pct']:+.2f}% | "
                         f"{m['range_pct']:.2f}% | {m['position']}% |")
            L.append("")
        if az.get("events"):
            L += ["Overnight releases:", ""]
            for ev in az["events"]:
                L.append(f"- {ev['local_time']} {ev['currency']} {ev['title']}"
                         + (f" (forecast {ev['forecast']}, prior {ev['previous']})"
                            if ev["forecast"] else ""))
            L.append("")
        L += [f"_{az['caveat']}_", ""]

    L += ["## Today's USD calendar (UK time)", ""]
    if events:
        L += ["| Time | Folder | Event | Gold wt | Forecast | Previous |",
              "|---|---|---|---|---|---|"]
        for e in events:
            L.append(f"| {e['local_time']} | {e['folder']} | {e['title']} | "
                     f"{e['weight']} | {e['forecast'] or '-'} | {e['previous'] or '-'} |")
    else:
        L.append("_No USD events scheduled._")

    if groups:
        L += ["", "## Event briefings", ""]
        for g in groups:
            lead = g["lead"]
            c = ctx.get(lead["title"], {})
            prof = c.get("profile")
            L.append(f"### {g['time']} - {prof['name'] if prof else lead['title']}")
            L.append("")
            if g["also"]:
                L += [f"_Published together with: {', '.join(g['also'])}._", ""]
            if prof:
                L += [prof["what"], "",
                      f"- _Published by:_ {prof['who']}",
                      f"- _Why gold cares:_ {prof['why_gold']}",
                      f"- _What to watch:_ {prof['watch']}",
                      f"- _Catch:_ {prof['gotchas']}",
                      f"- _Rough prior expectation:_ ${prof['prior_move_usd']}"]
            r = c.get("readings")
            if r and r.get("points"):
                L += ["", f"Recent readings - {r['label']} (FRED {r['series']}):", ""]
                for pt in r["points"]:
                    chg = (f" ({pt['change']:+.2f}% m/m)"
                           if pt.get("change") is not None else "")
                    L.append(f"- {pt['date']}: {pt['value']}{chg}")
            bs = base_rates.get(lead["title"])
            if bs:
                L += ["", f"Measured here: median 1h move ${bs['median_move_1h']}, "
                          f"max ${bs['max_move_1h']}, n={bs['samples']}, "
                          f"{bs['sustained_rate']}% held into the close."]
                for label, st in (bs.get("by_surprise") or {}).items():
                    L.append(f"  - {label}: ${st['median_move_1h']} (n={st['samples']})")
            L.append("")

    board = payload.get("board")
    if board:
        L += ["", "## Cross-asset board", "",
              "| Asset | Last | Day | 5d | 20d |", "|---|---|---|---|---|"]
        for r in board:
            L.append(f"| {r['name']} | {r['last']:,} | "
                     f"{r.get('change_pct') or 0:+.2f}% | "
                     f"{r.get('change_5d_pct') or 0:+.2f}% | "
                     f"{r.get('change_20d_pct') or 0:+.2f}% |")
        L.append("")
    corr = payload.get("correlations")
    if corr and corr.get("regime"):
        L += ["### Regime", "", corr["regime"], ""]
        if corr.get("notable"):
            L.append("Strongest current relationships with gold ("
                     + str(corr["window"]) + "-day): "
                     + ", ".join(f"{n['name']} {n['corr']:+.2f}"
                                 for n in corr["notable"]) + ".")
            L.append("")

    mm = payload.get("market_map")
    if mm:
        L += ["", "## Market map", "",
              f"**Risk appetite: {mm['appetite']}.** {mm['appetite_note']}", ""]
        if mm.get("miner_read"):
            L += [mm["miner_read"], ""]
        L += ["| Instrument | Last | Day |", "|---|---|---|"]
        for row in mm["indices"]:
            L.append(f"| {row['label']} | {row['last']:,.2f} | "
                     f"{row.get('change_pct') or 0:+.2f}% |")
        for row in mm["stocks"]:
            L.append(f"| {row['label']} ({row['sector']}) | {row['last']:,.2f} | "
                     f"{row.get('change_pct') or 0:+.2f}% |")
        L.append("")

    fomc = payload.get("fomc")
    if fomc and fomc.get("status", {}).get("next"):
        st = fomc["status"]
        L += ["## FOMC cycle", "",
              f"- Next meeting: **{st['next']}**, {st.get('days_away')} days away"
              + (" (with projections)" if st.get("has_projections") else ""),
              f"- Calendar source: {fomc.get('source')}", ""]

    calib = payload.get("calibration")
    if calib and calib.get("ready"):
        L += ["## Model calibration", "",
              f"- Over the last {calib['samples']} scored days the predicted range "
              f"was a median {calib['median_abs_error_pct']}% away from what "
              f"happened, and too wide {calib['over_predicted_pct']}% of the time.",
              ""]

    L += ["## Analysis", "", narrative, "", "## News (last 36h)", ""]
    for n in news[:15]:
        L.append(f"- [{n['title']}]({n['link']}) - {n['source']}")

    hs = payload["health"]
    L += ["", "## Data health", ""]
    for c in hs["checks"]:
        L.append(f"- {'ok  ' if c['ok'] else 'FAIL'} {c['source']}"
                 + (f" - {c['detail']}" if c["detail"] else ""))

    with open(os.path.join(REPORTS, f"{today}.md"), "w", encoding="utf-8") as fh:
        fh.write("\\n".join(L) + "\\n")


if __name__ == "__main__":
    raise SystemExit(main())
