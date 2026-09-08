# Gold / USD Daily Risk Database

A self-running database that answers four questions every weekday morning,
without anyone needing to open a chat window:

1. What happened in USD news yesterday, and how did gold react?
2. Is that effect likely to be short-lived or long-lasting?
3. What red-folder USD events are scheduled today, at what UK times, and what
   does each one normally do to gold?
4. How risky is today, as a number out of 100?

It then goes back in the evening and records what gold **actually** did around
each event, so the answers get better the longer it runs.

---

## How it works

| File | Job |
|---|---|
| `scripts/config.py` | Every tunable: event weights, feeds, risk bands |
| `scripts/sources.py` | Calendar, news and price fetching (standard library only) |
| `scripts/risk.py` | The 0-100 risk score and the historical base-rate lookup |
| `scripts/context.py` | Event profiles, FRED readings, FOMC calendar and cycle |
| `scripts/geopolitics.py` | Flashpoints, escalation scoring, unscheduled risk |
| `scripts/market.py` | Implied vol, gold's drivers, CFTC positioning, FRED |
| `scripts/actuals.py` | Reads the released value back and computes the surprise |
| `scripts/health.py` | Records which sources answered, so failures aren't silent |
| `data/event_profiles.json` | Curated briefing for each major USD release |
| `data/geopolitical_profiles.json` | Named flashpoints and how each reaches gold |
| `data/calibration.csv` | Predicted range vs what actually happened, per day |
| `scripts/narrate.py` | The written analysis (template, or a model if you add a key) |
| `scripts/render.py` | Builds the dashboard page |
| `scripts/morning.py` | Weekday 06:30 UK: builds the report |
| `scripts/evening.py` | Weekday 22:30 UK: records gold's actual reaction |
| `data/events.csv` | **The database.** One row per event, forever |
| `data/reports/` | Markdown archive, one file per day |
| `docs/` | The published dashboard |

**Data sources, all free and keyless:** the ForexFactory calendar feed
(published by FairEconomy), public RSS from the Federal Reserve, US Treasury,
BLS, CNBC, MarketWatch and Yahoo, free Yahoo/Stooq price data, FRED CSV
downloads for historical readings, and the Fed's own FOMC calendar page.

### The risk score

Two independent sources of danger, combined so neither can hide the other. A day
with a live escalation and an empty calendar must not read LOW.

**Scheduled** (0-70): the biggest release of the day by gold-sensitivity weight,
plus breadth for separate releases through the day, plus 5 for genuine
clustering - two *different* reports at the same minute, not the three titles of
one report.

**Unscheduled** (0-70): the geopolitical score (below).

The higher of the two sets the base; the lower adds up to 15 more, because both
at once is worse than either alone. Then:

- **Volatility** (-5 to +10) - where GVZ sits in its own yearly range
- **Positioning** (0 or 5) - crowded speculative length amplifies everything

Every component is printed on the dashboard, so the number is always auditable.

### Unscheduled risk

Seven named flashpoints - US/Iran, the wider Middle East, Russia/NATO,
China/Taiwan, trade, Fed independence, Korea - each with a gold weight, the
transmission mechanism, **what works against it**, and how long its effect
usually lasts. World-news headlines are matched to a flashpoint and an escalation
tier; the aggregate becomes the unscheduled score.

It is a headline-frequency heuristic, not a geopolitical model. It measures how
loud something is, which is what moves price in the short run - not what will
happen. Football transfers and rail strikes don't trip it.

### Expected range

Taken from **GVZ**, gold's volatility index - the market's own priced
expectation - rather than a backward-looking ATR, falling back to ATR if GVZ is
unavailable. The page says which it used.

### Driver attribution

DXY, the 10-year yield and the 10-year TIPS real yield sit alongside gold, and
the report names the channel the last move came through: real yields (tends to
persist), the dollar (tends to mean-revert), or haven demand (usually fades).
Same move, completely different shelf life.

### Positioning

Managed-money net length in COMEX gold from the CFTC's public API, with its
percentile over two years. Crowding is the fuel; the event is only the match.

### Calibration

Every evening the predicted range is scored against the range that actually
happened and written to `data/calibration.csv`. After a few weeks the dashboard
reports the median error and how often the model runs too wide. If those numbers
look bad, the weights in `config.py` are wrong and should be changed - the page
marks its own homework.

### What you get on each event

Every material release on the day expands into a briefing:

- **What it is** - who publishes it, how often, at what UK time
- **Why gold cares** - the actual transmission mechanism, not just "dollar up,
  gold down". For the FOMC that is the real-rate opportunity cost; for payrolls
  it is the labour half of the mandate feeding the rate path
- **What to watch** - the sub-component that actually carries the information
  (core m/m rather than headline CPI, the control group in retail sales, the
  1-year inflation expectation in the Michigan survey)
- **The catch** - how the event typically misleads people. NFP whipsaws in the
  first fifteen minutes; the FOMC press conference regularly reverses the
  statement reaction; PPI only matters next to CPI
- **Recent readings** - the last eight published values pulled live from FRED,
  with a sparkline, so you can see the trend the market is extrapolating
- **Measured history** - once the event has three or more entries in
  `data/events.csv`, the real median gold move and how often it held

### FOMC cycle tracking

The Fed's meeting calendar is scraped from federalreserve.gov each run (with a
strict eight-meetings-a-year sanity check, a cache, and a built-in fallback if
the page changes shape). The dashboard always shows how far away the next
decision is, whether it carries the dot plot, and what gold actually did on each
of the last eight decision days - open to close, the day's range, and whether
the move carried into the next session.

### The bit that compounds

`data/events.csv` records, for every material event: the forecast, the previous
value, gold immediately before, at +15 minutes, at +1 hour, and at the close -
plus whether the move **sustained**, went **partial**, or **faded**.

It also reads the **actual** value back from FRED after release and records the
surprise against forecast, because the unconditional average is a blend of two
different events. Once an event has three or more entries the report shows its
real base rate - and once each surprise bucket has two, it splits them:

> *CPI m/m: median 1h gold move $22, n=6. Split by the print: above $29 (n=2),
> in line $5.50 (n=2), below $22 (n=2).*

"CPI is usually a big one" and "CPI is a big one **when it surprises**" are
different claims, and only the second is useful.

Co-published titles - payrolls, the unemployment rate and average hourly
earnings arrive together - are recorded with a `co_released` count, briefed once
rather than three times, and counted as one release by the risk score.

---

## Setup (about 10 minutes, costs nothing)

1. **Create the repo.** On github.com, make a new **public** repository called
   `gold-risk-database`. Public matters: free GitHub Pages and unlimited
   Actions minutes only apply to public repos, and nothing here is personal -
   it is all public market data.

2. **Upload this folder.** Easiest way is
   [GitHub Desktop](https://desktop.github.com): *File -> Add local
   repository*, point it at this folder, then *Publish repository*.

3. **Turn on Pages.** Repo *Settings -> Pages -> Source: Deploy from a branch*,
   branch `main`, folder `/docs`. Save. Your dashboard appears at
   `https://<your-username>.github.io/gold-risk-database/` and works on any
   phone, anywhere.

4. **Let Actions write.** *Settings -> Actions -> General -> Workflow
   permissions* -> **Read and write permissions**. Save. Without this the jobs
   cannot commit the day's report back.

5. **Run it once.** *Actions -> Morning report -> Run workflow*. Give it a
   minute, then open your Pages URL.

### Optional: better writing

The analysis section works out of the box with a deterministic template. For a
properly reasoned write-up, get a free key from
[Google AI Studio](https://aistudio.google.com/apikey) and add it as
*Settings -> Secrets and variables -> Actions -> New repository secret*, named
`GEMINI_API_KEY`. One run a day sits far inside the free tier. If the key is
missing or the call fails, it silently falls back to the template - the
pipeline can never break because of this.

---

## Running it yourself

```bash
python scripts/morning.py     # build today's report
python scripts/evening.py     # log gold's reaction to today's events

python tests/run_offline.py           # full pipeline, no network needed
python tests/run_evening_offline.py   # reaction recorder, no network needed
```

## Timing note

GitHub cron runs on UTC, so the morning job fires at 06:30 UK in summer and
05:30 UK in winter. To pin it, edit the `cron:` line in
`.github/workflows/morning.yml` when the clocks change. GitHub's scheduler is
also best-effort and can run a few minutes late when it is busy.

## Honest limits

- **Duration is the weak spot.** No script knows on the morning whether an
  effect will last. What this one does is *measure* it afterwards and build the
  base rate, so after roughly fifty logged events the "short or long lasting"
  answer stops being a guess and starts being a statistic. Early reports will
  be thinner on that question than on the rest.
- **The `prior_move_usd` figures in the profiles are opinion**, not measurement.
  They are labelled as priors on the page and get superseded by the measured
  base rate as soon as the event has been logged three times.
- **The geopolitical score measures attention, not danger.** A quiet build-up
  that no one is writing about scores zero. It is a coincident indicator.
- **COT data is stale by construction** - published Fridays for the prior
  Tuesday. Useful for context, useless for timing.
- **Event weights are a starting opinion**, not truth. They are all in
  `config.py` and should be revised once the CSV disagrees with them.
- **Data health is now printed on the page.** FRED silently returned nothing for
  the first fortnight and the reports just omitted a section rather than saying
  so. Every source now reports whether it answered.
- Free price feeds occasionally rate-limit. The code retries and falls back
  between sources, and a failed component degrades the report rather than
  killing the run.
- This is information, not trading advice. The risk score is a model.
