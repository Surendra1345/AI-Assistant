# Mac Assistant

A private, voice-driven personal assistant for your MacBook. It does what you tell it, including long jobs in the background.

**Local on your Mac:** wake word, speech-to-text (Whisper), speech output (macOS `say`), files, notes, reminders.
**Cloud:** only the *text* of your requests and tool results goes to Claude for planning. Your audio never leaves the Mac.
**Offline fallback:** plain chat via a small Ollama model (no tools).

## Install (M1 Air, 8 GB)

1. Install Python and Ollama (optional, for the offline fallback):
   `brew install python@3.12` and, if you want offline chat, install Ollama then `ollama pull llama3.2:3b`
2. In this folder: `bash setup.sh`
3. Open `.env` and paste your `ANTHROPIC_API_KEY`.
4. Test by typing first: `source .venv/bin/activate && python -m assistant --text`
5. Then voice: `python -m assistant`. Allow Microphone access for Terminal when macOS asks.
   For a first voice test set `WAKE_MODE=enter` in `.env` (press Enter, then speak). Switch to `wakeword` after.

First time you use email, macOS asks to let Terminal control Mail. Click OK.

## What you can say

| Say | What happens |
|---|---|
| "Research how solid-state batteries work and summarize it" | Several searches, reads pages, saves a note, tells you the summary |
| "In the background, compare the top 3 note-taking apps" | Starts task #N, keeps listening, notifies and speaks when done |
| "Organize my Downloads folder" | Shows a plan (nothing moves), asks approval, moves files, can undo |
| "Draft an email to Priya about Friday's meeting" | Opens a draft in Mail for you to review |
| "Send an email to ... saying ..." | Asks "yes or no?" first |
| "Remind me to call the bank tomorrow at 10" | Saved, then spoken + notification at that time |
| "What's on my list?" / "Mark 3 done" | To-do tracker |
| "Write a script that renames my photos by date and run it" | Writes code, shows it, asks approval, runs it, reports output |
| "How's task 2 going?" / "Cancel task 2" | Status / cancel |
| "approve 3" / "deny 3" | Answers an approval a background task is waiting on |

## Safety model

- **Risky actions always ask first**: sending email, running code, moving files. Foreground: spoken/typed yes-no. Background: a notification, then "approve N" / "deny N".
- File moves never delete and can be undone. Drafting is preferred over sending.
- It can't read `~/.ssh`, `~/.aws`, `~/.gnupg`, or Keychains, and only writes inside `~/Assistant/workspace`.
- Web pages are treated as untrusted data; the model is told never to follow instructions found in them, and the approval prompt is the backstop.
- Honest limit: approved code runs as *you* (it isn't sandboxed). Read what it shows you before saying yes.
- Set `AUTO_APPROVE_TOOLS` in `.env` only for tools you fully trust.

## Where things live

`~/Assistant/` holds `notes/`, `workspace/` (code it writes), `plans/`, and `assistant.db` (to-dos, task history).

## 8 GB tips

- Whisper `base.en` uses about 0.5 GB. Keep `MAX_BG_WORKERS=2`.
- Close heavy apps (many Chrome tabs) for faster speech recognition.
- Cost: each request is a few small API calls (usually cents or less). Long research tasks cost more.

## Known limits of this first version

- Voice and macOS parts (wake word, Mail, notifications) were written but could not be run on a Mac during development; the agent loop, tools, approvals, task queue and reminders are covered by automated tests (`pytest tests`). Expect to tweak the wake-word threshold (`WAKE_THRESHOLD`) and silence detection on your mic.
- No calendar, Messages, or music control yet; the tool pattern in `assistant/tools.py` makes adding them a small function each.
- Speaking while the assistant is talking isn't supported (it can't be interrupted yet).
- Reminders live in this assistant's own list, not the Apple Reminders app.

## Adding a tool

In `assistant/tools.py`:

```python
@tool("open_app", "Open a macOS app by name.", {"name": {"type": "string"}}, ["name"])
def open_app(name: str) -> str:
    subprocess.run(["open", "-a", name], check=True)
    return f"Opened {name}"
```

Add `risky=True, describe=lambda a: "..."` for anything that changes or sends something.
