"""Tracks which data sources answered and which didn't.

Silent failures are the enemy here: FRED quietly returned nothing for two
weeks and the reports simply omitted a whole section rather than saying so.
Every fetch registers its outcome, and the dashboard prints the result.
"""

_checks = []


def reset():
    _checks.clear()


def ok(name, detail=""):
    _checks.append({"source": name, "ok": True, "detail": detail})


def fail(name, detail=""):
    _checks.append({"source": name, "ok": False, "detail": str(detail)[:200]})
    print(f"[health] {name} FAILED: {detail}")


def guard(name, fn, default=None, detail=lambda v: ""):
    """Run fn, record the outcome, return its value or `default`."""
    try:
        value = fn()
    except Exception as exc:                # noqa: BLE001
        fail(name, exc)
        return default
    if value in (None, [], {}):
        fail(name, "returned nothing")
        return default
    ok(name, detail(value))
    return value


def summary():
    good = [c for c in _checks if c["ok"]]
    bad = [c for c in _checks if not c["ok"]]
    return {"checks": list(_checks), "ok": len(good), "failed": len(bad),
            "degraded": bool(bad)}
