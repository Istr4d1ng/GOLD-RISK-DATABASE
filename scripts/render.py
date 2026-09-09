"""Dashboard rendering.

Three levels of depth for the geopolitical layer:
  1. a compact row on the dashboard - state, deviation from its own baseline
  2. hold or hover - a popover with the intensity chart and the mechanism
  3. press - a full page per flashpoint, with every headline and its link
"""

import html
import re

import config

# --------------------------------------------------------------------------
# Palette. Semantic colour (risk band, escalation state) is deliberately kept
# separate from the brass accent that carries the page's identity.
# --------------------------------------------------------------------------
BAND_CLASS = {"LOW": "low", "MODERATE": "moderate", "HIGH": "high",
              "EXTREME": "extreme"}
STATE_CLASS = {"escalating": "extreme", "active": "high", "flaring": "high",
               "simmering": "moderate", "steady": "muted-state",
               "de-escalating": "low", "quiet": "muted-state"}
FOLDER_CLASS = {"RED": "f-red", "ORANGE": "f-orange", "YELLOW": "f-yellow",
                "GREY": "f-grey"}

CSS = """
:root {
  --bg:#f4f5f7; --surface:#ffffff; --sunken:#eceef2;
  --line:#e0e3e9; --line-soft:#eaedf1;
  --ink:#101319; --ink-2:#39414f; --muted:#6b7480;
  --brass:#8a6d1f; --brass-soft:#f2ead6;
  --low:#1f7a52; --moderate:#a8720c; --high:#c2521c; --extreme:#c0303c;
  --accent:var(--moderate);
  --shadow:0 1px 2px rgba(16,19,25,.05), 0 12px 32px -22px rgba(16,19,25,.45);
  --mono:"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans:"Archivo", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:#0a0c10; --surface:#12151c; --sunken:#171b23;
    --line:#212630; --line-soft:#1a1f27;
    --ink:#e9ecf1; --ink-2:#b9c1cd; --muted:#828c9c;
    --brass:#c9a227; --brass-soft:#2a2413;
    --low:#3fb27f; --moderate:#e0a030; --high:#ec7b40; --extreme:#e3596a;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 16px 40px -26px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"] {
  --bg:#0a0c10; --surface:#12151c; --sunken:#171b23;
  --line:#212630; --line-soft:#1a1f27;
  --ink:#e9ecf1; --ink-2:#b9c1cd; --muted:#828c9c;
  --brass:#c9a227; --brass-soft:#2a2413;
  --low:#3fb27f; --moderate:#e0a030; --high:#ec7b40; --extreme:#e3596a;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 16px 40px -26px rgba(0,0,0,.9);
}
[data-band="LOW"]      { --accent:var(--low); }
[data-band="MODERATE"] { --accent:var(--moderate); }
[data-band="HIGH"]     { --accent:var(--high); }
[data-band="EXTREME"]  { --accent:var(--extreme); }

* { box-sizing:border-box; }
html { -webkit-text-size-adjust:100%; }
body {
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--sans); font-size:15px; line-height:1.55;
  -webkit-font-smoothing:antialiased;
}
.wrap { max-width:960px; margin:0 auto; padding:0 18px 80px; }

/* ---- masthead ---- */
.top {
  position:sticky; top:0; z-index:40; background:var(--bg);
  border-bottom:1px solid var(--line); margin-bottom:26px;
  display:flex; align-items:center; justify-content:space-between;
  gap:14px; padding:13px 0; flex-wrap:wrap;
}
.brand { display:flex; align-items:baseline; gap:10px; min-width:0; }
.brand b { font-size:15px; font-weight:600; letter-spacing:-.01em; }
.brand .rule { width:22px; height:2px; background:var(--brass); flex:none; }
.stamp { font-family:var(--mono); font-size:11.5px; color:var(--muted);
  font-variant-numeric:tabular-nums; }

/* ---- hero ---- */
.hero { display:grid; grid-template-columns:minmax(0,1fr) 300px; gap:34px;
  align-items:start; padding-bottom:30px; border-bottom:1px solid var(--line); }
.score { display:flex; align-items:flex-start; gap:16px; }
.score .num { font-family:var(--mono); font-size:74px; line-height:.86;
  font-weight:600; letter-spacing:-.04em; color:var(--accent);
  font-variant-numeric:tabular-nums; }
.score .of { font-family:var(--mono); font-size:12px; color:var(--muted);
  padding-top:6px; }
.bandline { display:flex; align-items:center; gap:9px; margin:14px 0 8px; }
.chip { font-size:10.5px; font-weight:600; letter-spacing:.1em;
  text-transform:uppercase; padding:4px 9px; border-radius:5px;
  background:color-mix(in srgb, var(--accent) 15%, transparent);
  color:var(--accent); white-space:nowrap; }
.verdict { color:var(--ink-2); margin:0; max-width:46ch; }

.scale { margin-top:20px; }
.scale .track { position:relative; height:5px; border-radius:3px;
  background:linear-gradient(90deg, var(--low) 0 25%, var(--moderate) 25% 50%,
    var(--high) 50% 75%, var(--extreme) 75% 100%); opacity:.85; }
.scale .pin { position:absolute; top:-5px; width:3px; height:15px;
  border-radius:2px; background:var(--ink);
  box-shadow:0 0 0 3px var(--bg); }
.scale .ticks { display:flex; justify-content:space-between;
  font-family:var(--mono); font-size:10px; color:var(--muted); margin-top:7px; }

/* two-source split */
.split { display:grid; gap:11px; margin-top:24px; }
.srow { display:grid; grid-template-columns:96px 1fr 44px; gap:12px;
  align-items:center; font-size:12.5px; color:var(--muted); }
.srow u { display:block; height:7px; border-radius:4px; background:var(--sunken); }
.srow u i { display:block; height:7px; border-radius:4px; background:var(--accent);
  min-width:3px; }
.srow b { font-family:var(--mono); font-size:12px; color:var(--ink-2);
  text-align:right; font-weight:500; font-variant-numeric:tabular-nums; }

/* ---- glance panel ---- */
.glance { background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:6px 16px; box-shadow:var(--shadow); }
.g { display:flex; justify-content:space-between; align-items:baseline;
  gap:14px; padding:11px 0; border-top:1px solid var(--line-soft); }
.g:first-child { border-top:none; }
.g .k { font-size:12.5px; color:var(--muted); }
.g .v { font-family:var(--mono); font-size:13px; font-weight:500;
  text-align:right; font-variant-numeric:tabular-nums; }
.g .v small { display:block; font-family:var(--sans); font-size:11px;
  color:var(--muted); font-weight:400; }
.up { color:var(--low); } .down { color:var(--extreme); }

/* ---- sections ---- */
section { padding:26px 0; border-bottom:1px solid var(--line);
  scroll-margin-top:64px; }
section:last-of-type { border-bottom:none; }
h2 { font-size:11px; text-transform:uppercase; letter-spacing:.13em;
  color:var(--muted); font-weight:600; margin:0 0 4px; }
.lede { color:var(--muted); font-size:13.5px; margin:0 0 18px; max-width:62ch; }

/* ---- geopolitics rows ---- */
.geo { display:grid; gap:2px; }
.gr { position:relative; display:grid;
  grid-template-columns:112px minmax(0,1fr) 104px 70px 14px;
  gap:14px; align-items:center; padding:13px 10px; border-radius:9px;
  background:none; border:none; width:100%; text-align:left; cursor:pointer;
  color:inherit; font:inherit; -webkit-tap-highlight-color:transparent; }
.gr:hover, .gr:focus-visible { background:var(--sunken); outline:none; }
.gr:focus-visible { box-shadow:inset 0 0 0 2px var(--accent); }
.gr .name { font-size:14px; font-weight:500; min-width:0; }
.gr .name small { display:block; font-weight:400; font-size:11.5px;
  color:var(--muted); }
.gr .dev { font-family:var(--mono); font-size:12.5px; text-align:right;
  white-space:nowrap; font-variant-numeric:tabular-nums; }
.gr .arrow { color:var(--muted); font-size:15px; }
.state { font-size:10px; font-weight:600; letter-spacing:.08em;
  text-transform:uppercase; padding:3px 7px; border-radius:4px;
  text-align:center; white-space:nowrap; }
.state.extreme { background:color-mix(in srgb,var(--extreme) 16%,transparent); color:var(--extreme); }
.state.high { background:color-mix(in srgb,var(--high) 16%,transparent); color:var(--high); }
.state.moderate { background:color-mix(in srgb,var(--moderate) 16%,transparent); color:var(--moderate); }
.state.low { background:color-mix(in srgb,var(--low) 16%,transparent); color:var(--low); }
.state.muted-state { background:var(--sunken); color:var(--muted); }

.spark { display:block; width:100%; height:26px; overflow:visible; }
.spark .base { stroke:var(--muted); stroke-width:1; stroke-dasharray:2 3; opacity:.7; }
.spark .fill { fill:var(--accent); opacity:.14; }
.spark .line { fill:none; stroke:var(--accent); stroke-width:1.5;
  stroke-linejoin:round; }
.spark .tip { fill:var(--accent); }

/* ---- popover (level 2) ---- */
.pop { position:absolute; z-index:60; left:10px; right:10px; top:calc(100% - 6px);
  background:var(--surface); border:1px solid var(--line); border-radius:12px;
  box-shadow:var(--shadow); padding:16px 17px; display:none; }
.pop.on { display:block; animation:rise .14s ease-out; }
@keyframes rise { from { opacity:0; transform:translateY(-4px);} to { opacity:1; } }
.pop h4 { margin:0 0 2px; font-size:14px; font-weight:600; }
.pop .sub { font-family:var(--mono); font-size:11px; color:var(--muted);
  margin-bottom:12px; }
.pop p { margin:0 0 10px; font-size:13px; color:var(--ink-2); }
.pop .big { width:100%; height:56px; margin:4px 0 12px; }
.spark.tall { height:130px; margin:6px 0 4px; }
.pop .cta { font-size:11.5px; color:var(--muted); font-family:var(--mono); }

/* transmission chain */
.chain { display:flex; align-items:center; gap:7px; flex-wrap:wrap;
  margin:2px 0 12px; }
.chain span { font-size:11px; padding:4px 9px; border-radius:20px;
  background:var(--sunken); color:var(--ink-2); white-space:nowrap; }
.chain span.end { background:var(--brass-soft); color:var(--brass);
  font-weight:600; }
.chain b { color:var(--muted); font-size:11px; }

/* ---- tables ---- */
.scroll { overflow-x:auto; margin:0 -18px; padding:0 18px; }
table { width:100%; border-collapse:collapse; font-size:13.5px; min-width:540px; }
th { text-align:left; font-size:10.5px; text-transform:uppercase;
  letter-spacing:.09em; color:var(--muted); font-weight:600;
  padding:0 12px 9px 0; border-bottom:1px solid var(--line); }
td { padding:11px 12px 11px 0; border-bottom:1px solid var(--line-soft);
  vertical-align:top; }
td.t { font-family:var(--mono); font-size:12.5px; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
td.n { font-family:var(--mono); font-size:12.5px; white-space:nowrap;
  font-variant-numeric:tabular-nums; }
tr.major td { background:color-mix(in srgb, var(--accent) 6%, transparent); }
.fdot { display:inline-block; width:7px; height:7px; border-radius:50%;
  margin-right:8px; vertical-align:middle; }
.f-red { background:var(--extreme); } .f-orange { background:var(--high); }
.f-yellow { background:var(--moderate); } .f-grey { background:var(--muted); }

/* ---- disclosure ---- */
details { border-bottom:1px solid var(--line-soft); }
details:last-of-type { border-bottom:none; }
summary { cursor:pointer; padding:13px 0; list-style:none; display:flex;
  align-items:baseline; gap:9px; flex-wrap:wrap; font-size:14px; }
summary::-webkit-details-marker { display:none; }
summary::after { content:"+"; margin-left:auto; color:var(--muted);
  font-family:var(--mono); }
details[open] summary::after { content:"\\2212"; }
summary .tm { font-family:var(--mono); font-size:12.5px; color:var(--muted); }
.detail { padding:0 0 18px; font-size:13.5px; color:var(--ink-2);
  max-width:70ch; }
.detail p { margin:0 0 10px; }
dl { display:grid; grid-template-columns:auto 1fr; gap:7px 16px; margin:0 0 14px;
  font-size:13px; }
dt { color:var(--muted); white-space:nowrap; }
dd { margin:0; }
.note { background:var(--sunken); border-radius:8px; padding:11px 13px;
  font-size:13px; margin:12px 0; }
.also { border-left:2px solid var(--line); padding-left:11px; font-size:12.5px;
  color:var(--muted); margin:0 0 12px; }

/* ---- headline list ---- */
ul.heads { list-style:none; padding:0; margin:0; }
ul.heads li { padding:11px 0; border-bottom:1px solid var(--line-soft); }
ul.heads li:last-child { border-bottom:none; }
ul.heads a { color:var(--ink); text-decoration:none; font-size:13.5px; }
ul.heads a:hover { text-decoration:underline; }
ul.heads .meta { display:flex; gap:9px; margin-top:3px; font-family:var(--mono);
  font-size:10.5px; color:var(--muted); flex-wrap:wrap; }
.tier { padding:1px 6px; border-radius:3px; background:var(--sunken); }
.tier.severe { background:color-mix(in srgb,var(--extreme) 16%,transparent);
  color:var(--extreme); }

.archive { display:flex; flex-wrap:wrap; gap:7px; }
.archive a { font-family:var(--mono); font-size:11.5px; padding:5px 9px;
  border:1px solid var(--line); border-radius:7px; color:var(--muted);
  text-decoration:none; }
.archive a:hover { color:var(--ink); border-color:var(--muted); }

.quotes { display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
  gap:0 22px; margin-top:6px; }
.q { display:flex; justify-content:space-between; align-items:baseline; gap:12px;
  padding:9px 0; border-bottom:1px solid var(--line-soft); }
.ql { font-size:13px; }
.ql small { display:block; font-size:11px; color:var(--muted); }
.qv { font-family:var(--mono); font-size:12.5px; text-align:right;
  white-space:nowrap; font-variant-numeric:tabular-nums; }
.qv small { display:block; font-size:10.5px; color:var(--muted); }
a.q { text-decoration:none; color:inherit; }
a.q:hover .ql { color:var(--brass); }
.brasstag { font-size:9.5px; letter-spacing:.08em; text-transform:uppercase;
  color:var(--brass); border:1px solid var(--brass); border-radius:3px;
  padding:1px 4px; margin-left:6px; vertical-align:1px; }
.chip.up { background:color-mix(in srgb,var(--low) 15%,transparent); color:var(--low); }
.chip.down { background:color-mix(in srgb,var(--extreme) 15%,transparent); color:var(--extreme); }
.sens { position:relative; display:inline-block; width:54px; height:8px;
  background:var(--sunken); border-radius:2px; }
.sens::after { content:""; position:absolute; left:26.5px; top:-2px; width:1px;
  height:12px; background:var(--line); }
.sens i { position:absolute; top:0; height:8px; border-radius:2px; }
.sens i.up { background:var(--low); } .sens i.down { background:var(--extreme); }
.nav { display:flex; gap:2px; flex-wrap:wrap; margin:-8px 0 22px;
  border-bottom:1px solid var(--line); padding-bottom:10px; }
.nav a { font-size:12.5px; color:var(--muted); text-decoration:none;
  padding:6px 11px; border-radius:7px; white-space:nowrap; }
.nav a:hover { color:var(--ink); background:var(--sunken); }
.nav a.on { color:var(--ink); background:var(--sunken); font-weight:500; }
.nav.jump { border-bottom:none; margin:-16px 0 18px; padding-bottom:0; }
.nav.jump a { font-size:11.5px; padding:4px 9px; }
.brand a.home { text-decoration:none; color:inherit; display:flex;
  align-items:baseline; gap:10px; }
.filter { font:inherit; font-size:13px; padding:6px 11px; border-radius:8px;
  border:1px solid var(--line); background:var(--surface); color:var(--ink);
  min-width:180px; margin-left:6px; }
.filter:focus { outline:none; border-color:var(--muted); }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr));
  gap:10px; margin:6px 0 22px; }
.card { display:grid; gap:4px; padding:14px 15px; border:1px solid var(--line);
  border-radius:11px; background:var(--surface); text-decoration:none;
  color:inherit; }
.card:hover { border-color:var(--muted); }
.ct { font-size:14px; font-weight:500; }
.cv { font-family:var(--mono); font-size:12.5px; }
.cd { font-size:12.5px; color:var(--muted); line-height:1.45; }
.archive-item { font-family:var(--mono); font-size:12.5px; padding:6px 10px;
  border:1px solid var(--line); border-radius:7px; color:var(--muted);
  text-decoration:none; }
.archive-item:hover { color:var(--ink); border-color:var(--muted); }
.pending { border-top:1px solid var(--line-soft); padding:11px 0; }
.pending .pt { font-size:13.5px; margin-bottom:5px; }
.pending .ps { font-size:12.5px; color:var(--ink-2); padding:2px 0; }
.rng { position:relative; display:inline-block; width:46px; height:8px;
  background:var(--sunken); border-radius:2px; vertical-align:middle; }
.rng i { position:absolute; top:-2px; width:2px; height:12px; border-radius:1px;
  background:var(--accent); }
.health { display:grid; gap:7px; }
.hr { display:grid; grid-template-columns:8px 1fr auto; gap:11px;
  align-items:baseline; font-size:12.5px; }
.hd { width:7px; height:7px; border-radius:50%; background:var(--low); }
.hd.off { background:var(--extreme); }

footer { margin-top:34px; padding-top:22px; border-top:1px solid var(--line);
  color:var(--muted); font-size:12px; line-height:1.7; }
a { color:var(--brass); }
.back { display:inline-flex; align-items:center; gap:7px; font-size:12.5px;
  color:var(--muted); text-decoration:none; margin:20px 0 0; }
.back:hover { color:var(--ink); }

@media (max-width:820px) {
  .hero { grid-template-columns:1fr; gap:26px; }
}
@media (max-width:620px) {
  .gr { grid-template-columns:88px minmax(0,1fr) 62px;
    grid-template-areas:"state name dev" "state spark spark"; gap:8px 11px; }
  .gr .state-cell { grid-area:state; align-self:start; }
  .gr .name { grid-area:name; font-size:13.5px; }
  .gr .dev { grid-area:dev; font-size:12px; }
  .gr .spark-cell { grid-area:spark; }
  .gr .arrow { display:none; }
}
@media (max-width:560px) {
  .score .num { font-size:60px; }
  dl { grid-template-columns:1fr; gap:1px; }
  dt { margin-top:9px; }
}
@media (prefers-reduced-motion: reduce) { *, .pop.on { animation:none !important; } }
"""

JS = """
(function () {
  var open = null;
  function close() { if (open) { open.classList.remove('on'); open = null; } }
  function show(pop) {
    if (open === pop) return;
    close(); pop.classList.add('on'); open = pop;
  }
  document.querySelectorAll('[data-geo]').forEach(function (row) {
    var pop = row.parentNode.querySelector('.pop');
    var timer = null, held = false;
    if (window.matchMedia('(pointer:fine)').matches) {
      row.addEventListener('mouseenter', function () { show(pop); });
      row.parentNode.addEventListener('mouseleave', close);
    }
    row.addEventListener('focus', function () { show(pop); });
    row.addEventListener('touchstart', function () {
      held = false;
      timer = setTimeout(function () { held = true; show(pop); }, 320);
    }, { passive: true });
    ['touchend', 'touchcancel', 'touchmove'].forEach(function (e) {
      row.addEventListener(e, function () { clearTimeout(timer); }, { passive: true });
    });
    row.addEventListener('click', function (e) {
      if (held) { e.preventDefault(); held = false; return; }
      window.location.href = row.dataset.geo;
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
  });
  document.addEventListener('click', function (e) {
    if (open && !open.parentNode.contains(e.target)) close();
  });
})();
"""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def e(text):
    return html.escape(str(text if text is not None else ""))


def md_lite(text):
    """Minimal markdown -> HTML. Blank lines separate paragraphs, not newlines."""
    def inline(t):
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", t)
        return re.sub(r"\[(.+?)\]\((https?://[^)\s]+)\)",
                      r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)

    out, para, bullets = [], [], []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{inline(b)}</li>" for b in bullets)
                       + "</ul>")
            bullets.clear()
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    for raw in (text or "").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush()
            out.append(f"<h3>{html.escape(m.group(2))}</h3>")
            continue
        if line.startswith("- "):
            if para:
                flush()
            bullets.append(line[2:])
            continue
        if bullets:
            flush()
        para.append(line)
    flush()
    return "\n".join(out)


def sparkline(points, baseline=None, width=200, height=26, cls="spark"):
    """Daily intensity against the flashpoint's own baseline.

    The dashed line is normal for THIS flashpoint. Height above it is the part
    that is actually news rather than continuing coverage.
    """
    vals = [p.get("score", 0) or 0 for p in (points or [])]
    if len(vals) < 2:
        return '<div class="muted" style="font-size:11px">no history yet</div>'
    top = max(max(vals), (baseline or 0) * 1.4, 1)
    n = len(vals)
    step = width / (n - 1)

    def y(v):
        return round(height - (v / top) * (height - 3) - 1, 2)

    pts = [(round(i * step, 2), y(v)) for i, v in enumerate(vals)]
    line = " ".join(f"{x},{yy}" for x, yy in pts)
    area = f"{pts[0][0]},{height} " + line + f" {pts[-1][0]},{height}"
    base = ""
    if baseline is not None:
        by = y(baseline)
        base = (f'<line class="base" x1="0" y1="{by}" x2="{width}" y2="{by}"/>')
    lx, ly = pts[-1]
    return (f'<svg class="{cls}" viewBox="0 0 {width} {height}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon class="fill" points="{area}"/>{base}'
            f'<polyline class="line" points="{line}"/>'
            f'<circle class="tip" cx="{lx}" cy="{ly}" r="2.6"/></svg>')


def chain_html(chain):
    if not chain:
        return ""
    parts = []
    for i, node in enumerate(chain):
        last = i == len(chain) - 1
        parts.append(f'<span class="{"end" if last else ""}">{e(node)}</span>')
        if not last:
            parts.append("<b>&rarr;</b>")
    return f'<div class="chain">{"".join(parts)}</div>'


def dev_label(fp):
    """How far above its own normal this flashpoint is today."""
    sigma = fp.get("sigma")
    if sigma is None:
        return '<span class="muted">no baseline</span>'
    if sigma >= 0.75:
        cls = "down"       # elevated = red-ish, since it means more risk
        txt = f"+{sigma:.1f}σ"
    elif sigma <= -0.75:
        cls = "up"
        txt = f"{sigma:.1f}σ"
    else:
        cls = "muted"
        txt = "normal"
    return f'<span class="{cls}">{txt}</span>'


# --------------------------------------------------------------------------
# geopolitics
# --------------------------------------------------------------------------

def geo_rows(geo, prefix=""):
    rows = []
    for fp in (geo or {}).get("flashpoints", []):
        state_cls = STATE_CLASS.get(fp.get("state"), "muted-state")
        days = fp.get("days_active")
        sub = (f"{days} days running" if days
               else f"{fp.get('headlines', 0)} headlines")
        novel = fp.get("novel_markers") or []
        summary = fp.get("summary") or fp.get("why_gold", "")
        tone = {"extreme": "var(--extreme)", "high": "var(--high)",
                "moderate": "var(--moderate)", "low": "var(--low)",
                "muted-state": "var(--muted)"}[state_cls]
        rows.append(f"""
<div style="position:relative;--accent:{tone}">
  <button class="gr" data-geo="{prefix}geo/{e(fp['key'])}.html"
          aria-label="{e(fp['name'])} detail">
    <span class="state-cell"><span class="state {state_cls}">{e(fp.get('state',''))}</span></span>
    <span class="name">{e(fp['name'])}<small>{e(sub)}</small></span>
    <span class="spark-cell">{sparkline(fp.get('history'), fp.get('baseline'))}</span>
    <span class="dev">{dev_label(fp)}</span>
    <span class="arrow">&rsaquo;</span>
  </button>
  <div class="pop" role="dialog" aria-label="{e(fp['name'])} summary">
    <h4>{e(fp['name'])}</h4>
    <div class="sub">{e(fp.get('state','')).upper()}
      &middot; {fp.get('headlines', 0)} headlines today
      &middot; baseline {fp.get('baseline', 0):.1f}</div>
    {sparkline(fp.get('history'), fp.get('baseline'), width=320, height=56, cls="spark big")}
    {chain_html(fp.get('chain'))}
    <p>{e(summary)}</p>
    {('<p><strong>New today:</strong> ' + e(", ".join(novel)) + '</p>') if novel else ''}
    <div class="cta">Press for the full picture and every headline &rsaquo;</div>
  </div>
</div>""")
    if not rows:
        return '<p class="lede">No flashpoint activity in the last 48 hours.</p>'
    return f'<div class="geo">{"".join(rows)}</div>'


def build_geo_page(fp, payload, geo):
    """Level 3 - one page per flashpoint."""
    state_cls = STATE_CLASS.get(fp.get("state"), "muted-state")
    page_band = {"extreme": "EXTREME", "high": "HIGH", "moderate": "MODERATE",
                 "low": "LOW"}.get(state_cls, "MODERATE")
    heads = "".join(
        f'<li><a href="{e(h.get("link") or "#")}" target="_blank" rel="noopener">'
        f'{e(h["title"])}</a><div class="meta">'
        f'<span class="tier {"severe" if h.get("tier") == "severe" else ""}">'
        f'{e(h.get("tier",""))}</span>'
        f'<span>{e(h.get("source",""))}</span>'
        f'<span>{e((h.get("published") or "")[:16].replace("T", " "))}</span>'
        f'</div></li>' for h in (fp.get("all_headlines") or fp.get("top") or []))
    novel = fp.get("novel_markers") or []
    novel_html = ""
    if novel:
        novel_html = (f'<div class="note"><strong>Language that is new today:</strong> '
                      f'{e(", ".join(novel))}. New vocabulary is the strongest single '
                      f'sign that something changed rather than that the story is '
                      f'simply still being covered.</div>')

    return f"""<!doctype html>
<html lang="en" data-band="{page_band}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(fp['name'])} &mdash; {e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><a class="home" href="../index.html"><span class="rule"></span><b>{e(fp['name'])}</b></a></div>
    <span class="stamp">{e(payload['date'])}</span>
  </div>
  {nav_html("geo/index.html", 1)}

  <section style="padding-top:0">
    <div class="bandline">
      <span class="state {state_cls}">{e(fp.get('state',''))}</span>
      <span class="stamp">{fp.get('headlines', 0)} headlines today
        &middot; baseline {fp.get('baseline', 0):.1f}
        &middot; {dev_label(fp)}
        {('&middot; running ' + str(fp['days_active']) + ' days') if fp.get('days_active') else ''}</span>
    </div>
    {sparkline(fp.get('history'), fp.get('baseline'), width=880, height=130, cls="spark tall")}
    <p class="lede" style="margin-top:12px">Daily intensity for this flashpoint over
    the last {len(fp.get('history') or [])} days. The dashed line is its own normal.
    Only height above that line is news rather than continuing coverage.</p>
    {novel_html}
  </section>

  <section>
    <h2>How it reaches gold</h2>
    {chain_html(fp.get('chain'))}
    <dl>
      <dt>Why gold cares</dt><dd>{e(fp.get('why_gold'))}</dd>
      <dt>Working against it</dt><dd>{e(fp.get('counterweight'))}</dd>
      <dt>How long it lasts</dt><dd>{e(fp.get('typical_duration'))}</dd>
      <dt>What would escalate it</dt><dd>{e(fp.get('escalation_markers'))}</dd>
    </dl>
  </section>

  <section>
    <h2>Headlines</h2>
    <p class="lede">Everything matched to this flashpoint in the last 48 hours,
    newest first. Tier is how the language was read, not how important the story is.</p>
    <ul class="heads">{heads or '<li class="muted">Nothing in the window.</li>'}</ul>
  </section>

  <a class="back" href="../index.html">&lsaquo; Back to the dashboard</a>

  <footer>
    Matched from public news feeds. This measures how loud a story is, not what
    will happen &mdash; a quiet build-up nobody is writing about scores zero here.
  </footer>
</div>
</body>
</html>"""


# --------------------------------------------------------------------------
# dashboard pieces
# --------------------------------------------------------------------------

def calendar_table(events, classified):
    if not events:
        return '<p class="lede">No USD events scheduled today.</p>'
    rows = []
    for ev in events:
        c = classified.get(ev["title"], {})
        hist = c.get("history")
        h = "&mdash;"
        if hist:
            h = f'${hist["median_move_1h"]:.2f} <span class="muted">n={hist["samples"]}</span>'
        rows.append(f"""
<tr class="{'major' if ev['weight'] >= config.MAJOR_WEIGHT else ''}">
  <td class="t">{e(ev['local_time'])}</td>
  <td><span class="fdot {FOLDER_CLASS.get(ev['folder'],'f-grey')}"></span>{e(ev['title'])}</td>
  <td class="n">{ev['weight']}</td>
  <td class="n">{e(ev['forecast']) or '&ndash;'}</td>
  <td class="n">{e(ev['previous']) or '&ndash;'}</td>
  <td class="n">{h}</td>
</tr>""")
    return f"""<div class="scroll"><table>
  <thead><tr><th>UK</th><th>Event</th><th>Wt</th><th>Fcst</th><th>Prev</th>
    <th>Past 1h</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table></div>"""


def briefings(groups, ctx, base_rates):
    blocks = []
    for g in groups or []:
        lead = g["lead"]
        c = ctx.get(lead, {})
        prof = c.get("profile") or {}
        inner = []
        if g.get("also"):
            inner.append(f'<p class="also">Published together with '
                         f'{e(", ".join(g["also"]))} &mdash; one release, one reaction.</p>')
        if prof:
            inner.append(f"<p>{e(prof.get('what'))}</p><dl>"
                         + "".join(f"<dt>{k}</dt><dd>{e(v)}</dd>" for k, v in (
                             ("Why gold cares", prof.get("why_gold")),
                             ("What to watch", prof.get("watch")),
                             ("The catch", prof.get("gotchas")),
                             ("Rough prior", "$" + str(prof.get("prior_move_usd")))))
                         + "</dl>")
        br = base_rates.get(lead)
        if br:
            by = br.get("by_surprise") or {}
            split = ""
            if by:
                split = "<br>Split by the print: " + " &middot; ".join(
                    f'{e(k)} <strong>${v["median_move_1h"]}</strong> (n={v["samples"]})'
                    for k, v in by.items())
            inner.append(f'<div class="note"><strong>Measured here:</strong> median '
                         f'1h move ${br["median_move_1h"]}, n={br["samples"]}, '
                         f'{br["sustained_rate"]}% held into the close.{split}</div>')
        else:
            inner.append('<p class="muted" style="font-size:12.5px">No measured '
                         'history yet &mdash; the figures above are a prior, not a '
                         'statistic.</p>')
        blocks.append(f"""
<details>
  <summary><span class="tm">{e(g['time'])}</span>
    {e(prof.get('name') or lead)}</summary>
  <div class="detail">{''.join(inner)}</div>
</details>""")
    return "".join(blocks) or '<p class="lede">Nothing material to brief today.</p>'



APPETITE_CLASS = {"risk-off": "extreme", "risk-on": "low", "mixed": "muted-state"}


def market_map_section(mm):
    if not mm:
        return ""

    def rows(items, sector=False):
        out = []
        for r in items:
            chg = r.get("change_pct")
            cls = "up" if (chg or 0) >= 0 else "down"
            sub = (f'<small>{e(r.get("sector"))}</small>' if sector and r.get("sector")
                   else "")
            five = r.get("change_5d_pct")
            out.append(
                f'<div class="q"><span class="ql">{e(r["label"])}{sub}</span>'
                f'<span class="qv">{r["last"]:,.2f}'
                f'<span class="{cls}"> {chg:+.2f}%</span>'
                + (f'<small>{five:+.2f}% 5d</small>' if five is not None else "")
                + '</span></div>')
        return "".join(out)

    ap = APPETITE_CLASS.get(mm.get("appetite"), "muted-state")
    miner = (f'<div class="note">{e(mm["miner_read"])}</div>'
             if mm.get("miner_read") else "")
    failed = ""
    if mm.get("failed"):
        failed = (f'<p class="lede" style="margin:10px 0 0">Not fetched: '
                  f'{e(", ".join(mm["failed"][:6]))}.</p>')
    return f"""
<section>
  <h2>Market map</h2>
  <p class="lede">Indices and one liquid name per sector &mdash; here to answer a
  gold question, not as a quote board.</p>
  <div class="bandline" style="margin:0 0 12px">
    <span class="state {ap}">{e(mm.get('appetite', ''))}</span>
    <span class="stamp">cyclicals {mm.get('cyclical_avg')} vs defensives
      {mm.get('defensive_avg')}</span>
  </div>
  <div class="note">{e(mm.get('appetite_note', ''))}</div>
  {miner}
  <div class="quotes">{rows(mm.get('indices', []))}</div>
  <div class="quotes">{rows(mm.get('stocks', []), sector=True)}</div>
  {failed}
</section>"""



def _bar(score, width=54):
    """Signed sensitivity as a bar either side of a centre line."""
    pct = max(-1.0, min(1.0, score)) * (width / 2)
    left = width / 2 + (pct if pct < 0 else 0)
    cls = "up" if score > 0 else "down"
    return (f'<span class="sens"><i class="{cls}" style="left:{left:.1f}px;'
            f'width:{abs(pct):.1f}px"></i></span>')


def board_section(board, corr):
    if not board:
        return ""
    cells = []
    for r in board:
        chg = r.get("change_pct")
        cls = "up" if (chg or 0) >= 0 else "down"
        star = ' <span class="brasstag">primary</span>' if r.get("primary") else ""
        cells.append(
            f'<a class="q" href="assets/{e(r["key"])}.html">'
            f'<span class="ql">{e(r["name"])}{star}'
            f'<small>{(r.get("change_5d_pct") or 0):+.2f}% 5d &middot; '
            f'{(r.get("change_20d_pct") or 0):+.2f}% 20d</small></span>'
            f'<span class="qv">{r["last"]:,}'
            f'<span class="{cls}"> {chg:+.2f}%</span></span></a>')
    regime = ""
    if corr and corr.get("regime"):
        rel = ""
        if corr.get("notable"):
            rel = ('<div class="chain" style="margin-top:10px">'
                   + "".join(f'<span>{e(n["name"])} {n["corr"]:+.2f}</span>'
                             for n in corr["notable"]) + "</div>")
        regime = (f'<div class="note">{e(corr["regime"])}</div>{rel}'
                  f'<p class="lede" style="margin-top:8px">Rolling '
                  f'{corr["window"]}-day correlation of daily returns. These '
                  f'relationships move, which is the point of tracking them.</p>')
    return f"""
<section>
  <h2>Cross-asset board</h2>
  <p class="lede">The tracked set. Press any of them for what drives it and what
  it has measurably done.</p>
  <div class="quotes">{"".join(cells)}</div>
  {regime}
</section>"""


def _sens_rows(spec, drivers):
    rows = sorted(spec["sensitivity"].items(), key=lambda kv: -abs(kv[1]))
    out = []
    for key, score in rows:
        if abs(score) < 0.1:
            continue
        d = drivers[key]
        word = "up" if score > 0 else "down"
        out.append(
            f'<tr><td><a href="../drivers/{e(key)}.html">{e(d["name"])}</a>'
            f'<div class="muted small">{e(d["short"])}</div></td>'
            f'<td class="n">{_bar(score)}</td>'
            f'<td class="n">{score:+.2f}</td>'
            f'<td class="small">goes <strong>{word}</strong> when this rises</td></tr>')
    return "".join(out)


def build_asset_page(key, spec, drivers, payload, measured=None, corr=None,
                     all_assets=None):
    board = {r["key"]: r for r in payload.get("board", [])}
    row = board.get(key, {})
    chg = row.get("change_pct")
    cls = "up" if (chg or 0) >= 0 else "down"
    price = (f'<div class="score"><span class="num">{row["last"]:,}</span></div>'
             f'<div class="bandline"><span class="chip {cls}">{chg:+.2f}% today</span>'
             f'<span class="stamp">{(row.get("change_5d_pct") or 0):+.2f}% 5d '
             f'&middot; {(row.get("change_20d_pct") or 0):+.2f}% 20d</span></div>'
             if row else "")

    meas = '<p class="lede">No measured history yet for this asset. It starts ' \
           'accumulating from the first event logged after it was added.</p>'
    if measured:
        rws = "".join(
            f'<tr><td>{e(t)}</td><td class="n">{m["median_pct_1h"]:+.3f}%</td>'
            f'<td class="n">{m["samples"]}</td>'
            f'<td class="n">{m["sustained_rate"]}%</td></tr>'
            for t, m in measured.items())
        meas = (f'<div class="scroll"><table><thead><tr><th>Event</th>'
                f'<th>Median 1h</th><th>n</th><th>Held</th></tr></thead>'
                f'<tbody>{rws}</tbody></table></div>')

    corr_html = ""
    if corr and key in corr.get("matrix", {}):
        row_c = {k: v for k, v in corr["matrix"][key].items()
                 if k != key and v is not None}
        top = sorted(row_c.items(), key=lambda kv: -abs(kv[1]))[:6]
        names = {ak: av["name"] for ak, av in (all_assets or {}).items()}
        corr_html = ('<div class="chain">' + "".join(
            f'<span>{e(names.get(k, k))} {v:+.2f}</span>' for k, v in top)
            + "</div>")

    return f"""<!doctype html>
<html lang="en" data-band="MODERATE">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(spec['name'])} &mdash; {e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><a class="home" href="../index.html"><span class="rule"></span><b>{e(spec['name'])}</b></a></div>
    <span class="stamp">{e(payload['date'])} &middot; {e(spec['symbol'])}</span>
  </div>
  {nav_html("assets/index.html", 1)}

  <section style="padding-top:0">
    {price}
    <p class="verdict" style="max-width:70ch">{e(spec['what'])}</p>
    <div class="note">{e(spec['drives_it'])}</div>
  </section>

  <section>
    <h2>What moves it</h2>
    <p class="lede">Signed sensitivity to each driver. These are priors, not
    measurements &mdash; they are the starting opinion this database checks itself
    against.</p>
    <div class="scroll"><table><tbody>{_sens_rows(spec, drivers)}</tbody></table></div>
  </section>

  <section>
    <h2>Measured reactions</h2>
    <p class="lede">Median move in the hour after each event, from this
    database's own log.</p>
    {meas}
  </section>

  {f'<section><h2>Current relationships</h2>{corr_html}<p class="lede" style="margin-top:10px">Rolling {corr["window"]}-day correlation of daily returns.</p></section>' if corr_html else ''}

  <a class="back" href="../index.html">&lsaquo; Back to the dashboard</a>
  <footer>Priors are opinion; measured reactions are fact. Where they disagree,
  trust the measurement.</footer>
</div>
</body>
</html>"""


def build_driver_page(key, spec, assets, payload, events=None):
    rows = []
    for akey, a in assets.items():
        s = a["sensitivity"].get(key, 0)
        if abs(s) < 0.1:
            continue
        rows.append((abs(s), f'<tr><td><a href="../assets/{e(akey)}.html">'
                             f'{e(a["name"])}</a></td>'
                             f'<td class="n">{_bar(s)}</td>'
                             f'<td class="n">{s:+.2f}</td>'
                             f'<td class="small">goes '
                             f'<strong>{"up" if s > 0 else "down"}</strong></td></tr>'))
    rows.sort(key=lambda r: -r[0])
    ev = ""
    if events:
        ev = ('<div class="chain">' + "".join(f'<span>{e(t)}</span>'
                                              for t in events) + "</div>")
    return f"""<!doctype html>
<html lang="en" data-band="MODERATE">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(spec['name'])} &mdash; {e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><a class="home" href="../index.html"><span class="rule"></span><b>{e(spec['name'])}</b></a></div>
    <span class="stamp">driver</span>
  </div>
  {nav_html("drivers/index.html", 1)}
  <section style="padding-top:0">
    <p class="verdict" style="max-width:70ch">{e(spec['what'])}</p>
    <dl>
      <dt>How it propagates</dt><dd>{e(spec['propagates'])}</dd>
      <dt>It rises when</dt><dd>{e(spec['rises_when'])}</dd>
      <dt>What to watch</dt><dd>{e(spec['watch'])}</dd>
    </dl>
  </section>
  <section>
    <h2>If this rises</h2>
    <div class="scroll"><table><tbody>{"".join(r for _, r in rows)}</tbody></table></div>
  </section>
  {f'<section><h2>Events that inform it</h2>{ev}</section>' if ev else ''}
  <a class="back" href="../index.html">&lsaquo; Back to the dashboard</a>
  <footer>Sensitivities are priors, revised as the measured log grows.</footer>
</div>
</body>
</html>"""




NAV = [("index.html", "Today"), ("assets/index.html", "Assets"),
       ("drivers/index.html", "Drivers"), ("geo/index.html", "Flashpoints"),
       ("weekly/index.html", "Weekly"), ("reports/index.html", "Archive")]


def nav_html(active="", depth=0):
    """Site navigation. `depth` is how many folders down the page sits."""
    up = "../" * depth
    links = "".join(
        f'<a href="{up}{href}"' + (' class="on"' if href == active else "")
        + f'>{label}</a>' for href, label in NAV)
    return f'<nav class="nav">{links}</nav>'


def filter_box(placeholder="Filter"):
    return (f'<input class="filter" type="search" id="filter" '
            f'placeholder="{e(placeholder)}" aria-label="{e(placeholder)}" '
            f'autocomplete="off">')


FILTER_JS = """
(function () {
  var box = document.getElementById('filter');
  if (!box) return;
  var items = Array.prototype.slice.call(document.querySelectorAll('[data-find]'));
  var count = document.getElementById('filter-count');
  function apply() {
    var q = box.value.trim().toLowerCase();
    var shown = 0;
    items.forEach(function (el) {
      var hit = !q || el.dataset.find.indexOf(q) !== -1;
      el.hidden = !hit;
      if (hit) shown++;
    });
    if (count) count.textContent = q ? shown + ' of ' + items.length : '';
  }
  box.addEventListener('input', apply);
  box.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape') { box.value = ''; apply(); }
  });
})();
"""


def page_shell(title, body, active="", depth=0, extra_js="", band="MODERATE",
               stamp=""):
    """Every page in the site is built from this, so navigation is consistent."""
    up = "../" * depth
    return f"""<!doctype html>
<html lang="en" data-band="{e(band)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} &mdash; {e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><a class="home" href="{up}index.html"><span class="rule"></span>
      <b>{e(title)}</b></a></div>
    <span class="stamp">{e(stamp)}</span>
  </div>
  {nav_html(active, depth)}
  {body}
  <footer>
    <a href="{up}index.html">Dashboard</a> &middot;
    <a href="{up}assets/index.html">Assets</a> &middot;
    <a href="{up}drivers/index.html">Drivers</a> &middot;
    <a href="{up}geo/index.html">Flashpoints</a> &middot;
    <a href="{up}weekly/index.html">Weekly review</a> &middot;
    <a href="{up}reports/index.html">Archive</a>
    <br>Information only &mdash; not trading advice.
  </footer>
</div>
<script>{FILTER_JS}{extra_js}</script>
</body>
</html>"""


def build_assets_index(board, all_assets):
    by = {r["key"]: r for r in (board or [])}
    groups = {
        "Metals": ["gold", "silver", "copper"],
        "Equities": ["sp500", "nasdaq"],
        "Energy": ["oil"],
        "Rates and currency": ["us10y", "dollar", "eurusd", "usdjpy"],
        "Crypto and volatility": ["bitcoin", "vix"],
    }
    out = []
    for label, keys in groups.items():
        cards = []
        for k in keys:
            spec = all_assets.get(k)
            if not spec:
                continue
            row = by.get(k, {})
            chg = row.get("change_pct")
            move = (f'<span class="{"up" if (chg or 0) >= 0 else "down"}">'
                    f'{chg:+.2f}%</span>' if chg is not None else "")
            find = f'{k} {spec["name"]} {label}'.lower()
            cards.append(
                f'<a class="card" href="{e(k)}.html" data-find="{e(find)}">'
                f'<span class="ct">{e(spec["name"])}'
                + (' <span class="brasstag">primary</span>' if spec.get("primary") else "")
                + f'</span><span class="cv">{row.get("last", "")} {move}</span>'
                f'<span class="cd">{e(spec["drives_it"][:110])}&hellip;</span></a>')
        if cards:
            out.append(f'<h3 class="sub">{e(label)}</h3>'
                       f'<div class="cards">{"".join(cards)}</div>')
    body = f"""
<section style="padding-top:18px">
  <h2>Assets</h2>
  <p class="lede">Every tracked instrument, what drives it, and what it has
  measurably done. {filter_box("Filter assets")}
  <span class="muted small" id="filter-count"></span></p>
  {''.join(out)}
</section>"""
    return page_shell("Assets", body, active="assets/index.html", depth=1)


def build_drivers_index(all_drivers, all_assets):
    cards = []
    for key, spec in all_drivers.items():
        movers = sorted(((abs(a["sensitivity"].get(key, 0)), a["name"])
                         for a in all_assets.values()), reverse=True)[:3]
        top = ", ".join(n for _, n in movers)
        find = f'{key} {spec["name"]} {spec["short"]} {top}'.lower()
        cards.append(
            f'<a class="card" href="{e(key)}.html" data-find="{e(find)}">'
            f'<span class="ct">{e(spec["name"])}</span>'
            f'<span class="cd">{e(spec["short"])}</span>'
            f'<span class="cv muted small">moves {e(top)} most</span></a>')
    body = f"""
<section style="padding-top:18px">
  <h2>Drivers</h2>
  <p class="lede">The eight forces this database thinks markets actually move
  on. Every event maps to these, and every asset carries a signed sensitivity to
  each. {filter_box("Filter drivers")}
  <span class="muted small" id="filter-count"></span></p>
  <div class="cards">{''.join(cards)}</div>
</section>"""
    return page_shell("Drivers", body, active="drivers/index.html", depth=1)


def build_geo_index(geo):
    cards = []
    for fp in (geo or {}).get("flashpoints", []):
        cls = STATE_CLASS.get(fp.get("state"), "muted-state")
        find = f'{fp["key"]} {fp["name"]} {fp.get("state","")}'.lower()
        cards.append(
            f'<a class="card" href="{e(fp["key"])}.html" data-find="{e(find)}">'
            f'<span class="ct">{e(fp["name"])}</span>'
            f'<span class="cv"><span class="state {cls}">{e(fp.get("state",""))}</span></span>'
            f'<span class="cd">{e((fp.get("summary") or "")[:130])}</span></a>')
    body = f"""
<section style="padding-top:18px">
  <h2>Flashpoints</h2>
  <p class="lede">Unscheduled risk, each scored against its own recent normal.
  {filter_box("Filter flashpoints")}
  <span class="muted small" id="filter-count"></span></p>
  <div class="cards">{''.join(cards) or '<p class="lede">None active.</p>'}</div>
</section>"""
    return page_shell("Flashpoints", body, active="geo/index.html", depth=1)


def build_archive_index(dates):
    links = "".join(
        f'<a class="archive-item" href="{e(d)}.html" data-find="{e(d)}">{e(d)}</a>'
        for d in dates)
    body = f"""
<section style="padding-top:18px">
  <h2>Daily archive</h2>
  <p class="lede">Every report, newest first. {filter_box("Filter by date")}
  <span class="muted small" id="filter-count"></span></p>
  <div class="archive">{links}</div>
</section>"""
    return page_shell("Archive", body, active="reports/index.html", depth=1)


def build_weekly_page(payload, moves, shift, learn, clash, cov, calib):
    """The weekly cross-asset review."""
    mv = "".join(
        f'<tr><td><a href="../assets/{e(m["key"])}.html">{e(m["name"])}</a></td>'
        f'<td class="n">{m["last"]:,}</td>'
        f'<td class="n {"up" if m["change_pct"] >= 0 else "down"}">'
        f'{m["change_pct"]:+.2f}%</td>'
        f'<td class="n muted">{m["range_pct"]:.2f}%</td></tr>' for m in moves)

    sh = ""
    if shift and shift.get("rows"):
        rws = "".join(
            f'<tr><td>{e(r["name"])}</td><td class="n">{r["recent"]:+.2f}</td>'
            f'<td class="n muted">{r["usual"]:+.2f}</td>'
            f'<td class="n {"up" if r["shift"] >= 0 else "down"}">'
            f'{r["shift"]:+.2f}</td></tr>' for r in shift["rows"][:10])
        sh = f"""
<section>
  <h2>What moved together</h2>
  <p class="lede">Correlation with the primary asset over {shift['short']} days
  against its {shift['long']}-day norm. The shift column is the one that matters
  &mdash; a relationship changing tells you more than its level.</p>
  <div class="scroll"><table>
    <thead><tr><th>Asset</th><th>Recent</th><th>Usual</th><th>Shift</th></tr></thead>
    <tbody>{rws}</tbody></table></div>
</section>"""

    lr = ('<p class="lede">Nothing has three samples yet. Weekly releases get '
          'there in about a month, monthly ones in a quarter.</p>')
    if learn:
        rws = "".join(
            f'<tr><td>{e(r["event"])}</td>'
            f'<td><a href="../assets/{e(r["asset"])}.html">{e(r["name"])}</a></td>'
            f'<td class="n">{r["median"]:.3f}%</td>'
            f'<td class="n muted">{r["samples"]}</td></tr>' for r in learn[:20])
        lr = (f'<p class="lede">{cov["rows"]} reactions across {cov["events"]} '
              f'events and {cov["assets"]} assets over {cov["days"]} days.</p>'
              f'<div class="scroll"><table><thead><tr><th>Event</th><th>Asset</th>'
              f'<th>Median 1h</th><th>n</th></tr></thead><tbody>{rws}</tbody>'
              f'</table></div>')

    cl = ""
    if clash:
        items = "".join(
            f'<li><strong>{e(r["event"])} &rarr; {e(r["name"])}</strong>: expected '
            f'{e(r["expected_dir"])} ({r["expected"]:+.2f}), measured '
            f'{r["signed"]:+.3f}% over {r["samples"]} instances</li>'
            for r in clash[:10])
        cl = f"""
<section>
  <h2>Where the model is wrong</h2>
  <p class="lede">The measured direction contradicts the prior in assets.json.
  These are the lines to change &mdash; the measurement is the fact, the prior is
  an opinion.</p>
  <ul class="heads">{items}</ul>
</section>"""

    cal = ""
    if calib and calib.get("ready"):
        cal = (f'<div class="note">Predicted range was a median '
               f'<strong>{calib["median_abs_error_pct"]}%</strong> from the '
               f'realised range over {calib["samples"]} scored days, and too wide '
               f'{calib["over_predicted_pct"]}% of the time.</div>')

    return f"""<!doctype html>
<html lang="en" data-band="MODERATE">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weekly review &mdash; {e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="brand"><a class="home" href="../index.html"><span class="rule"></span><b>Weekly cross-asset review</b></a></div>
    <span class="stamp">week ending {e(payload['date'])}</span>
  </div>
  {nav_html("weekly/index.html", 1)}
  <section style="padding-top:0">
    <h2>What moved</h2>
    <div class="scroll"><table>
      <thead><tr><th>Asset</th><th>Last</th><th>Week</th><th>Range</th></tr></thead>
      <tbody>{mv}</tbody></table></div>
  </section>
  {sh}
  <section>
    <h2>What the log has learned</h2>
    {lr}
  </section>
  {cl}
  <section>
    <h2>Calibration</h2>
    {cal or '<p class="lede">Not enough scored days yet.</p>'}
  </section>
  <a class="back" href="../index.html">&lsaquo; Back to the dashboard</a>
  <footer>Written weekly from the reaction log. Priors are opinion; measured
  reactions are fact.</footer>
</div>
</body>
</html>"""



def asia_section(az):
    if not az:
        return ""
    idx = "".join(
        f'<div class="q"><span class="ql">{e(i["label"])}'
        f'<small>{e(i["country"])}</small></span>'
        f'<span class="qv">{i["last"]:,.2f}'
        f'<span class="{"up" if i["change_pct"] >= 0 else "down"}"> '
        f'{i["change_pct"]:+.2f}%</span></span></div>' for i in az.get("indices", []))

    rows = "".join(
        ('<tr class="major">' if m.get("primary") else '<tr>')
        + f'<td><a href="assets/{e(m["key"])}.html">{e(m["name"])}</a></td>'
        + f'<td class="n {"up" if m["change_pct"] >= 0 else "down"}">'
        + f'{m["change_pct"]:+.2f}%</td>'
        + f'<td class="n muted">{m["range_pct"]:.2f}%</td>'
        + f'<td class="n">{_range_pos(m["position"])}</td></tr>'
        for m in az.get("moves", []))

    evs = ""
    if az.get("events"):
        evs = ('<div class="scroll"><table><thead><tr><th>UK</th><th>Release</th>'
               '<th>Fcst</th><th>Prev</th></tr></thead><tbody>' + "".join(
                   f'<tr><td class="t">{e(ev["local_time"])}</td>'
                   f'<td><span class="fdot {FOLDER_CLASS.get(ev["folder"],"f-grey")}">'
                   f'</span>{e(ev["currency"])} {e(ev["title"])}</td>'
                   f'<td class="n">{e(ev["forecast"]) or "&ndash;"}</td>'
                   f'<td class="n">{e(ev["previous"]) or "&ndash;"}</td></tr>'
                   for ev in az["events"]) + "</tbody></table></div>")

    return f"""
<section>
  <h2>Asia overnight &mdash; to {e(az['cutoff'])} UK</h2>
  {f'<div class="note">{e(az["read"])}</div>' if az.get('read') else ''}
  {f'<div class="quotes">{idx}</div>' if idx else ''}
  {f'<div class="scroll" style="margin-top:14px"><table><thead><tr><th>Asset</th><th>Overnight</th><th>Range</th><th>In range</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else ''}
  {f'<h3 class="sub">Overnight releases</h3>{evs}' if evs else ''}
  <p class="lede" style="margin-top:12px">{e(az.get('caveat', ''))}</p>
</section>"""


def _range_pos(pos):
    """Where in the overnight range it sits, as a small position bar."""
    return (f'<span class="rng"><i style="left:{max(0, min(96, pos)):.0f}%"></i>'
            f'</span><span class="muted small"> {pos}%</span>')



VERDICT_CLASS = {"consistent": "low", "not following": "extreme", "flat": "muted-state"}


def affairs_section(af):
    if not af or not (af.get("stories") or af.get("pending")):
        return ""

    cards = []
    for st in af.get("stories", []):
        rows = "".join(
            f'<tr><td><a href="assets/{e(r["key"])}.html">{e(r["name"])}</a>'
            + ('<span class="muted small"> conflicted</span>' if r.get("conflict") else "")
            + f'</td>'
            + f'<td class="n">{"up" if r["expected"] > 0 else "down"} '
            + f'<span class="muted">({r["expected"]:+.2f})</span></td>'
            + f'<td class="n {"up" if r["observed"] >= 0 else "down"}">'
            + f'{r["observed"]:+.2f}%</td>'
            + f'<td><span class="state {VERDICT_CLASS.get(r["verdict"], "muted-state")}">'
            + f'{e(r["verdict"])}</span></td></tr>' for r in st.get("rows", []))
        heads = ""
        if st.get("headlines"):
            heads = ('<ul class="heads">' + "".join(
                f'<li><a href="{e(h.get("link") or "#")}" target="_blank" '
                f'rel="noopener">{e(h["title"])}</a>'
                f'<div class="meta"><span>{e(h.get("source", ""))}</span></div></li>'
                for h in st["headlines"]) + "</ul>")
        why = ""
        if st.get("why"):
            why = (f'<dl><dt>Why it reaches markets</dt><dd>{e(st["why"])}</dd>'
                   + (f'<dt>Working against it</dt><dd>{e(st["counterweight"])}</dd>'
                      if st.get("counterweight") else "")
                   + (f'<dt>How long it lasts</dt><dd>{e(st["duration"])}</dd>'
                      if st.get("duration") else "") + "</dl>")
        cards.append(f"""
<details>
  <summary><span class="state {'high' if st['kind'] == 'geopolitical' else 'muted-state'}">
    {e(st.get('state') or st['kind'])}</span>
    <strong>{e(st['title'])}</strong>
    <span class="muted small">&mdash; {e(st['read'][:74])}</span></summary>
  <div class="detail">
    {'<p class="also">This one is easing, so the model applies its drivers in reverse - the risk premium it created should be coming out, not going in.</p>' if st.get('easing') else ''}
    {f'<p>{e(st["detail"])}</p>' if st.get('detail') else ''}
    {chain_html(st.get('chain'))}
    {why}
    <div class="scroll"><table>
      <thead><tr><th>Asset</th><th>Model expects</th><th>Actually did</th>
        <th></th></tr></thead><tbody>{rows}</tbody></table></div>
    <div class="note">{e(st['read'])}</div>
    {heads}
    <p><a href="{e(st['link'])}">More on this &rsaquo;</a></p>
  </div>
</details>""")

    pend = ""
    if af.get("pending"):
        blocks = []
        for p in af["pending"]:
            def side(items):
                return " &middot; ".join(
                    f'{e(i["name"])} <strong>{e(i["direction"])}</strong>'
                    for i in items[:4])
            blocks.append(
                f'<div class="pending"><div class="pt"><span class="tm">'
                f'{e(p["time"])}</span> {e(p["name"])}</div>'
                f'<div class="ps"><span class="muted">above forecast:</span> '
                f'{side(p["above"])}</div>'
                f'<div class="ps"><span class="muted">below forecast:</span> '
                f'{side(p["below"])}</div></div>')
        pend = (f'<h3 class="sub">Not happened yet</h3>'
                f'<p class="lede">What today&rsquo;s scheduled releases would do '
                f'in each direction.</p>{"".join(blocks)}')

    return f"""
<section id="affairs">
  <h2>Current affairs &amp; markets</h2>
  <p class="lede">What is actually going on, what the driver model says it should
  do to each market, and whether prices are behaving that way.</p>
  {"".join(cards) or '<p class="lede">No live story is pushing hard enough to model today.</p>'}
  {pend}
  <p class="lede" style="margin-top:14px">{e(af.get('caveat', ''))}</p>
</section>"""



def audio_player(brief, date_str):
    """Present only when the file actually exists - the audio step is allowed
    to fail without taking the report down with it."""
    if not brief:
        return ""
    mins = brief.get("seconds", 0)
    length = f"{mins // 60}:{mins % 60:02d}" if mins else ""
    return f"""
<section id="brief" hidden>
  <h2>Spoken brief</h2>
  <p class="lede">A separate ninety-second read on what is going on and what it
  means for gold and the other markets. Written for listening, not the page read
  aloud.</p>
  <audio controls preload="none" src="audio/{e(date_str)}.mp3"
         style="width:100%;max-width:520px"></audio>
  <p class="lede" style="margin-top:8px">{length} &middot; {brief.get('words', 0)}
  words &middot; <a href="audio/{e(date_str)}.mp3" download>download</a></p>
</section>"""


AUDIO_JS = """
(function () {
  var sec = document.getElementById('brief');
  if (!sec) return;
  var src = sec.querySelector('audio').getAttribute('src');
  fetch(src, { method: 'HEAD' })
    .then(function (r) { if (r.ok) sec.hidden = false; })
    .catch(function () {});
})();
"""


def build_page(payload, narrative, archive=None, groups=None):
    risk = payload["risk"]
    band = risk["band"]
    geo = payload.get("geo") or {}
    gold = payload.get("gold") or {}
    implied = payload.get("implied") or {}
    drivers = payload.get("drivers") or {}
    cot = payload.get("cot")
    attribution = payload.get("attribution")
    fomc = payload.get("fomc") or {}
    health = payload.get("health") or {}
    calib = payload.get("calibration") or {}

    glance = []
    if risk.get("expected_range_usd"):
        glance.append(("Expected range today", f"${risk['expected_range_usd']:,.0f}",
                       risk.get("range_source")))
    if gold.get("last"):
        chg = gold.get("change_pct")
        cls = "up" if (chg or 0) >= 0 else "down"
        glance.append(("Gold last close", f"${gold['last']:,.2f} "
                       f'<span class="{cls}">{chg:+.2f}%</span>' if chg is not None
                       else f"${gold['last']:,.2f}", None))
    if implied.get("gvz"):
        glance.append(("Implied vol (GVZ)", f"{implied['gvz']}",
                       f"{implied['percentile_1y']}th percentile of the year"))
    for key, label in (("REAL10Y", "10y real yield"), ("DXY", "Dollar index")):
        d = drivers.get(key)
        if not d:
            continue
        if key == "REAL10Y":
            move = f'<span class="{"down" if d["change_5d_bp"] >= 0 else "up"}">{d["change_5d_bp"]:+.1f}bp</span>'
        else:
            move = f'<span class="{"down" if d["change_pct"] >= 0 else "up"}">{d["change_pct"]:+.2f}%</span>'
        glance.append((label, f"{d['last']} {move}", None))
    if fomc.get("status", {}).get("next"):
        st = fomc["status"]
        glance.append(("Next FOMC", f"{st['days_away']}d",
                       st["next"] + (" &middot; dot plot" if st.get("has_projections") else "")))
    if cot:
        glance.append(("Managed money net", f"{cot['net']:,}",
                       f"{cot['percentile_2y']}th percentile of 2y"))

    glance_html = "".join(
        f'<div class="g"><span class="k">{e(k)}</span>'
        f'<span class="v">{v}{f"<small>{sub}</small>" if sub else ""}</span></div>'
        for k, v, sub in glance)

    comp = risk["components"]
    sched, unsched = risk.get("scheduled", 0), risk.get("unscheduled", 0)
    split_html = "".join(
        f'<div class="srow"><span>{label}</span>'
        f'<u><i style="width:{max(0, min(100, int(val * 100 / 70)))}%"></i></u>'
        f'<b>{val}</b></div>'
        for label, val in (("Scheduled", sched), ("Unscheduled", unsched)))
    extras = " &middot; ".join(
        f"{k} {v:+d}" for k, v in (("volatility", comp.get("volatility", 0)),
                                   ("positioning", comp.get("positioning", 0)),
                                   ("both at once", comp.get("both_at_once", 0)))
        if v)

    archive_html = ""
    if archive:
        archive_html = (
            '<section><h2>Recent reports</h2><div class="archive">'
            + "".join(f'<a href="reports/{e(d)}.html">{e(d)}</a>'
                      for d in archive[:8])
            + '<a href="reports/index.html">all &rsaquo;</a>'
            + "</div></section>")

    attr_html = ""
    if attribution:
        attr_html = (f'<div class="note"><strong>Gold&rsquo;s last move came through '
                     f'{e(attribution["channel"])}.</strong> {e(attribution["note"])}</div>')
    cot_html = ""
    if cot:
        cot_html = f'<div class="note">{e(cot["read"])}</div>'

    health_html = "".join(
        f'<div class="hr"><span class="hd {"" if c["ok"] else "off"}"></span>'
        f'<span>{e(c["source"])}</span>'
        f'<span class="muted">{e(c["detail"] or ("failed" if not c["ok"] else ""))}</span></div>'
        for c in health.get("checks", []))

    calib_html = ""
    if calib.get("ready"):
        calib_html = (f'<div class="note">Over the last {calib["samples"]} scored days '
                      f'the predicted range was a median '
                      f'<strong>{calib["median_abs_error_pct"]}%</strong> away from what '
                      f'happened, and too wide {calib["over_predicted_pct"]}% of the time. '
                      f'If that stays poor the weights in config.py are wrong.</div>')
    elif calib:
        calib_html = (f'<p class="lede">Scoring itself since setup: '
                      f'{calib.get("samples", 0)} days recorded, five needed before the '
                      f'error is worth reporting.</p>')

    return f"""<!doctype html>
<html lang="en" data-band="{e(band)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(config.SITE_TITLE)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

  <div class="top">
    <div class="brand"><a class="home" href="index.html"><span class="rule"></span>
      <b>{e(config.SITE_TITLE)}</b></a></div>
    <span class="stamp">{e(payload['date'])} &middot; built {e(payload['generated'])}</span>
  </div>
  {nav_html("index.html", 0)}
  <nav class="nav jump">
    <a href="#brief">Listen</a><a href="#affairs">Current affairs</a><a href="#asia">Asia</a><a href="#unscheduled">Geopolitics</a>
    <a href="#calendar">Calendar</a><a href="#briefings">Briefings</a>
    <a href="#board">Board</a><a href="#analysis">Analysis</a>
  </nav>

  <div class="hero">
    <div>
      <div class="score">
        <span class="num">{risk['score']}</span><span class="of">/100</span>
      </div>
      <div class="bandline"><span class="chip">{e(band)} risk</span></div>
      <p class="verdict">{e(risk['band_note'])}</p>
      <div class="scale">
        <div class="track"><span class="pin" style="left:calc({risk['score']}% - 1.5px)"></span></div>
        <div class="ticks"><span>0 low</span><span>25</span><span>50</span>
          <span>75</span><span>100 extreme</span></div>
      </div>
      <div class="split">{split_html}</div>
      {f'<p class="lede" style="margin:10px 0 0">Plus {extras}.</p>' if extras else ''}
    </div>
    <div class="glance">{glance_html}</div>
  </div>

  <section id="unscheduled">
    <h2>Unscheduled risk</h2>
    <p class="lede">{e(geo.get('note', ''))} Each flashpoint is scored against
    <em>its own</em> recent normal, so a long-running conflict does not sit at maximum
    forever. Hold a row for the picture, press it for everything.</p>
    {geo_rows(geo)}
  </section>

  <section id="calendar">
    <h2>Today&rsquo;s USD calendar &mdash; UK time</h2>
    {calendar_table(payload.get('events', []), payload.get('classified', {}))}
  </section>

  <section id="briefings">
    <h2>Event briefings</h2>
    <p class="lede">What each release is, why gold cares, and what it has actually
    done here before.</p>
    {briefings(groups, payload.get('context') or {}, payload.get('base_rates') or {})}
  </section>

  <section>
    <h2>What is driving gold</h2>
    {attr_html}{cot_html}
  </section>

  {audio_player(payload.get('brief'), payload['date'])}

  {affairs_section(payload.get('affairs'))}

  <div id="asia"></div>
  {asia_section(payload.get('asia'))}

  <div id="board"></div>
  {board_section(payload.get('board'), payload.get('correlations'))}

  {market_map_section(payload.get('market_map'))}

  <section id="analysis">
    <h2>Analysis</h2>
    <div class="detail" style="max-width:70ch">{md_lite(narrative)}</div>
  </section>

  <section>
    <h2>Going deeper</h2>
    <div class="archive">
      <a href="weekly/index.html">Weekly cross-asset review</a>
      <a href="assets/gold.html">Asset pages</a>
      <a href="drivers/rate_expectations.html">Driver pages</a>
    </div>
  </section>

  {archive_html}

  <section>
    <h2>Calibration &amp; data health</h2>
    {calib_html}
    <div class="health">{health_html}</div>
  </section>

  <footer>
    Built automatically from the ForexFactory calendar feed, Financial Juice, public
    RSS, FRED, CFTC and free price data.<br>
    Information only &mdash; not trading advice. The risk score is a model, not a
    forecast.
  </footer>
</div>
<script>{JS}{AUDIO_JS}</script>
</body>
</html>"""
