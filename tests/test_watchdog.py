"""Tests for deploy/watchdog.py: it must stay quiet when the bot is healthy and speak up when it is stalled."""
import datetime as dt, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import watchdog  # noqa: E402

NOW = dt.datetime(2026, 11, 23, 12, 0, tzinfo=dt.timezone.utc)
def iso(minutes_ago): return (NOW - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
def run(n, status="completed", conclusion="success", started=60, updated=10):
    return {"run_number": n, "status": status, "conclusion": conclusion, "run_started_at": iso(started), "updated_at": iso(updated)}
def commit(minutes_ago, who="cliperz-bot"): return {"commit": {"author": {"name": who, "date": iso(minutes_ago)}}}

def test_healthy_when_a_run_is_in_progress_and_state_is_fresh():
    assert watchdog.assess([run(3, "in_progress", None, started=20, updated=20), run(2)], [commit(15)], NOW) == []

def test_stuck_run_is_reported():
    p = watchdog.assess([run(3, "in_progress", None, started=90, updated=90)], [commit(15)], NOW)
    assert any("stuck" in x for x in p)

def test_no_active_run_for_a_long_time_is_reported():
    p = watchdog.assess([run(3, updated=40), run(2, updated=95)], [commit(15)], NOW)
    assert any("no bot run is active" in x for x in p)

def test_a_short_gap_between_runs_is_fine():
    assert watchdog.assess([run(3, updated=8), run(2, updated=60)], [commit(15)], NOW) == []

def test_repeated_failures_are_reported_but_cancelled_runs_are_not():
    fail = [run(5, conclusion="failure"), run(4, conclusion="failure"), run(3)]
    assert any("failed" in x for x in watchdog.assess([run(6, "in_progress", None, started=5, updated=5)] + fail, [commit(15)], NOW))
    cancelled = [run(5, conclusion="cancelled"), run(4, conclusion="cancelled"), run(3)]
    assert watchdog.assess([run(6, "in_progress", None, started=5, updated=5)] + cancelled, [commit(15)], NOW) == []

def test_stale_state_is_reported():
    p = watchdog.assess([run(3, "in_progress", None, started=5, updated=5)], [commit(4 * 60)], NOW)
    assert any("no bot state has been saved" in x for x in p)

def test_other_authors_commits_do_not_count_as_bot_state():
    p = watchdog.assess([run(3, "in_progress", None, started=5, updated=5)], [commit(5, who="someone")], NOW)
    assert any("no bot state commits" in x for x in p)

def test_no_runs_at_all():
    assert watchdog.assess([], [commit(5)], NOW)

def test_alert_is_limited_to_one_window_every_two_hours():
    t = lambda h, m: dt.datetime(2026, 11, 23, h, m, tzinfo=dt.timezone.utc)
    assert watchdog.should_alert(t(12, 17)) and not watchdog.should_alert(t(12, 47))
    assert not watchdog.should_alert(t(13, 17)) and watchdog.should_alert(t(14, 17))
