"""Offline test for the reaction recorder, actuals capture and calibration."""
import csv
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import config          # noqa: E402
import market          # noqa: E402
import risk as riskmod # noqa: E402
import sources         # noqa: E402

FIX = os.path.join(TESTS, "fixtures", "calendar.json")
ANCHOR = datetime(2026, 8, 28).date()
tz = ZoneInfo(config.DISPLAY_TZ)
today = datetime.now(tz).date()
offset = timedelta(days=(today - ANCHOR).days)


def shifted_calendar():
    out = []
    for e in json.load(open(FIX, encoding="utf-8")):
        e = dict(e)
        e["date"] = (datetime.fromisoformat(e["date"]) + offset).isoformat()
        out.append(e)
    return out


sources.fetch_calendar = shifted_calendar

# Synthetic 5-minute bars: flat, then a +$25 spike over the hour from 13:30 UK
# (the payrolls slot) that half retraces into the close.
bars = []
start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
spike = datetime.combine(today, datetime.min.time(),
                         tzinfo=tz).replace(hour=13, minute=30).astimezone(timezone.utc)
price, t = 4400.0, start
while t < start + timedelta(hours=22):
    if spike <= t < spike + timedelta(minutes=60):
        price += 25 / 12
    elif t >= spike + timedelta(minutes=60):
        price -= 0.06
    bars.append({"t": t, "o": price, "h": price + 1.5, "l": price - 1.5, "c": price})
    t += timedelta(minutes=5)

sources.gold_intraday = lambda days=5: ("GC=F (fixture)", bars)
market.fred_series = lambda sid, years=2: [
    ("2026-07-01", {"PAYEMS": 160000.0, "UNRATE": 4.2, "CES0500000003": 36.10,
                    "MICH": 4.3, "UMCSENT": 51.0}.get(sid, 100.0)),
    ("2026-08-01", {"PAYEMS": 160062.0, "UNRATE": 4.0, "CES0500000003": 36.21,
                    "MICH": 4.5, "UMCSENT": 51.4}.get(sid, 100.4)),
]

riskmod.EVENTS_CSV = os.path.join(TESTS, "_tmp_events.csv")
riskmod.CALIBRATION_CSV = os.path.join(TESTS, "_tmp_calibration.csv")
for f in (riskmod.EVENTS_CSV, riskmod.CALIBRATION_CSV):
    if os.path.exists(f):
        os.remove(f)

# A file written under the OLD 17-column schema, to prove migration works.
OLD = ["date", "time_uk", "event", "impact", "weight", "forecast", "previous",
       "actual", "gold_before", "gold_15m", "gold_1h", "gold_close",
       "move_15m", "move_1h", "move_close", "pct_close", "persistence"]
with open(riskmod.EVENTS_CSV, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=OLD)
    w.writeheader()
    w.writerow({k: "" for k in OLD} | {"date": "2026-09-04", "event": "CPI m/m",
                                       "move_1h": "18.2", "persistence": "sustained"})

# calibration reads the morning's prediction from latest.json next to events.csv
shutil.copy(os.path.join(ROOT, "data", "latest.json"),
            os.path.join(TESTS, "latest.json"))

import reactions     # noqa: E402
reactions.REACTIONS_CSV = os.path.join(TESTS, "_tmp_reactions.csv")
if os.path.exists(reactions.REACTIONS_CSV):
    os.remove(reactions.REACTIONS_CSV)

# Every tracked asset gets the same shaped intraday series, scaled differently,
# so the cross-asset logger has something to measure.
import assets as assetlib   # noqa: E402


def fake_intraday(days=5):
    out = {}
    for i, key in enumerate(assetlib.load_assets()):
        scale = 1 + i * 0.4
        out[key] = [{"t": b["t"], "o": b["o"] * scale, "h": b["h"] * scale,
                     "l": b["l"] * scale, "c": b["c"] * scale} for b in bars]
    return out, []


reactions.intraday_bars = fake_intraday

import evening       # noqa: E402
evening.riskmod = riskmod
evening.reactions = reactions

assert evening.main() == 0
rows = riskmod.load_history()

print("\n--- checks ---")

with open(riskmod.EVENTS_CSV, newline="", encoding="utf-8") as fh:
    header = csv.DictReader(fh).fieldnames
assert header == riskmod.CSV_FIELDS, header
assert any(r["event"] == "CPI m/m" and r["move_1h"] == "18.2" for r in rows)
print(f"ok  schema migrated       (17 -> {len(header)} columns, old row preserved)")

logged = {r["event"] for r in rows}
assert "Non-Farm Employment Change" in logged
assert "Chicago PMI" not in logged
print(f"ok  material events only  ({len(logged) - 1} logged today)")

nfp = next(r for r in rows if r["event"] == "Non-Farm Employment Change")
assert abs(float(nfp["move_1h"]) - 25) < 2.5, nfp["move_1h"]
assert nfp["persistence"] in ("sustained", "partial", "faded")
print(f"ok  reaction measured     (1h ${nfp['move_1h']} on a $25 spike, "
      f"{nfp['persistence']})")

assert int(nfp["co_released"]) == 2, nfp["co_released"]
print("ok  co-release recorded   (payrolls shares its move with 2 other titles)")

assert nfp["actual"] not in ("", None), nfp
assert nfp["surprise_label"] in ("above", "below", "in line"), nfp
print(f"ok  actual captured       (forecast {nfp['forecast']}, actual "
      f"{nfp['actual']}, {nfp['surprise_label']})")

ur = next(r for r in rows if r["event"] == "Unemployment Rate")
assert float(ur["actual"]) == 4.0 and ur["surprise_label"] == "below", ur
print(f"ok  surprise computed     (unemployment 4.0 vs 4.1% forecast -> below)")

noise = next(r for r in rows if r["event"] == "Fed Chairman Warsh Speaks")
assert abs(float(noise["move_1h"])) < 1.5 and noise["persistence"] == "", noise
print(f"ok  noise not classified  (a ${noise['move_1h']} drift gets no "
      f"sustained/faded label)")

assert evening.main() == 0
assert len(riskmod.load_history()) == len(rows)
print("ok  re-running is safe    (no duplicate rows)")

with open(riskmod.CALIBRATION_CSV, newline="", encoding="utf-8") as fh:
    cal = list(csv.DictReader(fh))
assert len(cal) == 1, cal
c = cal[0]
assert float(c["realised_range"]) > 0 and float(c["predicted_range"]) > 0
print(f"ok  calibration logged    (predicted ${c['predicted_range']}, realised "
      f"${c['realised_range']}, {c['abs_error_pct']}% out)")

fake = [{"date": f"2026-09-{d:02d}", "risk_score": 50, "predicted_range": 80,
         "realised_range": r, "error": 0, "abs_error_pct": 0,
         "band": "HIGH", "range_source": "x", "scheduled": 1, "unscheduled": 0}
        for d, r in zip(range(1, 9), [70, 90, 60, 100, 75, 85, 65, 95])]
with open(riskmod.CALIBRATION_CSV, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=riskmod.CALIBRATION_FIELDS)
    w.writeheader()
    [w.writerow(r) for r in fake]
summary = riskmod.calibration()
assert summary["ready"] and summary["samples"] == 8, summary
print(f"ok  calibration summary   (median error {summary['median_abs_error_pct']}%, "
      f"too wide {summary['over_predicted_pct']}% of days)")

for f in (riskmod.EVENTS_CSV, riskmod.CALIBRATION_CSV,
          os.path.join(TESTS, "latest.json")):
    os.remove(f)
rx = reactions.load()
assert rx, "no cross-asset reactions logged"
assets_logged = {r["asset"] for r in rx}
events_logged = {r["event"] for r in rx}
assert len(assets_logged) == 12, sorted(assets_logged)
print(f"ok  cross-asset logged     ({len(rx)} rows: {len(events_logged)} events "
      f"x {len(assets_logged)} assets)")

gold_nfp = next(r for r in rx if r["asset"] == "gold"
                and r["event"] == "Non-Farm Employment Change")
assert abs(float(gold_nfp["pct_1h"])) > 0.3 and gold_nfp["persistence"], gold_nfp
print(f"ok  percent moves recorded (gold {gold_nfp['pct_1h']}% at 1h, "
      f"{gold_nfp['persistence']})")
assert gold_nfp["surprise_label"] in ("above", "below", "in line")
print("ok  surprise carried across (so base rates split by print, per asset)")

m = reactions.matrix_for_event("Non-Farm Employment Change", rx, min_samples=1)
assert m and "gold" in m and "oil" in m
print(f"ok  matrix reads back      ({len(m)} assets for one event)")

before = len(rx)
assert evening.main() == 0
assert len(reactions.load()) == before
print("ok  cross-asset idempotent (no duplicate rows on a re-run)")
if os.path.exists(reactions.REACTIONS_CSV):
    os.remove(reactions.REACTIONS_CSV)

print("\nALL CHECKS PASSED")
