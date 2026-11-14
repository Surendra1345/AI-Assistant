"""Approval gate. Risky actions (send email, run code, move files) need an explicit yes.

- Foreground request: asks you right away (spoken or typed).
- Background task: parks the request; you get a notification and answer with
  "approve 3" / "deny 3" (typed or spoken) or via the resolve_approval tool.
"""
import itertools
import threading
import time
from typing import Callable, Optional

from . import config


class Approvals:
    def __init__(self, notify: Callable[[str, str], None]):
        self._notify = notify
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}
        self._ids = itertools.count(1)
        self.interactive_confirm: Optional[Callable[[str], bool]] = None

    def request(self, tool: str, description: str, task_id: Optional[int] = None, timeout: int = 1800) -> bool:
        if tool in config.AUTO_APPROVE:
            return True
        if task_id is None:
            if self.interactive_confirm is None:
                return False
            return bool(self.interactive_confirm(description))
        # background: park and wait
        aid = next(self._ids)
        entry = {"id": aid, "tool": tool, "description": description, "task_id": task_id,
                 "event": threading.Event(), "approved": None, "created": time.time()}
        with self._lock:
            self._pending[aid] = entry
        self._notify("Approval needed", f"Task {task_id} wants to: {description}. Say 'approve {aid}' or 'deny {aid}'.")
        entry["event"].wait(timeout)
        with self._lock:
            self._pending.pop(aid, None)
        return entry["approved"] is True

    def resolve(self, approval_id: int, approve: bool) -> bool:
        with self._lock:
            entry = self._pending.get(approval_id)
        if not entry:
            return False
        entry["approved"] = approve
        entry["event"].set()
        return True

    def list_pending(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in e.items() if k != "event"} for e in self._pending.values()]
