"""Offline test for the reaction recorder, using synthetic 5-minute bars."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import config      # noqa: E402
import sources     # noqa: E402
import risk as riskmod   # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "calendar.json")
sources.fetch_calendar = lambda: json.load(open(FIX, encoding="utf-8"))

tz = ZoneInfo(config.DISPLAY_TZ)
today = datetime.now(tz).date()

# Build 5m bars for today: flat, then a +$25 spike at the 15:00 UK cluster
# that half retraces by the close - so we can check the persistence label.
bars = []
start = datetime.combine(today, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
spike = datetime.combine(today, datetime.min.time(), tzinfo=tz).replace(hour=15).astimezone(timezone.utc)
price = 3400.0
t = start
while t < start + timedelta(hours=22):
    if spike <= t < spike + timedelta(minutes=60):
        price += 25 / 12
    elif t >= spike + timedelta(minutes=60):
        price -= 0.06
    bars.append({"t": t, "o": price, "h": price + 1, "l": price - 1, "c": price})
    t += timedelta(minutes=5)

sources.gold_intraday = lambda days=5: ("GC=F (fixture)", bars)

# use a scratch csv so the real database is untouched
riskmod.EVENTS_CSV = os.path.join(ROOT, "tests", "_tmp_events.csv")
if os.path.exists(riskmod.EVENTS_CSV):
    os.remove(riskmod.EVENTS_CSV)

import evening    # noqa: E402
evening.riskmod.EVENTS_CSV = riskmod.EVENTS_CSV

assert evening.main() == 0
rows = riskmod.load_history()
print("\n--- checks ---")
assert rows, "no rows written"
print(f"ok  rows appended        ({len(rows)})")
logged = {r["event"] for r in rows}
assert "Fed Chairman Warsh Speaks" in logged
assert "Chicago PMI" not in logged, "immaterial event should not be logged"
print("ok  only material events logged")
warsh = next(r for r in rows if r["event"] == "Fed Chairman Warsh Speaks")
assert abs(float(warsh["move_1h"]) - 25) < 2.5, warsh["move_1h"]
print(f"ok  1h move measured     (${warsh['move_1h']} on a $25 spike)")
assert warsh["persistence"] in ("sustained", "partial", "faded")
print(f"ok  persistence labelled ({warsh['persistence']})")

# idempotency: a second run must not duplicate
assert evening.main() == 0
assert len(riskmod.load_history()) == len(rows)
print("ok  re-running is safe   (no duplicate rows)")

br = riskmod.base_rate("Fed Chairman Warsh Speaks", riskmod.load_history() * 3)
assert br and br["samples"] == 3
print("ok  feeds back into base rates")
os.remove(riskmod.EVENTS_CSV)
print("\nALL CHECKS PASSED")
