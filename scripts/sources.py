"""Data collection. Standard library only - no pip install, nothing to break."""

import csv
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _get(url, timeout=25, retries=3):
    """GET a URL as bytes, with a browser UA and simple backoff."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Accept-Language": "en-GB,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:            # noqa: BLE001 - any failure retries
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


# ---------------------------------------------------------------------------
# Economic calendar
# ---------------------------------------------------------------------------

def fetch_calendar():
    """Return the week's calendar entries as dicts, or raise."""
    last = None
    for url in config.CALENDAR_URLS:
        try:
            raw = _get(url)
            data = json.loads(raw.decode("utf-8", "replace"))
            if isinstance(data, list) and data:
                return data
        except Exception as exc:            # noqa: BLE001
            last = exc
    raise RuntimeError(f"no calendar source responded: {last}")


def weight_for(title, impact):
    """Gold-sensitivity weight 0-10 for an event title."""
    t = (title or "").lower()
    best = 0
    for key, w in config.EVENT_WEIGHTS.items():
        if key in t and w > best:
            best = w
    if best:
        return best
    return config.IMPACT_FALLBACK.get((impact or "").lower(), 1)


def parse_events(entries, day, currency="USD"):
    """Filter the raw feed to one calendar day, in display timezone."""
    tz = ZoneInfo(config.DISPLAY_TZ)
    out = []
    for e in entries:
        if currency and e.get("country") != currency:
            continue
        raw_date = e.get("date")
        if not raw_date:
            continue
        try:
            dt = datetime.fromisoformat(raw_date)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(tz)
        if local.date() != day:
            continue
        title = e.get("title", "").strip()
        impact = (e.get("impact") or "").strip()
        out.append({
            "title": title,
            "currency": e.get("country"),
            "utc": dt.astimezone(timezone.utc).isoformat(),
            "local_time": local.strftime("%H:%M"),
            "local_dt": local,
            "impact": impact,
            "folder": {"high": "RED", "medium": "ORANGE",
                       "low": "YELLOW"}.get(impact.lower(), "GREY"),
            "forecast": (e.get("forecast") or "").strip(),
            "previous": (e.get("previous") or "").strip(),
            "actual": (e.get("actual") or "").strip(),
            "weight": weight_for(title, impact),
        })
    out.sort(key=lambda x: x["utc"])
    return out


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def fetch_chart(symbol, interval="1d", rng="6mo"):
    """Yahoo chart endpoint -> list of {t, o, h, l, c} dicts in UTC."""
    url = config.YAHOO_CHART.format(symbol=urllib.parse.quote(symbol))
    url += f"?interval={interval}&range={rng}&includePrePost=false"
    data = json.loads(_get(url).decode("utf-8", "replace"))
    result = (data.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"no chart data for {symbol}")
    r = result[0]
    stamps = r.get("timestamp") or []
    q = (r.get("indicators") or {}).get("quote") or [{}]
    q = q[0]
    bars = []
    for i, ts in enumerate(stamps):
        c = (q.get("close") or [None] * len(stamps))[i]
        if c is None:
            continue
        bars.append({
            "t": datetime.fromtimestamp(ts, tz=timezone.utc),
            "o": (q.get("open") or [None] * len(stamps))[i] or c,
            "h": (q.get("high") or [None] * len(stamps))[i] or c,
            "l": (q.get("low") or [None] * len(stamps))[i] or c,
            "c": c,
        })
    return bars


def fetch_stooq_daily(symbol="xauusd"):
    """Fallback daily OHLC from Stooq (CSV, no key)."""
    raw = _get(config.STOOQ_CSV.format(symbol=symbol)).decode("utf-8", "replace")
    rows = list(csv.DictReader(io.StringIO(raw)))
    bars = []
    for r in rows:
        try:
            bars.append({
                "t": datetime.strptime(r["Date"], "%Y-%m-%d").replace(tzinfo=timezone.utc),
                "o": float(r["Open"]), "h": float(r["High"]),
                "l": float(r["Low"]), "c": float(r["Close"]),
            })
        except (KeyError, ValueError):
            continue
    if not bars:
        raise RuntimeError("stooq returned no usable rows")
    return bars


def gold_daily(rng="2y"):
    """Daily gold bars from whichever free source answers first."""
    for sym in config.GOLD_SYMBOLS:
        try:
            bars = fetch_chart(sym, "1d", rng)
            if len(bars) > 30:
                return sym, bars
        except Exception:                   # noqa: BLE001
            continue
    return "XAUUSD (stooq)", fetch_stooq_daily()


def gold_intraday(days=5):
    """5-minute gold bars for measuring event reactions."""
    for sym in config.GOLD_SYMBOLS:
        try:
            bars = fetch_chart(sym, "5m", f"{days}d")
            if len(bars) > 50:
                return sym, bars
        except Exception:                   # noqa: BLE001
            continue
    raise RuntimeError("no intraday gold data available")


def last_close(symbol):
    try:
        bars = fetch_chart(symbol, "1d", "1mo")
        return bars[-1]["c"], (bars[-1]["c"] - bars[-2]["c"]) / bars[-2]["c"] * 100
    except Exception:                       # noqa: BLE001
        return None, None


def atr(bars, period=14):
    """Average true range over the last `period` bars."""
    if len(bars) < period + 1:
        return None
    trs = []
    for i in range(1, len(bars)):
        prev_c = bars[i - 1]["c"]
        trs.append(max(bars[i]["h"] - bars[i]["l"],
                       abs(bars[i]["h"] - prev_c),
                       abs(bars[i]["l"] - prev_c)))
    return sum(trs[-period:]) / period


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def _text(node, *names):
    for n in names:
        el = node.find(n)
        if el is not None and el.text:
            return el.text.strip()
    return ""


def _parse_date(s):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def score_headline(text):
    t = (text or "").lower()
    return sum(w for k, w in config.NEWS_KEYWORDS.items() if k in t)


def fetch_news(hours=36, limit=25):
    """Recent USD/gold-relevant headlines from free RSS feeds."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = []
    for source, url in config.NEWS_FEEDS:
        try:
            raw = _get(url, timeout=15, retries=2)
            root = ET.fromstring(raw)
        except Exception:                   # noqa: BLE001
            continue
        nodes = root.findall(".//item") or root.findall(
            ".//{http://www.w3.org/2005/Atom}entry")
        for node in nodes:
            title = _text(node, "title", "{http://www.w3.org/2005/Atom}title")
            if not title:
                continue
            link = _text(node, "link")
            if not link:
                el = node.find("{http://www.w3.org/2005/Atom}link")
                link = el.get("href") if el is not None else ""
            pub = _parse_date(_text(node, "pubDate", "published", "updated",
                                    "{http://purl.org/dc/elements/1.1/}date"))
            if pub and pub < cutoff:
                continue
            desc = re.sub(r"<[^>]+>", " ",
                          _text(node, "description", "summary"))[:400]
            score = score_headline(title + " " + desc)
            if score < 3:
                continue
            items.append({
                "source": source, "title": title, "link": link,
                "published": pub.isoformat() if pub else "",
                "summary": " ".join(desc.split()),
                "relevance": score,
            })
    seen, unique = set(), []
    for it in sorted(items, key=lambda x: (-x["relevance"], x["published"])):
        key = it["title"].lower()[:70]
        if key in seen:
            continue
        seen.add(key)
        unique.append(it)
    return unique[:limit]
