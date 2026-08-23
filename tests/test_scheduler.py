from project_os.scheduler import Scheduler


def test_run_pending_runs_job_on_first_call():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    ran = scheduler.run_pending(now=1000.0)

    assert ran == ["backup"]
    assert calls == ["backup"]


def test_run_pending_skips_job_before_interval_elapses():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    scheduler.run_pending(now=1000.0)
    ran_again = scheduler.run_pending(now=1500.0)

    assert ran_again == []
    assert calls == ["backup"]


def test_run_pending_runs_job_again_after_interval_elapses():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    scheduler.run_pending(now=1000.0)
    ran_later = scheduler.run_pending(now=1000.0 + 3600)

    assert ran_later == ["backup"]
    assert calls == ["backup", "backup"]


def test_run_pending_isolates_a_failing_job_from_others():
    calls = []
    scheduler = Scheduler()

    def _boom():
        raise RuntimeError("simulated failure")

    scheduler.register("broken", interval_seconds=60, func=_boom)
    scheduler.register("healthy", interval_seconds=60, func=lambda: calls.append("healthy"))

    ran = scheduler.run_pending(now=1000.0)

    assert "healthy" in ran
    assert "broken" not in ran
    assert calls == ["healthy"]
