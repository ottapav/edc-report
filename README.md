# EDC sharing report

Interactive web app (Dash) that displays the electricity-sharing data of a Czech sharing
group. The input is the CSV report generated on [edc-cr.cz](https://www.edc-cr.cz), the portal
of the *Elektroenergetické datové centrum* (EDC). Upload the CSV and you get the group's
sharing at a glance. The app also recomputes the whole period with the proposed **exact
static method** (`presna_staticka.py`) and shows the result of the approximate static method (EDC's current implementation) and the exact one side by side,
with the computation timed per 15-min interval.

> **Česky:** Webová aplikace, která zobrazuje data o sdílení elektřiny z CSV reportu
> vygenerovaného na portálu edc-cr.cz. Po nahrání CSV ukáže
> souhrny, denní a hodinové grafy, teplotní mapu a podíl, který „mohl být sdílen“.
> Z reportu odhadne alokační klíče (přibližná statická metoda EDC s 1 nebo 5 koly, i pro velké skupiny).
> Jedním tlačítkem přepočítá sdílení přesnou statickou metodou a porovná ji s dneškem.
> Dalším tlačítkem spočítá vyúčtování sdílené elektřiny podle přínosu (Shapleyho hodnota)
> (zadáte ceny od prodejce a výkupní ceny výroben).
> Rozhraní je v češtině i angličtině, se světlým i tmavým režimem.

![Report of one group, light mode](docs/screenshot-light.png)

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [Using the app](#using-the-app)
- [How the allocation keys are estimated](#how-the-allocation-keys-are-estimated)
- [Exact static method and timing](#exact-static-method-and-timing)
- [Billing by contribution (the Shapley value)](#billing-by-contribution-the-shapley-value)
- [Architecture](#architecture)
- [Performance](#performance)
- [Deployment on Render](#deployment-on-render)
- [Configuration](#configuration)
- [Tests](#tests)
- [Limitations](#limitations)
- [Data and privacy](#data-and-privacy)

## Features

**Report of the approximate static method (EDC)** (the figures of `plot_energy_sharing.py`, interactive):

* **General information and headline figures:**
  * facts: period, 15-min intervals, producer, peak production, best day;
  * energy: production, shared, *could have been shared*, surplus above group demand;
  * consumption: members' consumption and energy from the grid.
* **Total energy by flow:** stacked bars per member (shared | unmet) and for the source
  (shared | shared to unticked members | unshared).
* **Pie "where the production went":** shared to the ticked members, shared to the unticked
  ones (hatched), *could have been shared* (min(unshared, unmet of the ticked members) in the
  same 15 min), and surplus nobody could use. The slices always add up to the production,
  whatever is ticked. For a subset of members that min is only an upper bound (as if the
  ticked members got the whole surplus), so the tile says "at most"; once the exact method
  has been computed, *could have been shared* is what it really adds to the ticked members,
  and the tiles, the pie, the Σ row of the comparison table and the sharing-error box agree.
* **Daily energy:** stacked areas (linear axis) with the grid flows, unshared and unmet, and
  the hatched energy that went to unticked members. **Click a day** to select it.
* **Sharing on the selected day:** 15-min steps from 06:00 to 21:00, always directly under the
  daily plot. The y axis fits the selected day and is shared by both methods, so they compare on one scale.
* **Heatmap hour × month:** the **total production** (independent of the selection) or the
  **total consumption** of the ticked members. A part report has neither, so it shows the
  shared energy. Neither depends on the sharing method, so next to the exact method it is
  shown once (the billing column has its own heatmap in Kč).
* **Per-member table:** consumption, shared, unmet, coverage and data availability.

**Selection panel:**

* Tick members on or off, rename them, and edit their allocation keys. All of this happens in
  one grid, so a group of hundreds of members stays fast.
* ◀ date ▶ for the hourly plot.
* Heatmap metric (production / consumption).
* Group ID for the title.

**Exact static method (proposal):**

* **Keys:** estimated from the report right after upload. You can check and correct them
  before the recompute. They are checked as you type: no key may be negative (the cell turns
  red), and they may add up to at most 100 % (empty cells count with their estimate);
  otherwise the recompute does not start and the card says why.
* **Same keys on both sides:** with keys other than the estimate (or a reserve), the
  recompute also replays the approximate static method (today's EDC rounds) with them, and
  the left column shows that replay instead of the report ("EDC replayed with these keys").
  Tiles, pie, comparison table and the sharing-error box then compare the two methods for
  the same keys; **Odhad** and a new recompute bring the report back. A member with key 0
  gets nothing in either method.
* **Recompute:** one button runs `rozdel()` for every 15-min interval, with a progress bar.
* **Side by side:** the approximate static method (EDC) and the exact method, with shared axes, differences to EDC in
  the tiles, and a per-member comparison table. The two columns share the rows of one grid
  (CSS subgrid): every card sits next to its counterpart at the same height, tile values are
  level, the "by flow" charts keep each member on the same row, and paired plots get the same
  height and number of legend rows, so their x axes line up.
* **Sharing error:** when the recompute is done, a callout gives the error of the approximate static method (EDC)
  algorithm as a percentage of the maximum sharing (what the exact method shares), with the
  kWh missed.
* **Timing:** the number of intervals evaluated, total time, and time per interval, split by
  the method's fast paths.

**Billing by contribution (the Shapley value; proposal):**

* **Prices:** each member's supplier price (the *Price* column of the grid, next to the keys)
  and each producer's feed-in price (the producers' grid above it), or default prices for the
  empty cells. Every number is typed the same way, with a decimal comma or point.
* **Several producers:** the producers share as a pool (any producer can supply any member);
  each has its own feed-in price.
* **Compute:** one button computes the exact Shapley values over the whole report in the
  background, with a progress bar.
* **Right column:** like the exact method, the billing is drawn next to the EDC report, with
  the same cards in Kč: tiles (benefit, what the EDC sharing missed, producer's and members'
  shares, producer's income, feed-in value), the value of the shared electricity per member
  (share + payment), where the benefit went, the daily share (click a day), the selected day
  in 15-min steps and the hour × month heatmap. When both the recompute and the billing
  exist, a switch chooses the right column; a computation that has just finished is shown.
* **Settlement table** (full width below): per member the shared energy, its value at the
  supplier price, the fair share of the benefit, the payment to the producer and the
  effective price per kWh; per producer the energy it shared, its income, its share and the
  feed-in value it gave up.

**Interface:**

* EANs are shown by their last three digits only (anonymity, room in the panel).
* CZ / EN.
* Light and dark mode: the default follows the system, and the ☾/☀ icon switches and
  remembers the choice.
* Works on a phone.

![Approximate (EDC) vs. exact static method, dark mode](docs/screenshot-dark.png)

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
   * **all report** (`IN/OUT-<ean>-D` for each producer, `IN/OUT-<ean>-O` for members) carries
     production and consumption and enables everything (with several producers: the billing,
     not the exact static method; the report does not say which producer supplied whom, so
     the shared energy is shown as one pool);
   * **part report** (`<ean>-<ean>` columns) has shared energy only: no pie, no recompute.
2. The report appears immediately, and the **allocation keys are estimated in the
   background**. A summary shows which EDC method explains the report (1 or 5 rounds) and
   how many 15-min intervals it reproduces. Keys that the report cannot pin down exactly are
   marked, and hovering shows the range of equally consistent values.
3. **Check the keys** against the contract and correct them in the grid if needed; **Odhad**
   restores the estimate. Keys act as ratios in the exact method, and 0 means the member gets
   nothing. Negative keys and a sum over 100 % are refused. An optional *reserve for sale* is
   passed to `rozdel(..., rezerva=)` (and taken off the production of the replayed
   approximate method too).
4. **Recompute.** The second column appears next to the EDC report, and the timing card shows
   the computation.
5. **Explore:**
   * click a day in either daily plot, or use ◀ ▶, to see it in 15-min steps;
   * untick members to see the rest of the group;
   * switch the heatmap between total production and total consumption.

![Daily plot with the selected day, the hourly plot and the heatmap](docs/screenshot-hourly.png)

## How the allocation keys are estimated

The CSV has no keys, but it contains what the approximate static method (EDC) did with them. In every
round each member gets `min(remaining demand, floor(k_i · P_r))`, where `P_r` is the production
left at the start of the round. Groups up to 100 EAN get 5 rounds, larger groups one round.
`keyfit.py` inverts this. The result is a **rough estimate**: it need not be optimal, but it
must never contradict the report.

**Rules that always hold**

* A member that never receives anything while it has demand and there is production gets
  **key 0**. The report only bounds its key from above, and a nonzero key would contradict it.
  A member without any demand while there was production also gets 0 (no phantom key).
* A member that is always fully covered gets the smallest key that keeps it covered.
* The keys never sum above 100 %, and the match with the report (the share of 15-min intervals
  that the approximate method reproduces with these keys) is always measured on **every** interval.

**How it works**

* **Every interval where a member is not fully covered bounds its key.** Such a member was
  never capped, so it received exactly `floor(k_i · P_r)` in each round:
  `sum_r floor(k_i · P_r) = s_i`. That pins `k_i` to a small interval, found exactly by
  bisection. An interval where the member is fully covered gives a lower bound.
* **The key is the value consistent with the most intervals**, on the 0.01 % grid of EDC
  keys. A rounder value nearby (1 %, 0.5 %, …) wins only when the separating intervals do not
  clearly favour the finer one. This absorbs the ~1 % of report rows that do not follow the
  model, without inventing round numbers.
* **One round is separable**, because each member depends only on its own key, so all keys
  come out in one pass over every interval. This covers the groups above 100 EAN.
* **Five rounds couple the members** through `P_r`. The bounds are iterated to a (nearly) fixed
  point from a rank-1 estimate, which needs no `P_r`, because two members short in the same
  interval both got their key's share of the same productions. The fit is then settled by
  replaying the method: moving single keys, and moving all keys together (rounded or rescaled).
  If the match is still below 98 %, a second, uniform start is tried and the better fit kept.
* **The five-round search is rough on purpose.** It works on at most 1 500 informative
  intervals, evenly spread over the period (every member keeps up to 300 of its own), with a
  few iterations and one sweep; small groups (rows × members ≤ 60 000) get the full search on
  all intervals. After 20 s (`FIT_BUDGET_S`) it returns the best keys found so far and the
  page says so. This is as good as the full search on the benchmark, in a tenth of the time.
* Both round counts are tried (5 only up to 100 members, and not when one round already
  explains the report), and the one that reproduces more intervals wins.

For every key the app also returns the **range of values the report fits equally well**. A key
is marked when that range is wider than 0.2 pp or 5 % of the key. Typical causes are a member
that is almost always fully covered (then only a lower bound is known) or one with no data.

**Accuracy and time**, measured by `python bench/keyfit_bench.py` on synthetic one-year groups
(35 040 intervals): EDC shares from known keys, 1 % of intervals perturbed, one CPU core.
"truth" is what the true keys reproduce, so a fit "as good as the truth" cannot do better.

| Members | Keys | EDC rounds | Match with the report (truth) | Keys equal to the true ones | Time |
|---|---|---|---|---|---|
| 20 | random, 0.01 % steps | 5 | 99.0 % (99.0 %) | 85 % | 2 s |
| 60 | whole percent | 5 | 99.0 % (99.0 %) | 90 % | 5 s |
| 60 | random | 5 | 99.0 % (99.0 %) | 92 % | 7 s |
| 100 | random | 5 | 99.0 % (99.0 %) | 99 % | 18 s |
| 150 | random | 1 | 99.0 % (99.0 %) | 100 % | 0.5 s |

The real group 0000018947 (5 members, 1 year) comes out as exactly 50 / 10 / 10 / 10 / 10 %,
reproducing 99.2 % of intervals, in about 3 s. Keys that differ from the true ones are
members whose value the data cannot pin down (every value in the reported range reproduces the
report equally well). The summary shows the match and warns below 95 %, so check those keys
against the contract. On the free Render instance (less than 1 CPU) expect several times
longer.

## Exact static method and timing

`presna_staticka.py` is the reference implementation (unchanged). Each member gets
`s_i = min(D_i, k_i · H)`, with the level `H` computed to the end, so everything that can be
consumed is shared while the keys hold. `recompute.py` calls `rozdel()` for every 15-min
interval of the report and builds a second report in the same structure, so every figure and
table works for both.

**Explanatory article (Czech).** [`clanek/`](clanek/README.md) explains the approximate and
the exact static method, the pool mode for several producers and the results for one real
group, for a broad audience (written for TZB-info, UCEEB ČVUT). The app assembles it from
`clanek/clanek.html` and the figures in `clanek/schemata.py` on every request, serves it at
`/clanek/` and links it from the *Exact static method* card, so an edit in the repository is
what the app shows.

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

## Billing by contribution (the Shapley value)

`billing.py` splits the benefit of sharing between the producers and the members by the
Shapley value. The benefit of a kWh that producer *i* shares to member *j* is `p_j − f_i`
(supplier price minus feed-in price). The keys do not enter the Shapley value: they decide
who got the energy, the Shapley value decides who deserves the money.

**The game.** In every 15-min interval a coalition is worth what it could save with the best
sharing, the producers' surplus shared as a pool: the cheapest production goes first to the
members with the highest price. With all distinct prices sorted, λ_0 < λ_1 < …,
`v(S) = Σ_k Δλ_k · min(G_k(S), D_k(S))`, where layer *k* holds the producers with
`f ≤ λ_k` (surplus `G_k`) and the members with `p ≥ λ_{k+1}` (demand `D_k`). Shapley values
add up, so the year is the sum of the intervals and the layers.

**Exact algorithm** (energies in hundredths of kWh, like EDC data, so nothing is rounded):

* nothing to share: nothing; a layer with one producer that covers its demand: every member
  gets `d_j / 2` of it, the producer the rest; a layer with one member that takes all its
  surplus: every producer gets `g_i / 2` (closed forms, all such intervals at once);
* otherwise, with the balance `Z = D(S) − G(S)` and `H(a) = Σ_{s≤a} P(Z ≤ s)`:
  `φ_j = ∫₀¹ H₋ⱼ(−1) − H₋ⱼ(−1 − d_j) du` for a member and
  `φ_i = g_i − ∫₀¹ H₋ᵢ(g_i − 1) − H₋ᵢ(−1) du` for a producer (Owen's multilinear extension).
  The integrand is a Bernstein polynomial with coefficients in [0, d_j], so Gauss–Legendre
  needs far fewer than m/2 nodes: a rigorous error bound (Bernstein ellipse) picks the smallest
  even count for 10⁻¹³ relative error (12 nodes for 20 players, 46 for 150);
* one DP per node gives the distribution of *Z*: the members sorted by price (every layer is
  a prefix of them), then each layer's producers; node 1 − u is the mirror image of u, so
  half the nodes need a DP;
* leaving a player out needs no deconvolution: a finite geometric series turns `H₋ᵢ` into
  lookups in *H*, summed over the player's layers with weights Δλ (a member is in the first
  layers, a producer in the last ones).

The approach — Owen's integral over u plus a DP of the distribution of a weighted sum — is the
one of F. Illés, *Linearly representable games and pseudo-polynomial calculation of the
Shapley value* ([arXiv:2205.12324](https://arxiv.org/abs/2205.12324)), for games whose value
depends only on a sum of player weights. Here `min(G, D) = D − (D − G)⁺` is an additive game
plus such a game; the code extends it with signed weights (producers), price layers, a
rigorous node count for the quadrature and the leave-one-out series. Energy-sharing papers
with batteries (e.g. [arXiv:1903.11047](https://arxiv.org/abs/1903.11047),
[arXiv:2301.00174](https://arxiv.org/abs/2301.00174)) estimate the Shapley value by sampling,
because there the value of each coalition comes from a simulation or optimisation over time.

The suite checks the result against brute force over all coalitions (one and several
producers, mixed prices, members without demand, prices below the feed-in price) to 10⁻⁹ Kč.

**Settlement.** The Shapley values of the best sharing are scaled to the benefit the EDC
report really achieved, `Σ p_j · s_j − Σ f_i · q_i` (`s_j` shared to member *j*, `q_i`
shared by producer *i*). Member *j* pays `p_j · s_j − share_j` (in whole haléř); the payments
make a pool from which each producer gets the feed-in value of its shared energy plus its
share (whole haléř, adding up to the payments). The page shows how much of the best possible
benefit the report achieved.

**Plots.** The computation also keeps the Shapley values of every 15-min interval with
production (float32, about 4 bytes per member and interval), scaled the same way, so the
daily, hourly and heatmap figures add up to the settlement.

**Time** (one core, synthetic groups, `compute_shapley`):

| Members | Producers | Period | Distinct prices | Time |
|---|---|---|---|---|
| 5 | 1 | 1 year | 4 | 3 s |
| 5 | 3 | 1 year | 5 + 3 feed-in | 19 s |
| 20 | 1 | 3 months | 19 | 6 s |
| 50 | 1 | 1 month | 45 | 17 s |
| 150 | 1 | 1 month | 1 | 38 s |
| 150 | 3 | 1 month | 1 + 3 feed-in | 1.6 min |
| 150 | 1 | 1 month | 113 | 3 min |

The cost grows with the number of members, the size of the production and demand in
hundredths of kWh, and the number of distinct prices. With several producers the closed
forms rarely apply, so more intervals need the quadrature. Expect several times longer on the free Render instance.

## Architecture

The code is in three layers. The domain modules know nothing about the web page; the
server state keeps uploads and running computations; the UI builds the page and its
callbacks from both.

| Layer | File | Role |
|---|---|---|
| Domain | `edc_data.py` | CSV parsing (both layouts), per-member frames keyed by EAN, statistics; memoised derived data |
| | `keyfit.py` | Replay of the approximate static method (EDC) (numpy, in blocks), rough key estimation for 1 and 5 rounds |
| | `presna_staticka.py` | Reference implementation of the exact static method |
| | `recompute.py` | Exact static recompute (the `rozdel()` loop in a child process), timing, sharing error |
| | `billing.py` | Shapley values of the billing (exact, price layers), the settlement in Kč, values per 15 min |
| | `procjob.py` | Runs a function in a forked child with progress, cancellation and a time limit |
| | `figures/` | Plotly figures: `base.py` themes, member colours and the shared chart shapes (stacked bars, pie, stacked areas by day and within a day, heatmap, pairing of the two columns); `energy.py` the report in kWh; `money.py` the billing in Kč |
| | `i18n.py` | CZ/EN strings and number formatting |
| Server state | `config.py` | Settings from environment variables |
| | `store.py` | Uploaded reports and their results (key estimate, recompute, billing), newest `EDC_CACHE_MAX` kept |
| | `jobs.py` | Background computations: queue, child process, cancellation, progress |
| UI | `ui/layout.py` | The page; both computation cards come from one `job_card()` with ids `<kind>-btn`, `<kind>-progress`, … |
| | `ui/members.py` | The members grid (tick, name, key, price) and reading what was typed in it |
| | `ui/widgets.py`, `ui/views.py` | Tiles, facts, tables, result summaries (pure functions of the data) |
| | `ui/panel.py` | Callbacks: labels (one table of id, property and string), theme, upload, grid buttons |
| | `ui/compute.py` | Callbacks of the computation cards: start, one shared progress poll, results |
| | `ui/report.py` | Callbacks of the report: the two columns, the hourly plot, the selected day |
| App | `app.py` | Creates the Dash app, `/healthz`, optional basic auth |
| | `assets/style.css` | Styles, light/dark variables (Dash loads it automatically) |
| | `gunicorn.conf.py`, `render.yaml`, `.python-version` | Deployment |
| Checks | `tests/` | pytest suite (synthetic data, no real CSV needed) |
| | `bench/keyfit_bench.py` | Reproducible accuracy / time benchmark of the key estimate (synthetic data) |

**One process on purpose.** An upload, its key estimate, a running recompute and its progress
live in the memory of one process, and every request of that browser session must reach it.
`gunicorn.conf.py` therefore pins **one worker** (ignoring `WEB_CONCURRENCY`) with threads, and
never recycles it (`max_requests = 0`).

This is the failure mode fixed in robopid-simulator: there, with two workers, the progress
polls of a job reached the worker that did not start it, and the button looked dead. More
workers here would need a shared store such as Redis, not a bigger worker count.

**Background jobs** (`jobs.py`). Key estimation (after upload), the `rozdel()` loop of the
recompute and the Shapley values of the billing each run in a **forked child process**
(`procjob.py`), started from a job thread. The web
server's request threads therefore stay free for progress polls and page renders, the child
gets a core of its own, and its arguments (big numpy arrays) are shared with the parent by
`fork` instead of being pickled; only progress messages and the small result travel back.
At most `EDC_MAX_JOBS` jobs run at once, and the rest wait in a visible queue. The browser
polls every 200 ms, and only the poll callback draws the progress bar and the button state.
Because a job is a process, it can be **cancelled**, and the slot is freed at once:

* when its report is gone: the same browser uploaded another file, or the report was evicted
  from the store (a job checks this itself, so the store needs no knowledge of jobs);
* when the page stops polling for `EDC_JOB_IDLE_S` seconds (tab closed). A waiting job leaves
  the queue the same way;
* when a key estimate runs longer than `EDC_FIT_TIMEOUT` seconds. It stops itself after about
  20 s with the best keys so far, so this is only a safety net.

The child resets gunicorn's signal handlers, so killing it really stops it. `/healthz` shows
`jobs_running`, `jobs_queued` and `max_jobs`. Two other safeguards:

* the poll is idempotent: every later poll repeats the complete final state, because Dash may
  drop the first "done" response when the next poll overtakes it;
* a job that disappeared (server restarted, or a free instance went to sleep) is reported and
  the button re-enabled, instead of leaving the page waiting.

**Efficiency measures** (from the code review):

* One grid for all members instead of 4 inputs per member. With 600 pattern-matching
  components the Dash renderer needed tens of seconds per update for 150 members.
* Tables are rendered as one HTML block instead of thousands of React components.
* More than 10 members fold into 9 + "Others" in the plots. tab10 has 10 colours and hues
  are never cycled; the ranking comes from the EDC report, so both columns match. Tables keep
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

The app runs on Render as the web service **edc-report** (project *edc-report*, environment
*Production*, free plan, Frankfurt). `render.yaml` is the Blueprint of that service: it is
based on Render's export of the live service, plus the settings the app relies on.

| Setting | Value |
|---|---|
| Build | `pip install -r requirements.txt` (Python 3.11 from `.python-version`) |
| Start | `gunicorn app:server -c gunicorn.conf.py` |
| Health check | `/healthz` |
| Auto-deploy | every commit to `main` |
| Environment | `EDC_CACHE_MAX=6`, `EDC_MAX_UPLOAD_MB=25`, `EDC_MAX_JOBS=2`; optionally `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD` |

To set it up from scratch, use Render → **New → Blueprint** → this repository → **Apply**.

Notes:

* **Existing service:** the live service was created in the dashboard with the start command
  `gunicorn app:app`. That works too: Dash 4 is a WSGI app, and gunicorn loads
  `gunicorn.conf.py` from the repository root on its own. Changes to `render.yaml` reach a
  service only when it is managed by a Blueprint; otherwise set the health check and the
  environment variables in the service settings.

* **Free plan:** 512 MB, and it sleeps after 15 minutes without traffic. The first visit then
  waits about a minute, and uploaded reports are gone; the page says so and asks for the file
  again. The *0.5c-512mb* plan ($7/month) stays up.
* **Memory:** both plans have 512 MB. Keep `EDC_CACHE_MAX` about 6.
* **Keep one worker.** Do not add `--workers N`, and do not rely on `WEB_CONCURRENCY` (see
  *Architecture*).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 8050 (Render sets it) | port for gunicorn |
| `EDC_THREADS` | 8 | request threads of the single worker |
| `EDC_MAX_JOBS` | 2 | key estimations / recomputes running at once (others queue); set to the number of CPUs of the instance |
| `EDC_FIT_TIMEOUT` | 120 | seconds after which a key estimate is killed |
| `EDC_JOB_IDLE_S` | 180 | seconds without a progress poll after which a job is cancelled (page closed) |
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
* the exact method adds exactly the "could have been shared" energy, and for any selection
  the tiles, the pie, the comparison table and the error box give the same number;
* the timing counts every interval;
* the Shapley values of the billing equal brute force over all coalitions, the bounded node
  count matches the exact one, and the settlement adds up (payments, shares, haléř);
* memoisation reuses frames.

## Limitations

* **Several producers:** the billing supports them (pool); the exact static method and the
  key estimate need one producer. The EDC report does not say which producer supplied which
  member, so the energy figures show the producers as one pool.
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
