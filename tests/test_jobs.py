"""Background jobs of the web app: child process, cancellation, abandoned pages."""
import multiprocessing as mp
import time

import pytest

import app
import keyfit
import edc_data as core
from conftest import all_report_csv, synthetic_group


def _slow_estimate(P, D, S, progress=None, **_):
    progress("fit", 0.1)
    time.sleep(60)


@pytest.fixture
def entry_key():
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    data = core.load_report(all_report_csv(P, D, S))
    key = app._cache_put("t.csv", data)
    yield key
    app._cache_drop(key)


def _wait(job, seconds=20):
    t0 = time.perf_counter()
    while not job["done"] and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job["done"]


def test_fit_job_runs_in_a_child_and_stores_the_result(entry_key):
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    job = app._JOBS[job_id]
    _wait(job)
    assert job["error"] is None and not job.get("error_key")
    fit = app._cache_get(entry_key).fit
    assert fit is not None and len(fit.keys) == 5 and fit.match > 0.9
    assert not mp.active_children()


def test_replacing_the_upload_cancels_its_running_job(entry_key, monkeypatch):
    monkeypatch.setattr(app, "estimate_keys", _slow_estimate)
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    job = app._JOBS[job_id]
    time.sleep(1.0)
    assert job["phase"] == "fit" and not job["done"]
    t0 = time.perf_counter()
    app._cache_drop(entry_key)                  # what a new upload does to the old one
    _wait(job, 5)
    assert job["error_key"] == "job_cancelled" and time.perf_counter() - t0 < 3
    assert not mp.active_children()


def test_a_page_that_stopped_polling_is_abandoned(entry_key, monkeypatch):
    monkeypatch.setattr(app, "estimate_keys", _slow_estimate)
    monkeypatch.setattr(app, "JOB_IDLE_S", 1.0)
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    job = app._JOBS[job_id]
    _wait(job, 10)                              # nobody polls -> cancelled after ~1 s
    assert job["error_key"] == "job_cancelled"
    assert not mp.active_children()


def test_polling_keeps_a_job_alive(entry_key, monkeypatch):
    monkeypatch.setattr(app, "JOB_IDLE_S", 1.0)
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    job = app._JOBS[job_id]
    t0 = time.perf_counter()
    while not job["done"] and time.perf_counter() - t0 < 20:
        app._poll(0, job_id, 0, "cs")
        time.sleep(0.2)
    assert job["done"] and job["error"] is None and not job.get("error_key")


def test_a_cancelled_job_waiting_for_a_slot_leaves_the_queue(entry_key, monkeypatch):
    held = [app._JOB_SLOTS.acquire() for _ in range(app.MAX_JOBS)]   # all slots taken
    try:
        job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
        job = app._JOBS[job_id]
        time.sleep(0.8)
        assert job["phase"] == "queued" and not job["done"]
        app._cache_drop(entry_key)
        _wait(job, 5)
        assert job["error_key"] == "job_cancelled"
    finally:
        for _ in held:
            app._JOB_SLOTS.release()


def test_poll_reports_a_cancelled_job_in_words(entry_key, monkeypatch):
    monkeypatch.setattr(app, "estimate_keys", _slow_estimate)
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    time.sleep(0.8)
    app._cache_drop(entry_key)
    _wait(app._JOBS[job_id], 5)
    out = app._poll(0, job_id, 0, "cs")
    assert out[0] is True and out[1] is False and "zrušen" in out[4]


def test_healthz_counts_jobs(entry_key, monkeypatch):
    monkeypatch.setattr(app, "estimate_keys", _slow_estimate)
    job_id, _ = app._start_background("fit", entry_key, [None] * 5, 0.0, "cs")
    time.sleep(0.8)
    body = app._healthz()
    assert body["status"] == "ok" and body["jobs_running"] >= 1 and body["max_jobs"] == app.MAX_JOBS
    app._cache_drop(entry_key)
    _wait(app._JOBS[job_id], 5)
