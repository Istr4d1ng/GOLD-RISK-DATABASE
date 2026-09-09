"""Offline test for the weekly cross-asset review."""
import csv
import math
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import assets as assetlib   # noqa: E402
import reactions            # noqa: E402
import risk as riskmod      # noqa: E402
import sources              # noqa: E402

MOVES = {"GC=F": 1.9, "^GSPC": -1.4, "^NDX": -2.1, "CL=F": 6.2,
         "DX-Y.NYB": -0.8, "^TNX": -3.1, "SI=F": 3.4, "HG=F": -1.1,
         "BTC-USD": -5.6, "EURUSD=X": 0.7, "USDJPY=X": -1.2, "^VIX": 12.0}


def fake_chart(symbol, interval="1d", rng="1y"):
    if symbol not in MOVES:
        raise RuntimeError(f"no fixture for {symbol}")
    seed = sum(ord(c) for c in symbol)
    start = datetime.now(timezone.utc) - timedelta(days=200)
    bars, px = [], 100.0
    for i in range(199):
        px = 100 * (1 + (math.sin((i + seed) / 5.0) * 1.2
                         + math.cos((i + seed) / 11.0) * 0.7) / 100)
        bars.append({"t": start + timedelta(days=i), "o": px,
                     "h": px * 1.004, "l": px * 0.996, "c": px})
    for j in range(5):
        px *= (1 + MOVES[symbol] / 5 / 100)
        bars.append({"t": start + timedelta(days=199 + j), "o": px,
                     "h": px * 1.006, "l": px * 0.994, "c": px})
    return bars


sources.fetch_chart = fake_chart

# A reaction log with enough history for base rates, including one pair whose
# measured sign deliberately contradicts the prior.
reactions.REACTIONS_CSV = os.path.join(ROOT, "tests", "_tmp_reactions.csv")
riskmod.CALIBRATION_CSV = os.path.join(ROOT, "tests", "_tmp_calib.csv")
rows = []
for i in range(5):
    rows.append({"date": f"2026-0{i+4}-10", "time_uk": "13:30",
                 "event": "Core CPI m/m", "kind": "event", "weight": "10",
                 "forecast": "0.3%", "actual": "0.4", "surprise": "0.1",
                 "surprise_label": "above", "asset": "gold", "before": "4400",
                 "m15": "", "m1h": "", "close": "", "move_1h": "",
                 "pct_15m": "", "pct_1h": f"-{0.5 + i * 0.1:.2f}",
                 "pct_close": "-0.4", "persistence": "sustained"})
    # gold RISING on a hot CPI would contradict the prior - that is the case
    # the review is supposed to catch
    rows.append({"date": f"2026-0{i+4}-10", "time_uk": "13:30",
                 "event": "Consumer Price Index", "kind": "event", "weight": "10",
                 "forecast": "0.3%", "actual": "0.4", "surprise": "0.1",
                 "surprise_label": "above", "asset": "gold", "before": "4400",
                 "m15": "", "m1h": "", "close": "", "move_1h": "",
                 "pct_15m": "", "pct_1h": f"{0.6 + i * 0.05:.2f}",
                 "pct_close": "0.5", "persistence": "sustained"})
with open(reactions.REACTIONS_CSV, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=reactions.FIELDS)
    w.writeheader()
    [w.writerow(r) for r in rows]

import weekly   # noqa: E402
weekly.reactions = reactions
weekly.riskmod = riskmod
assert weekly.main() == 0

today = datetime.now().date()
md = open(os.path.join(ROOT, "data", "weekly", f"{today}.md"), encoding="utf-8").read()
page = open(os.path.join(ROOT, "docs", "weekly", "index.html"), encoding="utf-8").read()

print("\n--- checks ---")
bars, _ = assetlib.fetch_bars("1y")
mv = weekly.week_moves(bars)
assert len(mv) == 12 and abs(mv[0]["change_pct"]) >= abs(mv[-1]["change_pct"])
print(f"ok  week moves ranked      (biggest {mv[0]['name']} "
      f"{mv[0]['change_pct']:+.2f}%, quietest {mv[-1]['name']} "
      f"{mv[-1]['change_pct']:+.2f}%)")

shift = weekly.correlation_shift(bars)
assert shift["rows"] and all(abs(r["shift"]) <= 2.01 for r in shift["rows"])
print(f"ok  correlation shift      ({shift['short']}d vs {shift['long']}d, "
      f"largest change {shift['rows'][0]['name']} {shift['rows'][0]['shift']:+.2f})")

learn = weekly.learned(reactions.load())
assert len(learn) == 2 and all(r["samples"] == 5 for r in learn)
print(f"ok  base rates surfaced    ({len(learn)} event/asset pairs at n=5)")

clash = weekly.disagreements(learn)
assert clash and clash[0]["asset"] == "gold", clash
print(f"ok  disagreements caught   ({clash[0]['event']} -> gold: expected "
      f"{clash[0]['expected_dir']}, measured {clash[0]['signed']:+.2f}%)")

assert "## What moved" in md and "## What moved together" in md
assert "Where the model is wrong" in md
print("ok  markdown review written")
assert "Weekly cross-asset review" in page and "assets/gold.html" in page
assert "prefers-color-scheme" in page
print(f"ok  weekly page renders    ({len(page):,} bytes, links to asset pages)")

for f in (reactions.REACTIONS_CSV, riskmod.CALIBRATION_CSV):
    if os.path.exists(f):
        os.remove(f)
print("\nALL CHECKS PASSED")
