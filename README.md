# SharEl sharing report — Dash web app

Upload a SharEl CSV export (from the EDC portal) and get an interactive report of
electricity sharing in the group. Optionally, recompute the sharing with the proposed
**exact static method** (`presna_staticka.py`) and compare it side by side with today's
EDC result.

## Features

**Report (from `plot_energy_sharing.py`)**

* **General information**: period, number of intervals, producer, peak production, best
  sharing day, and headline figures. These are production, shared, "could have been
  shared", surplus above group demand, members' consumption and energy from the grid.
* **Total energy by flow**: subplot 1 of Figure 1.
* **Shared vs unshared surplus**: the pie, Figure 2.
* **Daily energy by destination**: subplot 2. **Click a day** to select it; a dashed line
  marks the selected day.
* **Sharing on the selected day**: subplot 4, 15-min steps from 06:00 to 21:00. It is always
  placed directly under the daily plot. Its y axis is fixed over the whole period, so days
  compare on one scale.
* **Heatmap hour × month**: subplot 3, optional. It shows total outgoing energy as in the
  script, or shared energy, or unmet demand.
* **Per-destination table.**
* **Selection panel**:
  * destinations on/off, names and allocation keys;
  * the selected day (◀ date ▶, or click the daily plot);
  * y scale linear (stacked) or log (lines), and unshared/unmet flows on or off;
  * heatmap on/off and its metric;
  * sharing-group ID and CZ/EN.

**Exact static method (proposal)**

* The button recomputes every 15-min interval with `rozdel()`. A progress bar runs while it
  works, and the result appears side by side with today's report. Paired plots share their
  axes, and the selected day is the same in both columns.
* **Allocation keys**: empty fields are estimated from the report by fitting a replay of
  today's 5-round EDC method. The page shows how many intervals the replay reproduces with
  the keys used.
* **Timing**: the page reports the number of `rozdel()` evaluations (split into night,
  production covering everyone, and level H computed), the total time, and the time per
  interval. The loop runs in a separate worker process and is timed with its CPU clock.

## Run locally

```bash
pip install -r requirements.txt
python app.py                  # http://127.0.0.1:8050
```

or exactly as in production:

```bash
gunicorn app:server --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:8050
```

## Deploy on Render

The repo contains a Blueprint (`render.yaml`), a pinned `requirements.txt` and
`.python-version` (3.11).

1. Push this folder to a GitHub repository.
2. In Render: **New → Blueprint**, pick the repo, and confirm. Render reads `render.yaml`.
   It asks for `BASIC_AUTH_USER` / `BASIC_AUTH_PASSWORD`; leave them empty for a public app.
   To do it by hand instead, create a **New → Web Service** with runtime Python and:
   * Build command: `pip install -r requirements.txt`
   * Start command: `gunicorn app:server --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT`
   * Health check path: `/healthz`
3. Every push to the default branch redeploys the service.

**Must stay one worker (`--workers 1`).** Uploaded reports, recompute jobs and their progress
live in the memory of one process. With more workers, a request can land in a process that
does not have the upload. Threads are fine and are needed, because they serve the progress
polling while a recompute runs.

**Plan.** The **Free** plan works. It spins down after 15 minutes without traffic, the next
visit waits about a minute, and uploaded reports are gone after spin-down. The page then asks
you to upload the file again. The **0.5c-512mb** plan ($7/month) stays up.

**Memory.** Both plans have 512 MB. The app uses about 95 MB plus about 20–25 MB per cached
report, including its recompute. `SHAREL_CACHE_MAX` (default 6) caps how many reports stay in
memory, oldest dropped first.

**Speed.** Instances have less than one CPU, so key estimation (about 2 s here) and the
recompute take several times longer. The progress bar shows it, and the measured time per
interval reflects the instance.

**Privacy.** Uploaded files are only parsed in memory and never written to disk. The public URL
is open to anyone unless you set both `BASIC_AUTH_USER` and `BASIC_AUTH_PASSWORD`; then the
whole app asks for them (HTTP basic auth). Real CSVs are ignored by `.gitignore`, so meter data
does not end up in the repo.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SHAREL_CACHE_MAX` | `6` | reports kept in memory |
| `SHAREL_MAX_UPLOAD_MB` | `25` | largest accepted CSV |
| `BASIC_AUTH_USER`, `BASIC_AUTH_PASSWORD` | empty | password-protect the app when both are set |
| `PORT` | set by Render | port for gunicorn |

## Files

| File | Purpose |
|---|---|
| `app.py` | Dash layout and callbacks, job runner, config, `/healthz`, optional basic auth |
| `sharel_core.py` | CSV loading and statistics (pandas). Columns keyed by EAN |
| `figures.py` | Plotly figures (colours as in the matplotlib script) |
| `recompute.py` | Exact static recompute (worker process, timing), EDC replay, key fitting |
| `presna_staticka.py` | Reference implementation of the exact static method (unchanged) |
| `i18n.py` | CZ/EN strings and number formatting |
| `assets/style.css` | Styles (Dash loads it automatically) |
| `render.yaml`, `.python-version`, `requirements.txt` | Render deployment |

## Notes

* Both export layouts are auto-detected: the part report (`<ean>-<ean>` columns, shared energy
  only) and the all report (`IN/OUT-<ean>-D/O`). Recompute, the pie and the unmet/unshared
  flows need the all report.
* The worker process uses `fork`, which Linux (Render) and macOS provide. On Windows, the loop
  runs in the server process instead, and its timing can come out higher.
* Checked against group 0000018947 (09/2025–09/2026):
  * Today (EDC): production 4 275 kWh, shared 2 235 kWh (52.3 %), could have been shared
    367 kWh (8.6 %).
  * Exact static method with the recovered keys 50 / 4 × 10 %: shared 2 601.7 kWh
    (+366.7 kWh).
