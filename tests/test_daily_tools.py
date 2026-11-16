from datetime import datetime, timedelta

from assistant import store, tasks, tools


def test_complete_and_forget_report_missing_ids():
    assert "no to-do #99" in tools.complete_todo(99)
    assert "no memory #99" in tools.forget(99)
    tid = int(tools.add_todo("x").split("#")[1].split(":")[0])
    assert "Marked" in tools.complete_todo(tid)


def test_bad_due_tells_model_the_format():
    out = tools.execute_tool("add_todo", {"title": "x", "due": "tomorrow 10am"})
    assert out.startswith("ERROR") and "2026-11-12T09:00" in out


def test_repeating_reminder_reschedules_instead_of_finishing():
    past = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")
    tools.add_todo("water plants", past, "daily")
    heard = []
    tasks.ReminderScheduler(lambda t, m: heard.append(m)).check_once()
    row = store.query("SELECT * FROM todos WHERE title='water plants'")[0]
    assert heard == ["water plants"] and row["notified"] == 0 and row["due"] > past and row["done"] == 0
    tasks.ReminderScheduler(lambda t, m: heard.append(m)).check_once()
    assert heard == ["water plants"]        # not announced again until tomorrow


def test_repeat_needs_a_due_time():
    assert tools.execute_tool("add_todo", {"title": "x", "repeat": "daily"}).startswith("ERROR")


def test_next_due_rules():
    now = datetime(2026, 11, 13, 10, 0)       # a Friday
    assert tasks.next_due("2026-11-13T09:00", "daily", now) == "2026-11-14T09:00"
    assert tasks.next_due("2026-11-13T09:00", "weekdays", now) == "2026-11-16T09:00"   # skips the weekend
    assert tasks.next_due("2026-11-13T09:00", "weekly", now) == "2026-11-20T09:00"
    assert tasks.next_due("2026-01-31T09:00", "monthly", datetime(2026, 2, 1)) == "2026-02-28T09:00"


def test_two_code_runs_in_one_second_do_not_share_a_file(monkeypatch):
    from assistant import guard
    monkeypatch.setattr(tools.time, "time", lambda: 1000.0)
    a, b = tools.run_code("python", "print('a')"), tools.run_code("python", "print('b')")
    assert "a" in a and "b" in b
    assert len(list(tools.config.WORKSPACE.glob("run_*.py"))) >= 2


def test_cancel_after_finish_says_so():
    tm = tasks.TaskManager(lambda tid, c: type("A", (), {"run": lambda s, t: "ok"})(), lambda *a: None)
    tid = tm.start("x")
    import time
    for _ in range(50):
        if store.query("SELECT status FROM tasks WHERE id=?", (tid,))[0]["status"] == "done":
            break
        time.sleep(0.05)
    assert tm.cancel(tid) is False
