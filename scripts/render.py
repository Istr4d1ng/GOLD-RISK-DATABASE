"""Builds the dashboard page. Self-contained HTML, no external requests."""

import html
import re
from datetime import datetime

import config

FOLDER_COLOURS = {"RED": "#e5484d", "ORANGE": "#f5a524",
                  "YELLOW": "#d9c40a", "GREY": "#6b7280"}
BAND_COLOURS = {"LOW": "#30a46c", "MODERATE": "#f5a524",
                "HIGH": "#f76808", "EXTREME": "#e5484d"}


def md_lite(text):
    """Minimal markdown -> HTML. Headings, bold, italics, links, lists."""
    out = []
    in_list = False
    for line in (text or "").split("\n"):
        s = line.rstrip()
        esc = html.escape(s)
        esc = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc)
        esc = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", esc)
        esc = re.sub(r"\[(.+?)\]\((https?://[^)\s]+)\)",
                     r'<a href="\2" target="_blank" rel="noopener">\1</a>', esc)
        if s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{esc[2:]}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if not s:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", s)
        if m:
            lvl = min(4, len(m.group(1)) + 1)
            out.append(f"<h{lvl}>{html.escape(m.group(2))}</h{lvl}>")
        else:
            out.append(f"<p>{esc}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def _gauge(score, band):
    colour = BAND_COLOURS.get(band, "#6b7280")
    circ = 2 * 3.14159 * 52
    dash = circ * min(score, 100) / 100
    return f"""
<svg viewBox="0 0 128 128" class="gauge" role="img" aria-label="Risk {score} of 100">
  <circle cx="64" cy="64" r="52" fill="none" stroke="var(--track)" stroke-width="12"/>
  <circle cx="64" cy="64" r="52" fill="none" stroke="{colour}" stroke-width="12"
          stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ:.1f}"
          transform="rotate(-90 64 64)"/>
  <text x="64" y="60" text-anchor="middle" class="gauge-num">{score}</text>
  <text x="64" y="82" text-anchor="middle" class="gauge-sub">/ 100</text>
</svg>"""


def _events_table(events, classified):
    if not events:
        return '<p class="muted">No USD events scheduled today.</p>'
    rows = []
    for e in events:
        c = classified.get(e["title"], {})
        hist = c.get("history")
        hist_txt = "&mdash;"
        if hist:
            hist_txt = (f'{hist["median_move_1h"]:.2f} median<br>'
                        f'<span class="muted">n={hist["samples"]}'
                        + (f', {hist["sustained_rate"]}% held' if hist.get("sustained_rate") is not None else "")
                        + "</span>")
        dot = FOLDER_COLOURS.get(e["folder"], "#6b7280")
        fc = html.escape(e["forecast"] or "&ndash;")
        pv = html.escape(e["previous"] or "&ndash;")
        rows.append(f"""
<tr class="{'major' if e['weight'] >= config.MAJOR_WEIGHT else ''}">
  <td class="time">{e['local_time']}</td>
  <td><span class="dot" style="background:{dot}"></span>{html.escape(e['title'])}
      <div class="muted small">{html.escape(c.get('direction',''))}</div></td>
  <td class="num">{e['weight']}</td>
  <td class="num">{fc}</td>
  <td class="num">{pv}</td>
  <td class="num small">{hist_txt}</td>
</tr>""")
    return f"""
<div class="scroll">
<table>
  <thead><tr><th>UK</th><th>Event</th><th>Gold wt</th><th>Fcst</th>
             <th>Prev</th><th>Past 1h move ($)</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
</div>"""


def _news_list(news):
    if not news:
        return '<p class="muted">No high-relevance USD headlines in the last 36 hours.</p>'
    items = []
    for n in news[:12]:
        link = html.escape(n.get("link") or "#")
        items.append(
            f'<li><a href="{link}" target="_blank" rel="noopener">'
            f'{html.escape(n["title"])}</a>'
            f'<span class="src">{html.escape(n["source"])}</span></li>')
    return f'<ul class="news">{"".join(items)}</ul>'



def _pct(v):
    return "&ndash;" if v is None else f"{v:+.2f}%"


def _signed(v):
    return "&ndash;" if v is None else f"{v:+.2f}"


def _readings_block(r):
    if not r or not r.get("points"):
        return ""
    pts = r["points"]
    vals = [p["value"] for p in pts]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    bars = "".join(
        f'<span class="spark" style="height:{6 + 30 * (v - lo) / span:.0f}px" '
        f'title="{html.escape(str(p["date"]))}: {v}"></span>'
        for p, v in zip(pts, vals))
    rows = "".join(
        f'<tr><td>{html.escape(p["date"])}</td><td class="num">{p["value"]}</td>'
        f'<td class="num muted">'
        f'{_pct(p.get("change"))}'
        f'</td></tr>' for p in reversed(pts))
    return f"""
<div class="readings">
  <div class="rlabel">{html.escape(r["label"])}
    <span class="muted">&middot; FRED {html.escape(r["series"])}</span></div>
  <div class="sparks">{bars}</div>
  <table class="mini"><tbody>{rows}</tbody></table>
</div>"""


def _fomc_history_table(rows):
    if not rows:
        return ""
    body = "".join(
        f'<tr><td>{html.escape(r["date"])}</td>'
        f'<td class="num {"up" if r["move"] >= 0 else "down"}">{r["move"]:+.2f}</td>'
        f'<td class="num">{r["range"]:.2f}</td>'
        f'<td class="num {"up" if (r["next_day"] or 0) >= 0 else "down"}">'
        f'{_signed(r.get("next_day"))}</td>'
        f'</tr>' for r in rows)
    return f"""
<table class="mini wide">
  <thead><tr><th>Decision day</th><th>Gold O&rarr;C</th><th>Day range</th>
             <th>Next day</th></tr></thead>
  <tbody>{body}</tbody></table>"""



STATE_COLOURS = {"escalating": "#e5484d", "active": "#f76808",
                 "simmering": "#f5a524", "de-escalating": "#30a46c",
                 "quiet": "#6b7280"}


def _event_details(groups, ctx, base_rates, classified):
    """One briefing per release - the payrolls report is one event, not three."""
    blocks = []
    for g in groups:
        lead = g["lead"]
        c = ctx.get(lead["title"], {})
        prof = c.get("profile")
        inner = []
        if g["also"]:
            inner.append('<p class="also">Published together with '
                         + html.escape(", ".join(g["also"]))
                         + ' &mdash; one release, one reaction.</p>')
        if prof:
            inner.append(f'<p class="lead">{html.escape(prof["what"])}</p>')
            inner.append('<dl class="facts">')
            for k, v in (("Published by", prof["who"]),
                         ("Why gold cares", prof["why_gold"]),
                         ("What to watch", prof["watch"]),
                         ("The catch", prof["gotchas"]),
                         ("Rough prior expectation", "$" + prof["prior_move_usd"])):
                inner.append(f"<dt>{k}</dt><dd>{html.escape(v)}</dd>")
            inner.append("</dl>")
        else:
            cl = classified.get(lead["title"], {})
            inner.append(f'<p class="lead">{html.escape(cl.get("expectation",""))}</p>')
            inner.append(f'<p class="muted">{html.escape(cl.get("direction",""))}</p>')

        inner.append(_readings_block(c.get("readings")))

        bs = base_rates.get(lead["title"])
        if bs:
            extra = ""
            by = bs.get("by_surprise") or {}
            if by:
                parts = " &middot; ".join(
                    f'{html.escape(k)} <b>${v["median_move_1h"]}</b> (n={v["samples"]})'
                    for k, v in by.items())
                extra = f'<br><span class="muted">Split by the print: {parts}</span>'
            inner.append(
                f'<p class="measured"><strong>Measured here:</strong> median 1h gold '
                f'move ${bs["median_move_1h"]}, max ${bs["max_move_1h"]}, '
                f'n={bs["samples"]}, {bs["sustained_rate"]}% held into the close.'
                f'{extra}</p>')
        else:
            inner.append('<p class="muted small">No measured history yet. The figures '
                         'above are a prior, not a statistic.</p>')

        fh = c.get("fomc_gold_summary")
        if fh:
            inner.append(
                f'<p class="measured"><strong>Gold on the last {fh["samples"]} FOMC '
                f'decision days:</strong> average move ${fh["avg_abs_move"]}, '
                f'average range ${fh["avg_range"]}, biggest ${fh["biggest"]}.</p>')
            inner.append(_fomc_history_table(c.get("fomc_gold_history")))

        name = prof["name"] if prof else lead["title"]
        dot = FOLDER_COLOURS.get(lead["folder"], "#6b7280")
        blocks.append(f"""
<details>
  <summary><span class="dot" style="background:{dot}"></span>
    <strong>{g['time']}</strong> {html.escape(name)}
    <span class="muted small">&mdash; weight {lead['weight']}</span></summary>
  <div class="detail">{''.join(inner)}</div>
</details>""")
    if not blocks:
        return '<p class="muted">Nothing material enough to brief today.</p>'
    return "".join(blocks)


def _geo_card(geo):
    if not geo:
        return ""
    colour = {"SEVERE": "#e5484d", "ELEVATED": "#f76808",
              "BACKGROUND": "#f5a524", "QUIET": "#30a46c"}.get(geo["band"], "#6b7280")
    rows = []
    for f in geo.get("flashpoints", [])[:6]:
        sc = STATE_COLOURS.get(f["state"], "#6b7280")
        heads = "".join(
            f'<li><a href="{html.escape(h.get("link") or "#")}" target="_blank" '
            f'rel="noopener">{html.escape(h["title"])}</a>'
            f'<span class="src">{html.escape(h["source"])} &middot; {h["tier"]}</span></li>'
            for h in f.get("top", []))
        rows.append(f"""
<details>
  <summary><span class="pill" style="background:{sc}22;color:{sc}">
    {html.escape(f['state'])}</span>
    <strong>{html.escape(f['name'])}</strong>
    <span class="muted small">&mdash; {f['headlines']} headlines, weight {f['weight']}</span></summary>
  <div class="detail">
    <dl class="facts">
      <dt>Why gold cares</dt><dd>{html.escape(f['why_gold'])}</dd>
      <dt>Working against it</dt><dd>{html.escape(f['counterweight'])}</dd>
      <dt>How long it lasts</dt><dd>{html.escape(f['typical_duration'])}</dd>
      <dt>What would escalate it</dt><dd>{html.escape(f['escalation_markers'])}</dd>
    </dl>
    <ul class="news">{heads}</ul>
  </div>
</details>""")
    body = "".join(rows) or '<p class="muted">No flashpoint activity detected.</p>'
    return f"""
<section class="card">
  <h2>Unscheduled risk &mdash; geopolitics</h2>
  <div class="stat"><span class="k">Level</span>
    <span class="v" style="color:{colour}">{html.escape(geo['band'])}
      &middot; {geo['points']}/70</span></div>
  <p style="margin:12px 0">{html.escape(geo['note'])}</p>
  {body}
  <p class="muted small" style="margin-top:12px">{html.escape(geo['caveat'])}</p>
</section>"""


def _drivers_card(drivers, attribution, cot):
    if not drivers and not cot:
        return ""
    rows = []
    for key in ("REAL10Y", "US10Y", "DXY"):
        d = drivers.get(key)
        if not d:
            continue
        if key == "REAL10Y":
            move = f'{d["change_5d_bp"]:+.1f}bp / 5d'
            cls = "up" if d["change_5d_bp"] >= 0 else "down"
        else:
            move = f'{d["change_pct"]:+.2f}%'
            cls = "up" if d["change_pct"] >= 0 else "down"
        rows.append(f'<div class="stat"><span class="k">{html.escape(d["label"])}</span>'
                    f'<span class="v">{d["last"]} '
                    f'<span class="{cls}">{move}</span></span></div>')
    attr = ""
    if attribution:
        attr = (f'<p class="measured"><strong>Gold\u2019s last move came through '
                f'{html.escape(attribution["channel"])}.</strong> '
                f'{html.escape(attribution["note"])}</p>')
    pos = ""
    if cot:
        spark = ""
        hist = cot.get("history") or []
        if len(hist) > 3:
            vals = [h["net"] for h in hist]
            lo, hi = min(vals), max(vals)
            span = (hi - lo) or 1
            spark = '<div class="sparks">' + "".join(
                f'<span class="spark" style="height:{6 + 30 * (v - lo) / span:.0f}px" '
                f'title="{html.escape(h["date"])}: {v:,}"></span>'
                for h, v in zip(hist, vals)) + "</div>"
        pos = f"""
  <h3 class="sub">Speculative positioning</h3>
  <div class="stat"><span class="k">Managed money net long</span>
    <span class="v">{cot['net']:,} contracts</span></div>
  <div class="stat"><span class="k">Percentile of last 2 years</span>
    <span class="v">{cot['percentile_2y']}th</span></div>
  <div class="stat"><span class="k">Change over 4 weeks</span>
    <span class="v">{(f"{cot['change_4w']:+,}" if cot.get('change_4w') is not None else '&ndash;')}</span></div>
  {spark}
  <p class="measured">{html.escape(cot['read'])}</p>
  <p class="muted small">CFTC, as of {html.escape(cot['as_of'])}. Published Fridays,
  reporting the prior Tuesday &mdash; always several days stale.</p>"""
    return f"""
<section class="card">
  <h2>What is driving gold</h2>
  {''.join(rows)}
  {attr}
  {pos}
</section>"""


def _calibration_card(calib):
    if not calib:
        return ""
    if not calib.get("ready"):
        return f"""
<section class="card">
  <h2>Model calibration</h2>
  <p class="muted">Scoring itself since setup: {calib.get('samples', 0)} days recorded,
  five needed before the error is worth reporting.</p>
</section>"""
    rows = "".join(
        f'<tr><td>{html.escape(str(r["date"]))}</td>'
        f'<td class="num">${r["predicted"]:,.0f}</td>'
        f'<td class="num">${r["realised"]:,.0f}</td>'
        f'<td class="num muted">{r["score"]}</td></tr>'
        for r in reversed(calib.get("recent", [])))
    return f"""
<section class="card">
  <h2>Model calibration</h2>
  <div class="stat"><span class="k">Median error vs the day that happened</span>
    <span class="v">{calib['median_abs_error_pct']}%</span></div>
  <div class="stat"><span class="k">Predicted too wide</span>
    <span class="v">{calib['over_predicted_pct']}% of days</span></div>
  <div class="stat"><span class="k">Days scored</span>
    <span class="v">{calib['samples']}</span></div>
  <div class="scroll"><table class="mini wide">
    <thead><tr><th>Date</th><th>Predicted</th><th>Realised</th><th>Risk</th></tr></thead>
    <tbody>{rows}</tbody></table></div>
  <p class="muted small" style="margin-top:10px">This is the page marking its own
  homework. If the error stays high or it is consistently too wide, the weights in
  config.py are wrong and should be changed.</p>
</section>"""


def _health_card(hs):
    if not hs or not hs.get("checks"):
        return ""
    items = "".join(
        f'<div class="hrow"><span class="hdot {"on" if c["ok"] else "off"}"></span>'
        f'<span>{html.escape(c["source"])}</span>'
        f'<span class="muted small">{html.escape(c["detail"] or ("failed" if not c["ok"] else ""))}</span></div>'
        for c in hs["checks"])
    warn = ""
    if hs.get("degraded"):
        warn = (f'<p class="measured">{hs["failed"]} source(s) did not answer this '
                f'morning, so parts of this page are missing rather than empty by '
                f'choice.</p>')
    return f"""
<section class="card">
  <h2>Data health</h2>
  {warn}
  <div class="health">{items}</div>
</section>"""


def _fomc_card(fomc):
    if not fomc or not fomc.get("status", {}).get("next"):
        return ""
    st = fomc["status"]
    gs = fomc.get("gold_summary")
    today_flag = ('<p class="measured"><strong>Today is a decision day.</strong></p>'
                  if st.get("is_today") else "")
    sep = " &middot; with projections (dot plot)" if st.get("has_projections") else ""
    summary = ""
    if gs:
        summary = (f'<div class="stat"><span class="k">Gold on the last '
                   f'{gs["samples"]} decision days</span><span class="v">'
                   f'avg ${gs["avg_abs_move"]} move, ${gs["avg_range"]} range</span></div>')
    return f"""
<section class="card">
  <h2>FOMC cycle</h2>
  {today_flag}
  <div class="stat"><span class="k">Next meeting</span>
    <span class="v">{html.escape(st['next'])} &middot; {st.get('days_away')} days{sep}</span></div>
  <div class="stat"><span class="k">Last meeting</span>
    <span class="v">{html.escape(str(st.get('last')))}</span></div>
  {summary}
  {_fomc_history_table(fomc.get('gold_history'))}
  <p class="muted small" style="margin-top:10px">Calendar source: {html.escape(fomc.get('source',''))}.</p>
</section>"""


def build_page(payload, narrative, archive=None, groups=None):
    risk = payload["risk"]
    events = payload["events"]
    classified = payload.get("classified", {})
    ctx = payload.get("context") or {}
    gold = payload.get("gold", {})
    implied = payload.get("implied") or {}
    base_rates = payload.get("base_rates") or {}
    band = risk["band"]
    colour = BAND_COLOURS.get(band, "#6b7280")
    comp = risk["components"]
    groups = groups or []

    archive_html = ""
    if archive:
        links = "".join(
            f'<a href="reports/{html.escape(d)}.html">{html.escape(d)}</a>'
            for d in archive[:20])
        archive_html = ('<section class="card"><h2>Archive</h2>'
                        f'<div class="archive">{links}</div></section>')

    gold_line = ""
    if gold.get("last"):
        chg = gold.get("change_pct")
        cls = "up" if (chg or 0) >= 0 else "down"
        chg_txt = f'<span class="{cls}">{chg:+.2f}%</span>' if chg is not None else ""
        gold_line = (f'<div class="stat"><span class="k">Gold last close</span>'
                     f'<span class="v">${gold["last"]:,.2f} {chg_txt}</span></div>')

    implied_line = ""
    if implied.get("gvz"):
        implied_line = (f'<div class="stat"><span class="k">Implied vol (GVZ)</span>'
                        f'<span class="v">{implied["gvz"]} &middot; '
                        f'{implied["percentile_1y"]}th pct of the year</span></div>')

    bars = [("Headline event", comp["headline_event"], 70),
            ("Event breadth", comp["breadth"], 15),
            ("Clustering", comp["clustering"], 5),
            ("Geopolitical", comp["geopolitical"], 70),
            ("Both at once", comp["both_at_once"], 15),
            ("Volatility", comp["volatility"], 10),
            ("Positioning", comp["positioning"], 5)]
    bar_html = "".join(
        f'<div class="bar"><span>{label}</span><u><i style="width:'
        f'{max(0, min(100, int(value * 100 / cap))) if cap else 0}%"></i></u>'
        f'<span>{value:+d}</span></div>' for label, value, cap in bars)

    return f"""<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(config.SITE_TITLE)}</title>
<style>
  :root {{
    --bg:#0d0f12; --card:#15181d; --line:#232830; --fg:#e8eaed;
    --muted:#9aa3af; --track:#232830; --accent:{colour};
  }}
  @media (prefers-color-scheme: light) {{
    :root:not([data-theme="dark"]) {{
      --bg:#f6f7f9; --card:#ffffff; --line:#e3e6ea; --fg:#14171c;
      --muted:#5d6673; --track:#e8ebef;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:20px 16px 64px; }}
  header {{ display:flex; justify-content:space-between; align-items:baseline;
    flex-wrap:wrap; gap:8px; margin-bottom:20px; }}
  h1 {{ font-size:19px; margin:0; letter-spacing:-.01em; }}
  .date {{ color:var(--muted); font-size:14px; font-variant-numeric:tabular-nums; }}
  .card {{ background:var(--card); border:1px solid var(--line);
    border-radius:14px; padding:20px; margin-bottom:16px; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:0 0 14px; font-weight:600; }}
  h3 {{ font-size:16px; margin:22px 0 6px; }}
  h3.sub {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--muted); margin:22px 0 10px; }}
  .hero {{ display:flex; gap:24px; align-items:center; flex-wrap:wrap; }}
  .gauge {{ width:128px; height:128px; flex:none; }}
  .gauge-num {{ font-size:34px; font-weight:700; fill:var(--fg); }}
  .gauge-sub {{ font-size:12px; fill:var(--muted); }}
  .hero-body {{ flex:1; min-width:220px; }}
  .band {{ display:inline-block; font-size:12px; font-weight:700;
    letter-spacing:.08em; padding:4px 10px; border-radius:999px;
    background:{colour}22; color:{colour}; margin-bottom:8px; }}
  .split {{ display:flex; gap:8px; margin-bottom:10px; flex-wrap:wrap; }}
  .split span {{ font-size:12px; padding:3px 9px; border-radius:6px;
    background:var(--track); color:var(--muted); }}
  .stat {{ display:flex; justify-content:space-between; gap:12px;
    padding:7px 0; border-top:1px solid var(--line); font-size:14px; }}
  .stat .k {{ color:var(--muted); }}
  .stat .v {{ font-variant-numeric:tabular-nums; font-weight:600; text-align:right; }}
  .up {{ color:#30a46c; }} .down {{ color:#e5484d; }}
  .scroll {{ overflow-x:auto; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; min-width:560px; }}
  th {{ text-align:left; color:var(--muted); font-weight:600; font-size:12px;
    text-transform:uppercase; letter-spacing:.05em; padding:0 10px 8px 0; }}
  td {{ padding:11px 10px 11px 0; border-top:1px solid var(--line);
    vertical-align:top; }}
  td.time {{ font-variant-numeric:tabular-nums; font-weight:600; white-space:nowrap; }}
  td.num {{ font-variant-numeric:tabular-nums; white-space:nowrap; }}
  tr.major td {{ background:{colour}0e; }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%;
    margin-right:8px; vertical-align:middle; }}
  .pill {{ font-size:10.5px; font-weight:700; letter-spacing:.06em;
    text-transform:uppercase; padding:3px 8px; border-radius:999px;
    margin-right:8px; white-space:nowrap; }}
  .muted {{ color:var(--muted); }} .small {{ font-size:12.5px; line-height:1.45; }}
  ul.news {{ list-style:none; padding:0; margin:8px 0 0; }}
  ul.news li {{ padding:10px 0; border-top:1px solid var(--line); font-size:14.5px; }}
  ul.news li:first-child {{ border-top:none; }}
  ul.news a {{ color:var(--fg); text-decoration:none; }}
  ul.news a:hover {{ text-decoration:underline; }}
  .src {{ display:block; color:var(--muted); font-size:12px; margin-top:2px; }}
  .archive {{ display:flex; flex-wrap:wrap; gap:8px; }}
  .archive a {{ font-size:13px; padding:5px 10px; border:1px solid var(--line);
    border-radius:8px; color:var(--muted); text-decoration:none;
    font-variant-numeric:tabular-nums; }}
  .analysis p {{ margin:0 0 12px; }}
  .analysis a {{ color:var(--accent); }}
  footer {{ color:var(--muted); font-size:12.5px; text-align:center;
    margin-top:28px; line-height:1.7; }}
  .bars {{ display:grid; gap:6px; margin-top:12px; }}
  .bar {{ display:grid; grid-template-columns:110px 1fr 40px; gap:10px;
    align-items:center; font-size:12.5px; color:var(--muted); }}
  .bar i {{ display:block; height:6px; border-radius:3px; background:var(--accent);
    min-width:2px; }}
  .bar u {{ display:block; height:6px; border-radius:3px; background:var(--track); }}
  details {{ border-top:1px solid var(--line); }}
  details:first-of-type {{ border-top:none; }}
  summary {{ cursor:pointer; padding:12px 0; font-size:14.5px; list-style:none;
    display:flex; align-items:baseline; gap:6px; flex-wrap:wrap; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary::before {{ content:"+"; color:var(--muted); font-weight:700;
    margin-right:4px; }}
  details[open] summary::before {{ content:"\2212"; }}
  .detail {{ padding:2px 0 18px 22px; font-size:14px; }}
  .detail .lead {{ margin:0 0 12px; }}
  .also {{ margin:0 0 10px; font-size:13px; color:var(--muted);
    border-left:2px solid var(--line); padding-left:10px; }}
  dl.facts {{ margin:0 0 14px; display:grid; grid-template-columns:auto 1fr;
    gap:6px 14px; font-size:13.5px; }}
  dl.facts dt {{ color:var(--muted); white-space:nowrap; }}
  dl.facts dd {{ margin:0; }}
  .measured {{ background:var(--track); border-radius:8px; padding:10px 12px;
    font-size:13.5px; margin:12px 0; }}
  .readings {{ margin:14px 0; }}
  .rlabel {{ font-size:12.5px; color:var(--fg); margin-bottom:6px; }}
  .sparks {{ display:flex; align-items:flex-end; gap:3px; height:38px;
    margin:10px 0 8px; }}
  .spark {{ flex:1; max-width:26px; background:var(--accent); opacity:.65;
    border-radius:2px 2px 0 0; }}
  table.mini {{ font-size:12.5px; min-width:0; }}
  table.mini td, table.mini th {{ padding:5px 14px 5px 0; }}
  table.mini.wide {{ width:100%; margin-top:8px; }}
  .health {{ display:grid; gap:8px; }}
  .hrow {{ display:grid; grid-template-columns:10px 1fr auto; gap:10px;
    align-items:baseline; font-size:13.5px; }}
  .hdot {{ width:8px; height:8px; border-radius:50%; }}
  .hdot.on {{ background:#30a46c; }} .hdot.off {{ background:#e5484d; }}
  @media (max-width:520px) {{
    dl.facts {{ grid-template-columns:1fr; gap:2px 0; }}
    dl.facts dt {{ margin-top:8px; }}
    .detail {{ padding-left:12px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{html.escape(config.SITE_TITLE)}</h1>
  <span class="date">{payload['date']} &middot; built {payload['generated']}</span>
</header>

<section class="card">
  <div class="hero">
    {_gauge(risk['score'], band)}
    <div class="hero-body">
      <span class="band">{band} RISK</span>
      <div class="split">
        <span>Scheduled {risk.get('scheduled', 0)}/70</span>
        <span>Unscheduled {risk.get('unscheduled', 0)}/70</span>
      </div>
      <p style="margin:0 0 10px">{html.escape(risk['band_note'])}</p>
      <div class="stat"><span class="k">Expected gold range today</span>
        <span class="v">${risk.get('expected_range_usd') or 0:,.1f}</span></div>
      <div class="stat"><span class="k">Range basis</span>
        <span class="v small">{html.escape(risk.get('range_source') or '&ndash;')}</span></div>
      {implied_line}
      {gold_line}
    </div>
  </div>
  <div class="bars">{bar_html}</div>
</section>

{_geo_card(payload.get('geo'))}

<section class="card">
  <h2>Today&rsquo;s USD calendar &mdash; UK time</h2>
  {_events_table(events, classified)}
</section>

<section class="card">
  <h2>Event briefings &mdash; what each one is and what it does to gold</h2>
  {_event_details(groups, ctx, base_rates, classified)}
</section>

{_drivers_card(payload.get('drivers') or {{}}, payload.get('attribution'), payload.get('cot'))}

{_fomc_card(payload.get('fomc'))}

<section class="card analysis">
  <h2>Analysis</h2>
  {md_lite(narrative)}
</section>

<section class="card">
  <h2>USD news &mdash; last 36 hours</h2>
  {_news_list(payload.get('news', []))}
</section>

{_calibration_card(payload.get('calibration'))}

{_health_card(payload.get('health'))}

{archive_html}

<footer>
  Built automatically from the ForexFactory calendar feed, public RSS, FRED, CFTC
  and free price data.<br>Information only &mdash; not trading advice, and the risk
  score is a model, not a forecast.
</footer>
</div>
</body>
</html>"""
