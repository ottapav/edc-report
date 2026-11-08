"""Background jobs of the web app: child process, cancellation, abandoned pages."""
import multiprocessing as mp
import time

import pytest
from pandas.errors import ParserError

import app
import config
import jobs
import store
import edc_data as core
from ui import compute
from conftest import all_report_csv, synthetic_group


def _slow_estimate(P, D, S, progress=None, **_):
    progress("fit", 0.1)
    time.sleep(60)


@pytest.fixture
def entry_key():
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    data = core.load_report(all_report_csv(P, D, S))
    key = store.put("t.csv", data)
    yield key
    store.drop(key)


def _wait(job, seconds=20):
    t0 = time.perf_counter()
    while not job.done and time.perf_counter() - t0 < seconds:
        time.sleep(0.05)
    assert job.done


def test_fit_job_runs_in_a_child_and_stores_the_result(entry_key):
    job_id = jobs.start_fit(entry_key)
    job = jobs.JOBS[job_id]
    _wait(job)
    assert job.error is None and not job.error_key
    fit = store.get(entry_key).fit
    assert fit is not None and len(fit.keys) == 5 and fit.match > 0.9
    assert not mp.active_children()


def test_replacing_the_upload_cancels_its_running_job(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    job_id = jobs.start_fit(entry_key)
    job = jobs.JOBS[job_id]
    time.sleep(1.0)
    assert job.phase == "fit" and not job.done
    t0 = time.perf_counter()
    store.drop(entry_key)                  # what a new upload does to the old one
    _wait(job, 5)
    assert job.error_key == "job_cancelled" and time.perf_counter() - t0 < 3
    assert not mp.active_children()


def test_a_page_that_stopped_polling_is_abandoned(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    monkeypatch.setattr(config, "JOB_IDLE_S", 1.0)
    job_id = jobs.start_fit(entry_key)
    job = jobs.JOBS[job_id]
    _wait(job, 10)                              # nobody polls -> cancelled after ~1 s
    assert job.error_key == "job_cancelled"
    assert not mp.active_children()


def test_polling_keeps_a_job_alive(entry_key, monkeypatch):
    monkeypatch.setattr(config, "JOB_IDLE_S", 1.0)
    job_id = jobs.start_fit(entry_key)
    job = jobs.JOBS[job_id]
    t0 = time.perf_counter()
    while not job.done and time.perf_counter() - t0 < 20:
        compute.poll_state(job_id, 0, "cs")
        time.sleep(0.2)
    assert job.done and job.error is None and not job.error_key


def test_a_cancelled_job_waiting_for_a_slot_leaves_the_queue(entry_key, monkeypatch):
    held = [jobs._SLOTS.acquire() for _ in range(config.MAX_JOBS)]   # all slots taken
    try:
        job_id = jobs.start_fit(entry_key)
        job = jobs.JOBS[job_id]
        time.sleep(0.8)
        assert job.phase == "queued" and not job.done
        store.drop(entry_key)
        _wait(job, 5)
        assert job.error_key == "job_cancelled"
    finally:
        for _ in held:
            jobs._SLOTS.release()


def test_poll_reports_a_cancelled_job_in_words(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    job_id = jobs.start_fit(entry_key)
    time.sleep(0.8)
    store.drop(entry_key)
    _wait(jobs.JOBS[job_id], 5)
    out = compute.poll_state(job_id, 0, "cs")
    assert out[0] is True and out[1] is False and "zrušen" in out[4]


def test_healthz_counts_jobs(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    job_id = jobs.start_fit(entry_key)
    time.sleep(0.8)
    body = app._healthz()
    assert body["status"] == "ok" and body["jobs_running"] >= 1 and body["max_jobs"] == config.MAX_JOBS
    store.drop(entry_key)
    _wait(jobs.JOBS[job_id], 5)


def test_exact_job_with_invalid_keys_reports_why(entry_key):
    job = jobs.JOBS[jobs.start_exact(entry_key, [0.5, 0.4, 0.3, None, None], 0.0)]
    _wait(job)
    assert job.error_key == "keys_sum_over" and store.get(entry_key).exact is None


# --- limits: parsing an upload, one job per kind, the queue, the time limit ---------------


def test_an_upload_is_parsed_in_a_child_with_a_memory_budget(monkeypatch):
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    csv = all_report_csv(P, D, S)
    data = jobs.parse_report(csv)
    assert data.dest_eans == core.load_report(csv).dest_eans and not mp.active_children()
    with pytest.raises(ValueError, match="Unrecognised"):      # parse errors as they are
        jobs.parse_report(b"Datum;Cas od;foo\n1;2;3\n")
    # running out of the budget (procjob's tests show the limit itself works), whether
    # numpy or pandas' own reader notices it
    for oom in (MemoryError(), ParserError("Error tokenizing data. C error: out of memory")):
        monkeypatch.setattr(jobs, "load_report", _raises(oom))
        with pytest.raises(jobs.TooBig):
            jobs.parse_report(csv)
    monkeypatch.setattr(jobs, "load_report", _raises(ParserError("Expected 3 fields")))
    with pytest.raises(ParserError):                           # a broken file is not "too big"
        jobs.parse_report(csv)
    assert not mp.active_children()


def _raises(exc):
    def load(content):
        raise exc
    return load


def test_uploads_are_parsed_one_at_a_time(monkeypatch):
    monkeypatch.setattr(config, "PARSE_WAIT_S", 0.2)
    assert jobs._PARSE.acquire()                               # another upload is parsing
    try:
        with pytest.raises(jobs.Busy):
            jobs.parse_report(b"")
    finally:
        jobs._PARSE.release()


def test_a_new_job_replaces_the_running_one_of_its_kind(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    first = jobs.JOBS[jobs.start_fit(entry_key)]
    time.sleep(0.5)
    second = jobs.JOBS[jobs.start_fit(entry_key)]
    _wait(first, 5)
    assert first.error_key == "job_cancelled" and not second.cancel.is_set()
    store.drop(entry_key)
    _wait(second, 5)


def test_too_many_unfinished_jobs_are_refused(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    monkeypatch.setattr(config, "MAX_PENDING", 2)
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    other = store.put("u.csv", core.load_report(all_report_csv(P, D, S)))
    running = [jobs.JOBS[jobs.start_fit(k)] for k in (entry_key, other)]
    third = store.put("v.csv", store.get(other).data)
    with pytest.raises(jobs.Busy):
        jobs.start_fit(third)
    out = compute.start_job(jobs.start_fit, "cs", entry_key)    # replaces its own: allowed
    assert out["job"] in jobs.JOBS and running[0].cancel.is_set()
    for k in (entry_key, other, third):
        store.drop(k)
    for j in jobs.JOBS.values():
        _wait(j, 5)


def test_busy_server_refuses_with_a_message(entry_key, monkeypatch):
    monkeypatch.setattr(config, "MAX_PENDING", 0)
    out = compute.start_job(jobs.start_fit, "cs", entry_key)
    assert out["cls"] == "progress error" and "vytížen" in out["text"]


def test_a_job_is_stopped_after_its_time_limit(entry_key, monkeypatch):
    monkeypatch.setattr(jobs, "estimate_keys", _slow_estimate)
    monkeypatch.setattr(config, "JOB_TIMEOUT_S", 1.0)
    job = jobs.JOBS[jobs.start_fit(entry_key)]
    _wait(job, 10)
    assert job.error_key == "job_timeout" and not mp.active_children()


def test_a_report_unused_for_its_lifetime_is_deleted(monkeypatch):
    P, D, S, _ = synthetic_group(5, 96 * 30, 5, seed=3)
    key = store.put("t.csv", core.load_report(all_report_csv(P, D, S)))
    assert store.contains(key)
    monkeypatch.setattr(config, "REPORT_TTL_S", 0.3)
    time.sleep(0.2)
    assert store.get(key) is not None                          # a use keeps it
    time.sleep(0.2)
    assert store.contains(key)
    time.sleep(0.2)
    assert not store.contains(key) and store.get(key) is None


def test_the_store_keeps_to_its_memory_budget(monkeypatch):
    P, D, S, _ = synthetic_group(5, 96 * 90, 5, seed=3)
    data = core.load_report(all_report_csv(P, D, S))
    one = 3 * store.data_bytes(data)
    monkeypatch.setattr(config, "CACHE_MB", 2.5 * one / 2**20)   # room for two
    keys = [store.put(f"{i}.csv", data) for i in range(4)]
    assert [store.contains(k) for k in keys] == [False, False, True, True]
    monkeypatch.setattr(config, "CACHE_MB", 0.0)                 # the newest always stays
    assert store.contains(store.put("big.csv", data))
