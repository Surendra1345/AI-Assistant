"""Background task queue and the reminder scheduler."""
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Callable

from . import config, store


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class TaskManager:
    def __init__(self, agent_factory: Callable, notify: Callable[[str, str], None]):
        self._factory = agent_factory      # (task_id, cancel_event) -> Agent
        self._notify = notify
        self._pool = ThreadPoolExecutor(max_workers=config.MAX_BG_WORKERS)
        self._cancels: dict[int, threading.Event] = {}
        store.execute("UPDATE tasks SET status='interrupted', updated=? WHERE status IN ('queued','running')", (_now(),))

    def start(self, goal: str) -> int:
        tid = store.execute("INSERT INTO tasks (goal, status, created, updated) VALUES (?,?,?,?)",
                            (goal, "queued", _now(), _now()))
        self._cancels[tid] = threading.Event()
        self._pool.submit(self._run, tid, goal)
        return tid

    def cancel(self, tid: int) -> bool:
        ev = self._cancels.get(tid)
        if not ev or ev.is_set():
            return False
        ev.set()
        return True

    def _set(self, tid: int, status: str, result: str = None):
        store.execute("UPDATE tasks SET status=?, result=COALESCE(?, result), updated=? WHERE id=?",
                      (status, result, _now(), tid))

    def _run(self, tid: int, goal: str):
        cancel = self._cancels[tid]
        if cancel.is_set():
            self._set(tid, "cancelled")
            return
        self._set(tid, "running")
        try:
            result = self._factory(tid, cancel).run(
                f"Background task #{tid}. Complete this fully and finish with a brief spoken-style summary of the outcome "
                f"(save long output as a note and mention the file name).\n\nTask: {goal}")
            if cancel.is_set():
                self._set(tid, "cancelled", result)
                return
            self._set(tid, "done", result)
            self._notify(f"Task {tid} finished", result[:300])
            store.execute("INSERT OR IGNORE INTO reported (task_id) VALUES (?)", (tid,))
        except Exception as e:
            self._set(tid, "failed", f"{type(e).__name__}: {e}")
            self._notify(f"Task {tid} failed", str(e)[:200])
            store.execute("INSERT OR IGNORE INTO reported (task_id) VALUES (?)", (tid,))


class ReminderScheduler(threading.Thread):
    """Checks every 20 seconds for to-dos whose due time has passed and announces them."""

    def __init__(self, notify: Callable[[str, str], None], interval: int = 20):
        super().__init__(daemon=True)
        self._notify = notify
        self._interval = interval
        self._halt = threading.Event()

    def check_once(self):
        now = datetime.now().strftime("%Y-%m-%dT%H:%M")
        for r in store.query("SELECT * FROM todos WHERE done=0 AND notified=0 AND due IS NOT NULL AND due<=?", (now,)):
            store.execute("UPDATE todos SET notified=1 WHERE id=?", (r["id"],))
            self._notify("Reminder", r["title"])

    def run(self):
        while not self._halt.is_set():
            try:
                self.check_once()
            except Exception:
                pass
            time.sleep(self._interval)


def battery_status():
    """(percent, on_charger) from macOS, or None if unavailable (desktop Mac, other OS)."""
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5).stdout
        m = re.search(r"(\d+)%", out)
        if not m:
            return None
        return int(m.group(1)), ("discharging" not in out.lower())
    except Exception:
        return None


class ProactiveMonitor(threading.Thread):
    """Speaks up without being asked: low battery, and a heads-up shortly before a reminder is due."""

    def __init__(self, notify: Callable[[str, str], None], interval: int = 60, battery=battery_status):
        super().__init__(daemon=True)
        self._notify, self._interval, self._battery = notify, interval, battery
        self._warned: set = set()
        self._halt = threading.Event()

    def check_once(self):
        # battery: warn at BATTERY_WARN, 10 and 5 percent while unplugged; re-arm when charging
        st = self._battery()
        if st:
            pct, on_charger = st
            if on_charger:
                self._warned.clear()
            else:
                for level in sorted({config.BATTERY_WARN, 10, 5}, reverse=True):
                    if pct <= level and level not in self._warned:
                        self._warned |= {l for l in {config.BATTERY_WARN, 10, 5} if l >= level}
                        self._notify("Battery low", f"Battery is at {pct} percent. You may want to plug in.")
                        break
        # reminders due within the lead time (the exact-time alert is ReminderScheduler's job)
        now = datetime.now()
        lo, hi = now.strftime("%Y-%m-%dT%H:%M"), (now + timedelta(minutes=config.REMIND_LEAD_MIN)).strftime("%Y-%m-%dT%H:%M")
        for r in store.query("SELECT * FROM todos WHERE done=0 AND notified=0 AND pre_notified=0 "
                             "AND due IS NOT NULL AND due>? AND due<=?", (lo, hi)):
            store.execute("UPDATE todos SET pre_notified=1 WHERE id=?", (r["id"],))
            mins = max(1, round((datetime.fromisoformat(r["due"]) - now).total_seconds() / 60))
            self._notify("Coming up", f"In {mins} minutes: {r['title']}")

    def run(self):
        while not self._halt.is_set():
            try:
                self.check_once()
            except Exception:
                pass
            time.sleep(self._interval)
