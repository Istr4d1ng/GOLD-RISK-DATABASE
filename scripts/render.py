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


def build_page(payload, narrative, archive=None):
    risk = payload["risk"]
    events = payload["events"]
    classified = payload.get("classified", {})
    gold = payload.get("gold", {})
    band = risk["band"]
    colour = BAND_COLOURS.get(band, "#6b7280")
    comp = risk["components"]

    archive_html = ""
    if archive:
        links = "".join(
            f'<a href="reports/{html.escape(d)}.html">{html.escape(d)}</a>'
            for d in archive[:20])
        archive_html = f'<section class="card"><h2>Archive</h2><div class="archive">{links}</div></section>'

    gold_line = ""
    if gold.get("last"):
        chg = gold.get("change_pct")
        cls = "up" if (chg or 0) >= 0 else "down"
        chg_txt = f'<span class="{cls}">{chg:+.2f}%</span>' if chg is not None else ""
        gold_line = (f'<div class="stat"><span class="k">Gold last close</span>'
                     f'<span class="v">${gold["last"]:,.2f} {chg_txt}</span></div>')

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
  .hero {{ display:flex; gap:24px; align-items:center; flex-wrap:wrap; }}
  .gauge {{ width:128px; height:128px; flex:none; }}
  .gauge-num {{ font-size:34px; font-weight:700; fill:var(--fg); }}
  .gauge-sub {{ font-size:12px; fill:var(--muted); }}
  .hero-body {{ flex:1; min-width:220px; }}
  .band {{ display:inline-block; font-size:12px; font-weight:700;
    letter-spacing:.08em; padding:4px 10px; border-radius:999px;
    background:{colour}22; color:{colour}; margin-bottom:8px; }}
  .stat {{ display:flex; justify-content:space-between; gap:12px;
    padding:7px 0; border-top:1px solid var(--line); font-size:14px; }}
  .stat .k {{ color:var(--muted); }}
  .stat .v {{ font-variant-numeric:tabular-nums; font-weight:600; }}
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
  .muted {{ color:var(--muted); }} .small {{ font-size:12.5px; line-height:1.45; }}
  ul.news {{ list-style:none; padding:0; margin:0; }}
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
  .bar {{ display:grid; grid-template-columns:110px 1fr 34px; gap:10px;
    align-items:center; font-size:12.5px; color:var(--muted); }}
  .bar i {{ display:block; height:6px; border-radius:3px; background:var(--accent);
    min-width:2px; }}
  .bar u {{ display:block; height:6px; border-radius:3px; background:var(--track); }}
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
      <p style="margin:0 0 10px">{html.escape(risk['band_note'])}</p>
      <div class="stat"><span class="k">Expected gold range today</span>
        <span class="v">${risk.get('expected_range_usd') or 0:,.1f}</span></div>
      <div class="stat"><span class="k">14-day ATR</span>
        <span class="v">${risk.get('atr14') or 0:,.2f}</span></div>
      <div class="stat"><span class="k">Volatility vs normal</span>
        <span class="v">{(str(risk.get('vol_ratio')) + 'x') if risk.get('vol_ratio') else '&ndash;'}</span></div>
      {gold_line}
    </div>
  </div>
  <div class="bars">
    <div class="bar"><span>Headline event</span><u><i style="width:{min(100, comp['headline_event']*100//70)}%"></i></u><span>{comp['headline_event']}</span></div>
    <div class="bar"><span>Event breadth</span><u><i style="width:{min(100, comp['breadth']*100//15 if comp['breadth'] else 0)}%"></i></u><span>{comp['breadth']}</span></div>
    <div class="bar"><span>Clustering</span><u><i style="width:{comp['clustering']*20}%"></i></u><span>{comp['clustering']}</span></div>
    <div class="bar"><span>Volatility</span><u><i style="width:{max(0, comp['volatility'])*10}%"></i></u><span>{comp['volatility']:+d}</span></div>
  </div>
</section>

<section class="card">
  <h2>Today&rsquo;s USD calendar &mdash; UK time</h2>
  {_events_table(events, classified)}
</section>

<section class="card analysis">
  <h2>Analysis</h2>
  {md_lite(narrative)}
</section>

<section class="card">
  <h2>USD news &mdash; last 36 hours</h2>
  {_news_list(payload.get('news', []))}
</section>

{archive_html}

<footer>
  Generated automatically from the ForexFactory calendar feed, public RSS and free
  price data.<br>Information only &mdash; not trading advice, and the risk score is a
  model, not a forecast.
</footer>
</div>
</body>
</html>"""
