import multiprocessing as mp
import os
import signal
import threading
import time

import numpy as np
import pytest

from procjob import JobCancelled, JobTimeout, run_in_child


# module-level so the forked child can simply inherit them
def _square_sum(a, progress):
    progress("work", 0.0)
    progress("work", 0.5)
    progress("work", 1.0)
    return float((a ** 2).sum())


def _fails(progress):
    raise ValueError("boom")


def _sleeps(progress):
    progress("work", 0.1)
    time.sleep(60)


def _dies(progress):
    os._exit(3)


def _noop(*_):
    pass


def test_result_and_progress_are_relayed():
    seen = []
    a = np.arange(1000.0)
    out = run_in_child(_square_sum, (a,), progress=lambda p, f: seen.append((p, f)))
    assert out == float((a ** 2).sum())
    assert seen[0] == ("work", 0.0) and seen[-1] == ("work", 1.0)


def test_big_arguments_are_inherited_not_pickled():
    a = np.ones(20_000_000)                    # 160 MB: pickling it would take a while
    t0 = time.perf_counter()
    assert run_in_child(_square_sum, (a,), progress=_noop) == 20_000_000.0
    assert time.perf_counter() - t0 < 5


def test_child_exception_is_reported():
    with pytest.raises(RuntimeError, match="boom"):
        run_in_child(_fails, progress=_noop)


def test_child_that_dies_is_reported():
    with pytest.raises(RuntimeError, match="exited"):
        run_in_child(_dies, progress=_noop)


def test_cancel_kills_the_child_quickly():
    flag = threading.Event()
    threading.Timer(0.6, flag.set).start()
    t0 = time.perf_counter()
    with pytest.raises(JobCancelled):
        run_in_child(_sleeps, progress=_noop, cancelled=flag.is_set)
    assert time.perf_counter() - t0 < 3
    assert not mp.active_children()


def test_timeout_kills_the_child():
    t0 = time.perf_counter()
    with pytest.raises(JobTimeout):
        run_in_child(_sleeps, progress=_noop, timeout=0.7)
    assert time.perf_counter() - t0 < 4
    assert not mp.active_children()


def test_child_dies_even_if_the_parent_ignores_sigterm():
    """gunicorn workers install a SIGTERM handler that only sets a flag; the child must
    not inherit it, or terminate() would not stop it."""
    old = signal.signal(signal.SIGTERM, lambda *_: None)
    try:
        flag = threading.Event()
        threading.Timer(0.5, flag.set).start()
        with pytest.raises(JobCancelled):
            run_in_child(_sleeps, progress=_noop, cancelled=flag.is_set)
        assert not mp.active_children()
    finally:
        signal.signal(signal.SIGTERM, old)


def test_two_children_run_side_by_side():
    results, errs = [], []

    def go(i):
        try:
            results.append(run_in_child(_square_sum, (np.full(10, float(i)),), progress=_noop))
        except Exception as exc:  # pragma: no cover
            errs.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in (1, 2, 3)]
    [th.start() for th in threads]
    [th.join(20) for th in threads]
    assert not errs and sorted(results) == [10.0, 40.0, 90.0]


def _allocates(mb, progress):
    from procjob import limit_memory
    limit_memory(mb)
    return len(bytearray(400 * 2**20))          # 400 MB: more than the budget


def _small_after_limit(progress):
    from procjob import limit_memory
    limit_memory(50)
    return sum(range(1000))


def test_a_child_over_its_memory_budget_fails_alone():
    """The budget makes the allocation fail in the child (MemoryError), which still
    reports it; the parent keeps running."""
    with pytest.raises(MemoryError):
        run_in_child(_allocates, (50,), progress=_noop)
    assert run_in_child(_small_after_limit, progress=_noop) == 499500   # result still sent
    assert not mp.active_children()


def test_reraise_gives_the_childs_own_exception():
    with pytest.raises(ValueError, match="boom"):
        run_in_child(_fails, progress=_noop, reraise=True)


def test_a_killed_child_is_told_apart():
    from procjob import WorkerDied
    with pytest.raises(WorkerDied) as died:
        run_in_child(_killed, progress=_noop)
    assert died.value.killed
    with pytest.raises(WorkerDied) as died:
        run_in_child(_dies, progress=_noop)
    assert not died.value.killed and died.value.exitcode == 3


def _killed(progress):
    os.kill(os.getpid(), signal.SIGKILL)


def test_children_are_the_first_to_go_when_memory_runs_out():
    assert run_in_child(_oom_score, progress=_noop) == 1000


def _oom_score(progress):
    with open("/proc/self/oom_score_adj") as f:
        return int(f.read())
