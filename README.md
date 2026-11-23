# Mac Assistant ("Jarvis")

A private, voice-driven personal assistant for your Mac, in the spirit of Tony Stark's JARVIS: calm, capable, briefly witty, and it acts on your behalf with 46 tools — mail, files, notes, reminders, research, markets, code, apps, music.

**Local on your Mac:** wake word, speech-to-text (Whisper), speech output (Piper / ElevenLabs / macOS `say`), files, notes, reminders.
**Cloud:** only the *text* of your requests and tool results goes to Claude (or Groq) for planning. Your audio never leaves the Mac.
**Offline fallback:** a local Ollama model when there's no internet or no API key — plain chat, no tools.

## Install

1. `brew install python@3.12`, and optionally Ollama for offline fallback: `ollama pull llama3.2:3b`
2. In this folder: `bash setup.sh`
3. Open `.env` and set `ANTHROPIC_API_KEY` and/or `GROQ_API_KEY` (Groq has a free tier; without either, it falls back to Ollama only).
4. Test by typing first: `source .venv/bin/activate && python -m assistant --text`
5. Then voice: `python -m assistant`. Allow Microphone access when macOS asks, and Mail/Automation access the first time it checks email.

On startup it runs a health check (microphone, API key, Mail permission, Whisper model, Ollama) and tells you exactly what to fix if something's missing, instead of failing silently later.

### Using Gmail

Mail tools go through the Mail app, and check every account you've added there — so Gmail works too, once it's set up as a Mail.app account:

1. In Gmail: Settings → See all settings → Forwarding and POP/IMAP → enable IMAP.
2. On your Mac: System Settings → Internet Accounts → add your Google account (or add it directly inside Mail.app).
3. That's it — `check_mail` and `search_mail` now show messages from every account, Apple's own and Gmail, merged and sorted by date, and label which account each one came from.

## What you can say

| Say | What happens |
|---|---|
| "Research how solid-state batteries work and summarize it" | Several searches, reads pages, saves a note, tells you the summary |
| "Check my mail from the last 10 days for job replies" | Searches across that range, reads the relevant ones, can save a dated note |
| "In the background, compare the top 3 note-taking apps" | Starts task #N, keeps listening, notifies and speaks when done |
| "Organize my Downloads folder" | Shows a plan (nothing moves), asks approval, moves files, can undo |
| "Draft an email to Priya about Friday's meeting" | Opens a draft in Mail for you to review |
| "Send an email to ... saying ..." | Asks "yes or no?" first |
| "Remind me to call the bank tomorrow at 10" | Saved, then spoken + notification at that time |
| "What's the latest in AI today?" | Searches fresh news (last day), reads the best article, summarises with dates |
| "What's 12% of 48,000?" / "50000 at 8% for 10 years" | Exact calculator, no guessing |
| "Which company is going up today?" | Scans large companies, lists top risers and fallers |
| "If I put 50,000 in Tesla, would I earn?" | Real price history: what it would be worth, biggest drop, risk. Data only, never a guarantee |
| "Play some music" / "pause" / "skip" | Controls the Music app |
| "What's on my list?" / "Mark 3 done" | To-do tracker |
| "Write a script that renames my photos by date and run it" | Writes code, shows it, asks approval, runs it, reports output |
| "How's task 2 going?" / "Cancel task 2" | Status / cancel |
| "approve 3" / "deny 3" | Answers an approval a background task is waiting on |

Mid-conversation, you don't need to repeat the wake word for follow-ups ("and bread", "make it 4pm instead"). Pressing Enter also skips the wake word for one request.

## Reliability features

- **Startup health check** (`assistant/health.py`): checks the microphone, API keys, Mail permission, Whisper model, and Ollama before the voice loop starts, with actionable fixes for anything missing.
- **Error logging** (`assistant/logging_config.py`): every request, tool call, and failure is logged to `~/Assistant/assistant.log` for after-the-fact diagnosis. Console only shows warnings/errors; the file has the full detail.
- **Confidence-aware clarification**: Whisper's own confidence score comes along with every transcript. On merely imperfect but understandable speech, nothing changes. On genuinely very low confidence, the model is told to ask a short clarifying question with its best guess — the same judgment it already uses for garbled requests — rather than a hard-coded "did you mean that?" interrupting normal conversation.
- **Privacy guard** (`assistant/guard.py`): blocks access to `~/.ssh`, `~/.aws`, Keychains, browser data; detects and redacts passwords, card numbers, API keys and similar secrets in anything read or returned.

## Visualizer (optional)

A small browser page shows a glowing crystal-sphere that reacts live to your voice: gentle idle breathing, ripples with your mic level while listening, pulses with its own speech while talking. It's plain HTML/CSS/Canvas (`assistant/webui/`), served locally by `assistant/webserver.py` and opened automatically in your default browser. Disable with `SHOW_VISUALIZER=0` in `.env`.

## Using it from your phone (optional)

Set `REMOTE_ACCESS=1` in `.env` and the same assistant - same conversation, same tools, same approval prompts - becomes reachable from any phone on the same Wi-Fi, via a simple text chat page at `http://<this-Mac's-LAN-IP>:8765/chat` (the exact address is printed when the assistant starts). Works from any phone's browser, Android included.

- Voice input on the page uses the *browser's own* speech recognition (not routed through the Mac's Whisper) - note this needs a "secure context" (https, or localhost), so it will likely be unavailable over a plain `http://<lan-ip>` page; text input always works regardless.
- A reply to a phone message is sent back to the phone and is **not** also spoken aloud on the Mac.
- There's no login and no encryption - this is meant for your own home Wi-Fi, not for exposing to the internet (don't port-forward this).
- Off by default. When on, the web server binds to every network interface instead of just this machine, which is the only behavior change - everything else (voice, visualizer) works exactly as before.

## Running it as its own app (so macOS asks permission as "Jarvis", not your terminal/editor)

By default, macOS attributes microphone and Automation permission prompts to whatever process launched Python — your terminal or IDE. `setup.py` packages the assistant as `Jarvis.app` so it owns its own permission identity instead, the same way any installed app does:

```bash
pip install py2app   # one-time
python setup.py py2app -A
./dist/Jarvis.app/Contents/MacOS/Jarvis   # run it this way (not double-click) to keep seeing its output
```

This is an "alias mode" build: lightweight and tied to this project folder staying where it is, rather than a bundle you could copy elsewhere. See the comment at the top of `setup.py` for details and trade-offs.

## Safety model

- **Risky actions always ask first**: sending email, running code, moving files. Foreground: spoken/typed yes-no. Background: a notification, then "approve N" / "deny N".
- File moves never delete and can be undone. Drafting is preferred over sending.
- It can't read `~/.ssh`, `~/.aws`, `~/.gnupg`, or Keychains, and only writes inside `~/Assistant/workspace`.
- Web pages and emails are treated as untrusted data; the model is told never to follow instructions found in them, and the approval prompt is the backstop.
- Honest limit: approved code runs as *you* (it isn't sandboxed). Read what it shows you before saying yes.
- Set `AUTO_APPROVE_TOOLS` in `.env` only for tools you fully trust.

## Where things live

`~/Assistant/` holds `notes/`, `workspace/` (code it writes), `plans/`, `assistant.db` (to-dos, memory, task history), and `assistant.log` (diagnostics).

## Key settings (`.env`)

| Setting | Default | What it does |
|---|---|---|
| `ASSISTANT_NAME` | `Jarvis` | What it calls itself and responds to in speech |
| `WAKE_WORD` | `hey_jarvis` | The wake phrase |
| `WAKE_MODE` | `wakeword` | `wakeword` (tiny model), `whisper` (accent-tolerant), or `enter` (press Enter) |
| `BRAIN_ORDER` | `claude,groq,ollama` | Fallback order if one is rate-limited or unavailable |
| `SHOW_VISUALIZER` | `1` | Crystal-sphere browser visualizer on/off |
| `REMOTE_ACCESS` | `0` | Reach the assistant from your phone over Wi-Fi at `/chat` - see "Using it from your phone" above |
| `MAX_REQUEST_SECONDS` | `30` | How long a single spoken request can run before it's cut off |
| `AUTO_APPROVE_TOOLS` | empty | Comma-separated tools that skip the yes/no prompt |
| `TTS_ENGINE` | `piper` | `piper` (offline), `say` (macOS built-in voices), or `elevenlabs` (most natural, needs an API key) |
| `TTS_VOICE` | `Samantha` | For `TTS_ENGINE=say` - try `Rishi` for Indian English (download it in System Settings > Accessibility > Spoken Content first) |
| `ELEVENLABS_API_KEY` | empty | Enables `TTS_ENGINE=elevenlabs`; defaults to "Vikram," an Indian English voice |

## 8 GB tips

- Whisper `base.en` uses about 0.5 GB; `small.en` is more accurate but slower.
- Close heavy apps (many Chrome tabs) for faster speech recognition.
- Cost: each request is a few small API calls (usually cents or less, and free on Groq's tier). Long research tasks cost more.

## Known limits

- No calendar or Messages integration yet; the tool pattern in `assistant/tools.py` makes adding them a small function each.
- Reminders live in this assistant's own list, not the Apple Reminders app.
- The `Jarvis.app` packaging (above) is alias-mode: convenient for permission branding on this one machine, not a distributable/movable app.

## Adding a tool

In `assistant/tools.py`:

```python
@tool("open_app", "Open a macOS app by name.", {"name": {"type": "string"}}, ["name"])
def open_app(name: str) -> str:
    subprocess.run(["open", "-a", name], check=True)
    return f"Opened {name}"
```

Add `risky=True, describe=lambda a: "..."` for anything that changes or sends something.
