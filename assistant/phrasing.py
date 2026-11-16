"""Turns raw tool results ("Opened Spotify.") into how an assistant would say them ("Spotify's up and running.").

Used for the fast-path commands that skip the AI, and for single-tool answers from the smaller models. Errors, refusals and
anything unrecognised pass through unchanged, so nothing is ever hidden."""
import random
import re
from datetime import datetime
from typing import Optional

from . import config

_PASS = ("ERROR", "Blocked", "That didn't work", "I couldn't", "I can't", "I'm not allowed", "The user did not approve")


def _title(p: float = 1.0) -> str:
    return f", {config.USER_TITLE}" if config.USER_TITLE and random.random() < p else ""


def _pick(*options: str) -> str:
    return random.choice(options)


def _part_of_day(h: int) -> str:
    return "in the morning" if h < 12 else "in the afternoon" if h < 17 else "in the evening" if h < 21 else "at night"


def _when(due: str) -> str:
    """'2026-11-16T09:00' -> 'today at 9:00 AM' / 'tomorrow at 9:00 AM' / 'on Friday at 9:00 AM'."""
    try:
        d = datetime.strptime(due, "%Y-%m-%dT%H:%M")
    except ValueError:
        return due
    clock = d.strftime("%I:%M %p").lstrip("0")
    days = (d.date() - datetime.now().date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else f"on {d.strftime('%A')}" if 0 < days < 7 else f"on {d.strftime('%d %B')}"
    return f"{day} at {clock}"


def _todos(result: str) -> str:
    items = []
    for ln in result.splitlines():
        m = re.match(r"#\d+\s+(?:\[done\]\s+)?(.*?)(?:\s+—\s+due\s+(\S+))?(?:\s+\(repeats (\w+)\))?$", ln)
        if m:
            t = m.group(1) + (f", {_when(m.group(2))}" if m.group(2) else "") + (f", repeating {m.group(3)}" if m.group(3) else "")
            items.append(t)
    if not items:
        return result
    if len(items) == 1:
        return f"You have one thing on your list: {items[0]}."
    return f"You have {len(items)} things on your list: " + "; ".join(items[:6]) + (f"; and {len(items) - 6} more." if len(items) > 6 else ".")


def _mail(result: str) -> str:
    lines = result.splitlines()
    head = re.match(r"(\d+) unread", lines[0]) if lines else None
    if not head:
        return result
    n = int(head.group(1))
    msgs, hidden = [], 0
    for ln in lines[1:4]:
        if "(hidden" in ln:                       # banking / codes: never read aloud
            hidden += 1
            continue
        m = re.match(r"#\d+\s+(?:\[unread\]\s+)?(.*?)(?:\s*<[^>]*>)?:\s+(.*)$", ln)
        if m:
            msgs.append(f"{m.group(1).strip()}, {re.sub(r'[^\w\s,.!?%$&@\'-]', '', m.group(2)).strip()}")
    if n == 0:
        return _pick("Your inbox is clear.", "No unread mail. You're all caught up.")
    lead = f"You have {n} unread email{'s' if n != 1 else ''}."
    out = lead + (" The latest are from " + "; then ".join(msgs) + "." if msgs else "")
    if hidden:
        out += f" Plus {hidden} private message{'s' if hidden != 1 else ''} I won't read out."
    return out


def humanize(tool: str, result: str, args: Optional[dict] = None) -> str:
    if not isinstance(result, str) or not result or result.startswith(_PASS):
        return result
    args = args or {}
    try:
        if tool == "open_app" and (m := re.match(r"Opened (.+)\.$", result)):
            return _pick(f"Opening {m.group(1)}.", f"{m.group(1)} is up.", f"There you go, {m.group(1)} is open.")
        if tool == "open_file" and (m := re.match(r"Opened (.+?)(?: \((\d+) other matches\))?\.$", result)):
            extra = f" I found {m.group(2)} other match{'es' if m.group(2) != '1' else ''} if that's not the one." if m.group(2) else ""
            return _pick(f"Here's {m.group(1)}.", f"Opening {m.group(1)}.") + extra
        if tool == "open_url":
            return _pick("Opening that in your browser.", "On your screen now.")
        if tool == "quit_app":
            if (m := re.match(r"Closed (.+)\.$", result)):
                return _pick(f"{m.group(1)} is closed.", f"Done, I've closed {m.group(1)}.")
            if (m := re.match(r"(.+) isn't running\.$", result)):
                return f"{m.group(1)} isn't running at the moment."
        if tool == "music_control":
            if result.startswith("Playing in"):
                return _pick("Playing your music.", "Music coming right up.", "Resuming playback.")
            if result == "Paused.":
                return _pick("Paused.", "Music paused.")
            if result == "Next track.":
                return _pick("Skipping ahead.", "Next one coming up.")
            if result == "Previous track.":
                return _pick("Going back.", "Taking it back a track.")
            if (m := re.match(r"(.+) by (.+) \((\w+)\)$", result)):
                return f"That's {m.group(1)} by {m.group(2)}." if m.group(3) == "playing" else f"{m.group(1)} by {m.group(2)} is paused."
            if result.startswith("Nothing is playing"):
                return "Nothing is playing right now."
        if tool == "set_volume" and (m := re.match(r"Volume set to (\d+)\.$", result)):
            return _pick(f"Volume's at {m.group(1)} percent.", f"Done, volume is now {m.group(1)} percent.")
        if tool == "get_time":
            now = datetime.now()
            clock = now.strftime("%I:%M").lstrip("0")
            return _pick(f"It's {clock} {_part_of_day(now.hour)}{_title()}.", f"{clock} {now.strftime('%p')} on {now.strftime('%A')}{_title()}.",
                         f"It's {now.strftime('%A')}, {clock} {now.strftime('%p')}.")
        if tool == "list_todos":
            return "Your list is clear. Nothing outstanding." if result.startswith("Nothing") else _todos(result)
        if tool == "add_todo" and (m := re.match(r"Added #\d+: (.*?)(?: \(due (\S+?)(?:, repeats (\w+))?\))?$", result)):
            if m.group(2):
                rep = f", and I'll repeat it {m.group(3)}" if m.group(3) else ""
                return _pick(f"Reminder set. I'll remind you {_when(m.group(2))}: {m.group(1)}{rep}.",
                             f"Noted. {m.group(1)}, {_when(m.group(2))}{rep}.")
            return _pick(f"Added to your list: {m.group(1)}.", f"Noted: {m.group(1)}.")
        if tool == "complete_todo" and result.startswith("Marked"):
            return _pick("Ticked off.", "Done, marked as complete.", "Consider it done.")
        if tool == "remember" and result == "Remembered.":
            return _pick("Noted. I'll remember that.", "Got it, I'll remember that.")
        if tool == "forget" and result.startswith("Forgot"):
            return "Forgotten."
        if tool == "check_mail":
            return _mail(result)
        if tool == "email_me" and result.startswith("Emailed"):
            return _pick("Sent. It's in your inbox.", "Done. Check your email.")
        if tool == "calculate" and " = " in result:
            return _pick("That comes to ", "The answer is ", "It works out to ") + result.rsplit(" = ", 1)[1] + "."
    except Exception:
        pass
    return result
