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
| `data/event_profiles.json` | Curated briefing for each major USD release |
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

Four components, each visible on the dashboard so you can see where the number
came from:

- **Headline event** (0-70) - the single biggest scheduled release, by its
  gold-sensitivity weight
- **Breadth** (0-15) - several meaningful releases compound the noise
- **Clustering** (0 or 5) - two heavyweight prints at the same minute is worse
  than the same two spread across the day
- **Volatility** (-5 to +10) - current 14-day ATR against its 60-day average

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

Once an event has three or more entries, the morning report starts showing its
real base rate instead of a generic description: *"CPI m/m: median 1h gold move
$18.40, 71% held into the close, n=7."* That is the difference between a
newsletter and a database.

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
- **Event weights are a starting opinion**, not truth. They are all in
  `config.py` and should be revised once the CSV disagrees with them.
- Free price feeds occasionally rate-limit. The code retries and falls back
  between sources, and a failed component degrades the report rather than
  killing the run.
- This is information, not trading advice. The risk score is a model.
