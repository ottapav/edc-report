# EDC sharing report

Interactive web app (Dash) that displays the electricity-sharing data of a Czech sharing
group. The input is the CSV report generated on [edc-cr.cz](https://www.edc-cr.cz), the portal
of the *Elektroenergetické datové centrum* (EDC). Upload the CSV and you get the group's
sharing at a glance. The app also recomputes the whole period with the proposed **exact
static method** (`presna_staticka.py`) and shows today's result and the proposal side by side,
with the computation timed per 15-min interval.

> **Česky:** Webová aplikace, která zobrazuje data o sdílení elektřiny z CSV reportu
> vygenerovaného na portálu edc-cr.cz. Po nahrání CSV ukáže
> souhrny, denní a hodinové grafy, teplotní mapu a podíl, který „mohl být sdílen“.
> Z reportu odhadne alokační klíče (dnešní metoda EDC s 1 nebo 5 koly, i pro velké skupiny).
> Jedním tlačítkem přepočítá sdílení přesnou statickou metodou a porovná ji s dneškem.
> Rozhraní je v češtině i angličtině, se světlým i tmavým režimem.

![Report of one group, light mode](docs/screenshot-light.png)

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [How the allocation keys are estimated](#how-the-allocation-keys-are-estimated)
- [Exact static method and timing](#exact-static-method-and-timing)
- [Architecture](#architecture)
- [Performance](#performance)
- [Deployment on Render](#deployment-on-render)
- [Configuration](#configuration)
- [Tests](#tests)
- [Limitations](#limitations)
- [Data and privacy](#data-and-privacy)

## Features

**Report of today's sharing** (the figures of `plot_energy_sharing.py`, interactive):

* **General information and headline figures:**
  * facts: period, 15-min intervals, producer, peak production, best day;
  * energy: production, shared, *could have been shared*, surplus above group demand;
  * consumption: members' consumption and energy from the grid.
* **Total energy by flow:** stacked bars per member (shared | unmet) and for the source
  (shared | unshared).
* **Pie of the source's energy:** shared, *could have been shared* (min(unshared, unmet) in the
  same 15 min), and surplus nobody could use.
* **Daily energy:** stacked areas, or lines on a log axis. **Click a day** to select it.
* **Sharing on the selected day:** 15-min steps from 06:00 to 21:00, always directly under the
  daily plot. The y axis is fixed over the whole period, so days compare on one scale.
* **Heatmap hour × month** (optional): outgoing energy, shared energy or unmet demand.
* **Per-member table:** consumption, shared, unmet, coverage and data availability.

**Selection panel:**

* Tick members on or off, rename them, and edit their allocation keys. All of this happens in
  one grid, so a group of hundreds of members stays fast.
* ◀ date ▶ for the hourly plot.
* Display options.
* Group ID for the title.

**Exact static method (proposal):**

* **Keys:** estimated from the report right after upload. You can check and correct them
  before the recompute.
* **Recompute:** one button runs `rozdel()` for every 15-min interval, with a progress bar.
* **Side by side:** today (EDC) and the exact method, with shared axes, differences to EDC in
  the tiles, and a per-member comparison table.
* **Timing:** the number of intervals evaluated, total time, and time per interval, split by
  the method's fast paths.

**Interface:**

* CZ / EN.
* Light and dark mode: the default follows the system, and the ☾/☀ icon switches and
  remembers the choice.
* Works on a phone.

![Today vs. the exact static method, dark mode](docs/screenshot-dark.png)

## Quick start

```bash
git clone https://github.com/ottapav/edc-report.git && cd edc-report
python -m venv .venv && . .venv/bin/activate   # Python 3.11 (see .python-version)
pip install -r requirements.txt
python app.py                                  # http://127.0.0.1:8050
```

To run it exactly as in production:

```bash
gunicorn app:server -c gunicorn.conf.py        # listens on $PORT (default 8050)
```

## Using the app

1. **Upload** the CSV report generated on edc-cr.cz (file name like
   `Export-dat-…-report-….csv`). Both report layouts are detected from the header:
   * **all report** (`IN/OUT-<ean>-D` for the producer, `IN/OUT-<ean>-O` for members) carries
     production and consumption and enables everything;
   * **part report** (`<ean>-<ean>` columns) has shared energy only: no pie, no recompute.
2. The report appears immediately, and the **allocation keys are estimated in the
   background**. A summary shows which EDC method explains the report (1 or 5 rounds) and
   how many 15-min intervals it reproduces. Keys that the report cannot pin down exactly are
   marked, and hovering shows the range of equally consistent values.
3. **Check the keys** against the contract and correct them in the grid if needed; **Odhad**
   restores the estimate. Keys act as ratios in the exact method, and 0 means the member gets
   nothing. An optional *reserve for sale* is passed to `rozdel(..., rezerva=)`.
4. **Recompute.** The second column appears next to today's report, and the timing card shows
   the computation.
5. **Explore:**
   * click a day in either daily plot, or use ◀ ▶, to see it in 15-min steps;
   * untick members to see the rest of the group;
   * switch the heatmap metric, or turn the heatmap off.

![Daily plot with the selected day, the hourly plot and the heatmap](docs/screenshot-hourly.png)

## How the allocation keys are estimated

The CSV has no keys, but it contains what today's EDC static method did with them. In every
round each member gets `min(remaining demand, floor(k_i · P_r))`, where `P_r` is the production
left at the start of the round. Groups up to 100 EAN get 5 rounds, larger groups one round.
`keyfit.py` inverts this:

* **Every interval where a member is not fully covered bounds its key.** Such a member was
  never capped, so it received exactly `floor(k_i · P_r)` in each round:
  `sum_r floor(k_i · P_r) = s_i`. That pins `k_i` to a small interval, which is found exactly
  by bisection.
* **The key is the value consistent with the most intervals**, on the 0.01 % grid of EDC
  keys. A rounder value nearby (1 %, 0.5 %, …) wins only when the separating intervals do not
  clearly favour the finer one. This absorbs the ~1 % of report rows that do not follow the
  model, without inventing round numbers.
* **One round is separable**, because each member depends only on its own key, so all keys
  come out in one pass. This covers the groups above 100 EAN.
* **Five rounds couple the members** through `P_r`. The bounds are iterated to a fixed point
  from two starts:
  * uniform keys;
  * a rank-1 estimate, which needs no `P_r`, because two members short in the same interval
    both got their key's share of the same productions.
  The fit is then settled by replaying the method: moving single keys, and moving all keys
  together (rounded or rescaled). Several key sets can be self-consistent; the replay decides
  between them.
* Both round counts are tried (5 only up to 100 members), and the one that reproduces more
  intervals wins.

For every key the app also returns the **range of values the report fits equally well**. A key
is marked when that range is wider than 0.2 pp or 5 % of the key. Typical causes are a member
that is almost always fully covered (then only a lower bound is known) or one with no data.

**Accuracy**, measured on synthetic groups: EDC shares from known keys, 1 % of rows perturbed.
"As good as the truth" means the estimated keys reproduce as many intervals as the true keys.
The data cannot tell those apart.

| Group | EDC rounds | Result | Time (1 CPU) |
|---|---|---|---|
| Real group 0000018947 (5 members, 1 year) | 5 | exactly 50 / 10 / 10 / 10 / 10 %, 99.2 % of intervals (same as the true keys) | 0.3–3 s |
| 60 or 100 members, round keys | 5 | as good as the truth in 12 / 12 runs | 5–7 s |
| 20 members, random keys (0.01 % steps) | 5 | as good as the truth in 5 / 6 runs | ≤ 4 s |
| 60–100 members, random keys | 5 | 91–99 % of intervals; not always optimal | 10–22 s |
| 150–1 000 members | 1 | as good as the truth; every true key inside the reported range | 0.1–0.6 s |

Irregular keys in large 5-round groups remain the hard case: the fit can stop at a local
optimum. The summary always shows the match, and a warning appears below 95 %, so check those
keys against the contract.

## Exact static method and timing

`presna_staticka.py` is the reference implementation (unchanged). Each member gets
`s_i = min(D_i, k_i · H)`, with the level `H` computed to the end, so everything that can be
consumed is shared while the keys hold. `recompute.py` calls `rozdel()` for every 15-min
interval of the report and builds a second report in the same structure, so every figure and
table works for both.

**Timing.** The loop runs in a forked worker process: it gets a whole core, and the web
server's threads do not disturb the measurement. It is timed with that process's CPU clock:

* the garbage collector is told to ignore the inherited server heap (`gc.freeze()`), otherwise
  copy-on-write faults were billed to `rozdel()`;
* intervals are grouped by the method's fast paths (night P = 0; production covers everyone;
  level H computed) and each group is timed as one batch, so there is no per-call timer
  overhead.

The page reports the number of evaluations, the total time, the time per interval (overall
and with H computed), and the whole job.

For the real group (5 members, 35 040 intervals), 22 333 are night, 3 727 have enough for
everyone and 8 980 need H. That takes 50–65 ms in total, about 1.5–1.9 µs per interval and
about 4.5 µs with H. For 150 members and one month it takes about 70–80 ms and 25 µs per
interval. Numbers vary with the machine; Render instances have less than one CPU.

## Architecture

| File | Role |
|---|---|
| `app.py` | Dash layout and callbacks, in-memory store, background jobs, config, `/healthz`, optional basic auth |
| `edc_data.py` | CSV parsing (both layouts), per-member frames keyed by EAN, statistics; memoised derived data |
| `keyfit.py` | Replay of today's EDC method (numpy, in blocks), key estimation for 1 and 5 rounds |
| `recompute.py` | Exact static recompute in a worker process, timing |
| `presna_staticka.py` | Reference implementation of the exact static method |
| `figures.py` | Plotly figures, light/dark themes, folding of large groups into "Others" |
| `i18n.py` | CZ/EN strings and number formatting |
| `assets/style.css` | Styles, light/dark variables (Dash loads it automatically) |
| `gunicorn.conf.py`, `render.yaml`, `.python-version` | Deployment |
| `tests/` | pytest suite (synthetic data, no real CSV needed) |

**One process on purpose.** An upload, its key estimate, a running recompute and its progress
live in the memory of one process, and every request of that browser session must reach it.
`gunicorn.conf.py` therefore pins **one worker** (ignoring `WEB_CONCURRENCY`) with threads, and
never recycles it (`max_requests = 0`).

This is the failure mode fixed in robopid-simulator: there, with two workers, the progress
polls of a job reached the worker that did not start it, and the button looked dead. More
workers here would need a shared store such as Redis, not a bigger worker count.

**Background jobs.** Key estimation (after upload) and the recompute run in threads. At most
`EDC_MAX_JOBS` run at once, and the rest wait in a visible queue. The browser polls every
200 ms, and only the poll callback draws the progress bar and the button state. Two other
safeguards:

* the poll is idempotent: every later poll repeats the complete final state, because Dash may
  drop the first "done" response when the next poll overtakes it;
* a job that disappeared (server restarted, or a free instance went to sleep) is reported and
  the button re-enabled, instead of leaving the page waiting.

**Efficiency measures** (from the code review):

* One grid for all members instead of 4 inputs per member. With 600 pattern-matching
  components the Dash renderer needed tens of seconds per update for 150 members.
* Tables are rendered as one HTML block instead of thousands of React components.
* More than 10 members fold into 9 + "Others" in the plots. tab10 has 10 colours and hues
  are never cycled; the ranking comes from today's report, so both columns match. Tables keep
  every member.
* Derived data is memoised per upload and selection: filtered frames, aggregates, totals,
  daily sums, heatmap pivots, the hourly y range.
* Editing a key no longer redraws any figure; only the small "keys changed" note updates.
* The selected-day marker moves in the browser (clientside callback).
* Figures are built with one validated layout call; unused per-point hover data is gone.

## Performance

Measured in a browser against the production setup (gunicorn, one worker):

| | 5 members, 1 year | 150 members, 1 month |
|---|---|---|
| Upload → report and estimated keys | ≈ 3 s | 2.4 s (was 18 s) |
| Recompute → side-by-side report | < 1 s | 1.8 s (was 45 s) |
| Untick a member → both reports redrawn | < 0.5 s | 0.7 s (was 24 s) |
| Server render of the full page | 60–200 ms | 0.75 s |
| Memory | ≈ 95 MB + 20–25 MB per cached report | |

## Deployment on Render

The repository is a ready Blueprint:

1. Render → **New → Blueprint** → pick this repository → **Apply**.
2. Render installs `requirements.txt` on Python 3.11 and starts
   `gunicorn app:server -c gunicorn.conf.py`, with health check `/healthz`. Every push to
   `main` redeploys.
3. Optionally set `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` to password-protect the app.

Notes:

* **Free plan:** 512 MB, and it sleeps after 15 minutes without traffic. The first visit then
  waits about a minute, and uploaded reports are gone; the page says so and asks for the file
  again. The *0.5c-512mb* plan ($7/month) stays up.
* **Memory:** both plans have 512 MB. Keep `EDC_CACHE_MAX` about 6.
* **Changing the Blueprint:** if you created the service before `gunicorn.conf.py` existed,
  update its start command to the one above (or re-sync the Blueprint).
* **Keep one worker.** Do not add `--workers N`, and do not rely on `WEB_CONCURRENCY` (see
  *Architecture*).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 8050 (Render sets it) | port for gunicorn |
| `EDC_THREADS` | 8 | request threads of the single worker |
| `EDC_MAX_JOBS` | 2 | key estimations / recomputes running at once (others queue) |
| `EDC_CACHE_MAX` | 6 | uploaded reports kept in memory (oldest dropped) |
| `EDC_MAX_UPLOAD_MB` | 25 | largest accepted CSV |
| `BASIC_AUTH_USER`, `BASIC_AUTH_PASSWORD` | empty | password-protect the whole app when both are set |
| `LOG_LEVEL` | info | gunicorn log level |

## Tests

```bash
pip install pytest
python -m pytest -q tests
```

The suite runs on synthetic groups and a synthetic *all report* CSV, so no real meter data is
needed. It checks that:

* the vectorised replay equals `staticka_edc`;
* the exact per-interval key bounds contain the true key;
* keys are recovered, or fit as well as the truth with the truth inside the reported range,
  for 5 rounds and for a 150-member 1-round group;
* the CSV round-trips through the parser;
* the exact method adds exactly the "could have been shared" energy;
* the timing counts every interval;
* memoisation reuses frames.

## Limitations

* **Several producers:** all reports with more than one producer are not supported yet (the
  part report is). The exact method for several producers would use the pool mode (`bazen()`).
* **Keys:** the estimate cannot be better than the report allows. Members that are almost
  always fully covered only get a lower bound. Irregular keys in large 5-round groups may stop
  at a local optimum. The match and the ranges are always shown.
* **Windows:** there is no `fork`, so the `rozdel()` loop runs in the server process and its
  timing can be higher. Linux (Render) and macOS are fine.
* **Date picker:** month names follow the browser, not the CZ/EN switch.

## Data and privacy

Uploaded files are parsed in memory only and never written to disk. They disappear when the
cache drops them or the server restarts. `.gitignore` excludes `*.csv`, so real meter data
does not end up in the repository. The screenshots above use a synthetic group. For a public
deployment, set the basic-auth variables.
