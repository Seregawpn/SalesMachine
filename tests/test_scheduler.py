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
