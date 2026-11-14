import os
import tempfile
import threading
import time
from types import SimpleNamespace as NS

_tmp = tempfile.mkdtemp()
os.environ["ASSISTANT_HOME"] = _tmp
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402

from assistant import config, store, tools  # noqa: E402
from assistant.brain import Agent  # noqa: E402
from assistant.safety import Approvals  # noqa: E402
from assistant.tasks import ReminderScheduler, TaskManager  # noqa: E402

notes_sent = []


@pytest.fixture(autouse=True)
def services():
    notes_sent.clear()
    ap = Approvals(lambda t, m: notes_sent.append((t, m)))
    ap.interactive_confirm = lambda d: True
    tools.SERVICES.approvals = ap
    yield ap


class FakeClient:
    """Scripted model: returns a queue of responses."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = NS(create=self._create)
        self.calls = 0

    def _create(self, **kw):
        self.calls += 1
        return self.responses.pop(0)


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


def use(name, args, id="t1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=id, name=name, input=args)])


def test_agent_tool_loop_and_todo():
    c = FakeClient([use("add_todo", {"title": "call mom", "due": "2030-01-01T09:00"}), text("Added your reminder.")])
    out = Agent(c).run("remind me to call mom")
    assert out == "Added your reminder."
    assert "call mom" in tools.list_todos()
    assert "2030-01-01T09:00" in tools.list_todos()


def test_unknown_tool_and_errors_are_returned_not_raised():
    assert tools.execute_tool("nope", {}).startswith("ERROR")
    assert tools.execute_tool("add_todo", {"title": "x", "due": "garbage"}).startswith("ERROR")


def test_organize_plan_apply_undo(tmp_path):
    for n in ["a.pdf", "b.jpg", "c.zip", "d.unknownext", "e.crdownload"]:
        (tmp_path / n).write_text("x")
    (tmp_path / "folder").mkdir()
    plan = tools.execute_tool("organize_plan", {"folder": str(tmp_path)})
    assert "4 files" in plan and (tmp_path / "a.pdf").exists()  # nothing moved yet
    pid = plan.split("plan_id=")[1].split(":")[0]
    assert "Moved 4" in tools.execute_tool("organize_apply", {"plan_id": pid})
    assert (tmp_path / "Documents" / "a.pdf").exists() and (tmp_path / "Other" / "d.unknownext").exists()
    assert (tmp_path / "e.crdownload").exists()  # partial download untouched
    assert "Restored 4" in tools.execute_tool("organize_undo", {})
    assert (tmp_path / "a.pdf").exists()


def test_risky_action_denied_does_nothing(tmp_path, services):
    services.interactive_confirm = lambda d: False
    (tmp_path / "a.pdf").write_text("x")
    plan = tools.execute_tool("organize_plan", {"folder": str(tmp_path)})
    pid = plan.split("plan_id=")[1].split(":")[0]
    out = tools.execute_tool("organize_apply", {"plan_id": pid})
    assert "did not approve" in out and (tmp_path / "a.pdf").exists()


def test_run_code_needs_approval_and_runs(services):
    assert "hello" in tools.execute_tool("run_code", {"language": "python", "code": "print('hello')"})
    services.interactive_confirm = lambda d: False
    assert "did not approve" in tools.execute_tool("run_code", {"language": "python", "code": "print('no')"})


def test_blocked_and_workspace_paths():
    assert tools.execute_tool("read_file", {"path": "~/.ssh/id_rsa"}).startswith("ERROR")
    assert tools.execute_tool("write_file", {"path": "../escape.txt", "content": "x"}).startswith("ERROR")
    assert "Wrote" in tools.execute_tool("write_file", {"path": "ok/a.txt", "content": "hi"})


def test_notes_roundtrip():
    out = tools.execute_tool("save_note", {"title": "Test Note", "content": "body"})
    name = out.split("/")[-1]
    assert "body" in tools.execute_tool("read_note", {"name": name})


def test_background_task_runs_and_notifies():
    c = FakeClient([text("All done, summary here.")])
    tm = TaskManager(lambda tid, cancel: Agent(c, tid, cancel), lambda t, m: notes_sent.append((t, m)))
    tid = tm.start("do a thing")
    for _ in range(50):
        if store.query("SELECT status FROM tasks WHERE id=?", (tid,))[0]["status"] == "done":
            break
        time.sleep(0.1)
    row = store.query("SELECT * FROM tasks WHERE id=?", (tid,))[0]
    assert row["status"] == "done" and "summary" in row["result"]
    assert any("finished" in t for t, _ in notes_sent)


def test_background_risky_action_waits_for_approval(services):
    c = FakeClient([use("run_code", {"language": "python", "code": "print('bg ok')"}), text("Ran it.")])
    tm = TaskManager(lambda tid, cancel: Agent(c, tid, cancel), lambda t, m: notes_sent.append((t, m)))
    tid = tm.start("run something")
    for _ in range(50):
        if services.list_pending():
            break
        time.sleep(0.1)
    pending = services.list_pending()
    assert len(pending) == 1 and pending[0]["task_id"] == tid
    assert services.resolve(pending[0]["id"], True)
    for _ in range(80):
        if store.query("SELECT status FROM tasks WHERE id=?", (tid,))[0]["status"] == "done":
            break
        time.sleep(0.1)
    assert store.query("SELECT status FROM tasks WHERE id=?", (tid,))[0]["status"] == "done"


def test_background_agents_cannot_spawn_tasks():
    names = {s["name"] for s in tools.schemas(background=True)}
    assert "start_background_task" not in names and "resolve_approval" not in names
    assert "start_background_task" in {s["name"] for s in tools.schemas()}


def test_reminder_fires_once():
    tools.execute_tool("add_todo", {"title": "stand up", "due": "2000-01-01T00:00"})
    s = ReminderScheduler(lambda t, m: notes_sent.append((t, m)))
    s.check_once()
    s.check_once()
    assert [m for t, m in notes_sent if t == "Reminder"].count("stand up") == 1


def test_history_trim_keeps_valid_pairs():
    a = Agent(None)
    for i in range(30):
        a.messages += [{"role": "user", "content": f"q{i}"},
                       {"role": "assistant", "content": [NS(type="tool_use", id=str(i), name="x", input={})]},
                       {"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(i), "content": "r"}]},
                       {"role": "assistant", "content": [NS(type="text", text="ok")]}]
    a._trim(a.messages)
    assert len(a.messages) <= 40 and a.messages[0]["role"] == "user" and isinstance(a.messages[0]["content"], str)


def test_cancel_stops_agent():
    ev = threading.Event()
    ev.set()
    assert Agent(FakeClient([]), 1, ev).run("x") == "Cancelled."
