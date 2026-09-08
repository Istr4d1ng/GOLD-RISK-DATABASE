"""Turning a release into a number, and a number into a surprise.

The calendar feed publishes the forecast and the previous value but never the
actual. Without the actual, every base rate averages the prints that mattered
together with the ones that didn't - which is how you end up believing CPI
"usually" moves gold $18, when really it moves it $30 on a surprise and $6 when
it lands on the forecast.
"""

import re

import context
import market

# How a series maps back to the convention the calendar quotes it in.
#   level - use the observation as published (unemployment rate, claims)
#   diff  - month-on-month change in the level (payrolls)
#   index - percent change month-on-month (CPI, PCE, PPI, retail sales)
SUFFIX = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}


def parse_number(text):
    """'208K' -> 208000.0, '0.2%' -> 0.2, '-100.8B' -> -1.008e11, '' -> None."""
    if text is None:
        return None
    t = str(text).strip().replace(",", "").replace("|", "")
    if not t or t in ("-", "–"):
        return None
    m = re.match(r"^(<|>)?\s*(-?\d*\.?\d+)\s*([KkMmBbTt])?\s*(%)?$", t)
    if not m:
        return None
    value = float(m.group(2))
    if m.group(3):
        value *= SUFFIX[m.group(3).lower()]
    return value


def actual_for(title, release_date=None):
    """The released value, in the same units the calendar quotes.

    Read back from FRED after publication, because the calendar feed omits it.
    Returns (value, note) or (None, reason).
    """
    spec = context.series_for(title)
    if not spec:
        return None, "no series mapped for this event"
    sid, _label, kind = spec
    diff = sid.endswith("_DIFF")
    if diff:
        sid = sid.replace("_DIFF", "").replace("PAYMS", "PAYEMS")
    try:
        obs = market.fred_series(sid, years=2)
    except Exception as exc:                # noqa: BLE001
        return None, f"FRED {sid}: {exc}"
    if len(obs) < 2:
        return None, f"FRED {sid}: too few observations"

    if release_date:
        obs = [o for o in obs if o[0] <= release_date] or obs
    latest_date, latest = obs[-1]
    prev = obs[-2][1]

    if diff:
        return round(latest - prev, 1) * 1000, f"{sid} change, obs {latest_date}"
    if kind == "index":
        if not prev:
            return None, f"FRED {sid}: zero previous"
        return round((latest - prev) / prev * 100, 2), f"{sid} m/m %, obs {latest_date}"
    return round(latest, 3), f"{sid} level, obs {latest_date}"


def surprise(forecast_text, actual_value):
    """Signed difference between what printed and what was expected."""
    fc = parse_number(forecast_text)
    if fc is None or actual_value is None:
        return None, ""
    diff = actual_value - fc
    if abs(fc) > 0:
        rel = abs(diff) / max(abs(fc), 1e-9)
    else:
        rel = abs(diff)
    if abs(diff) < 1e-9 or rel < 0.02:
        label = "in line"
    elif diff > 0:
        label = "above"
    else:
        label = "below"
    return round(diff, 4), label
