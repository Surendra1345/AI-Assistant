"""Entry point.  python -m assistant          (voice)
                python -m assistant --text   (type instead of talk; good for testing)"""
import argparse
import re
import sys
import time

from datetime import datetime

from . import config, macos, router, store, tools
from .brain import Agent
from .safety import Approvals
from .tasks import ProactiveMonitor, ReminderScheduler, TaskManager


def build(voice=None):
    store.query("SELECT 1")  # creates the database
    client = None
    if config.API_KEY:
        import anthropic
        client = anthropic.Anthropic(api_key=config.API_KEY)
    else:
        if config.GROQ_API_KEY:
            print(f"No ANTHROPIC_API_KEY: using Groq ({config.GROQ_MODEL}) as the brain.")
        else:
            print("No ANTHROPIC_API_KEY or GROQ_API_KEY set: using local Ollama as the brain.")

    def notify(title: str, message: str):
        macos.notification(title, message)
        if voice:
            voice.speak(f"{title}. {message}")
        else:
            print(f"\n[{title}] {message}")

    approvals = Approvals(notify)
    tools.SERVICES.approvals = approvals
    tools.SERVICES.tasks = TaskManager(lambda tid, cancel: Agent(client, tid, cancel), notify)
    ReminderScheduler(notify).start()
    if config.PROACTIVE:
        ProactiveMonitor(notify).start()
    return Agent(client), approvals


def text_confirm(description: str) -> bool:
    return input(f"\n  APPROVE? {description}\n  [y/N] ").strip().lower() in ("y", "yes")


STOP_WORDS = re.compile(r"^\W*(stop|quiet|enough|cancel|never ?mind|okay|ok|shh+|wait)\W*$", re.I)
QUICK_APPROVAL = re.compile(r"^\W*(approve|deny)\s+#?(\d+)\W*$", re.I)


def handle(agent: Agent, approvals: Approvals, text: str) -> str:
    m = QUICK_APPROVAL.match(text)  # fast path so approvals never wait on the model
    if m:
        ok = approvals.resolve(int(m.group(2)), m.group(1).lower() == "approve")
        return "Done." if ok else "There's no pending approval with that number."
    if STOP_WORDS.match(text):  # "stop", "never mind"...: just stay quiet
        return ""
    fast = router.route(text)  # simple commands skip the model entirely
    if fast is not None:
        return fast
    return agent.run(text)


def greet(voice=None):
    """Proactive: once per day (and whenever something finished while away), say what needs attention."""
    today = datetime.now().strftime("%Y-%m-%d")
    last = store.query("SELECT value FROM meta WHERE key='last_greet'")
    first_today = not last or last[0]["value"] != today
    if not first_today and not store.query(
            "SELECT 1 FROM tasks WHERE status IN ('done','failed') AND id NOT IN (SELECT task_id FROM reported)"):
        return  # already greeted today and nothing new finished
    brief = tools.briefing_text()
    store.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('last_greet', ?)", (today,))
    hour = datetime.now().hour
    hello = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    msg = f"{hello}. " + (brief + "." if brief else "Nothing urgent today.")
    voice.speak(msg) if voice else print(f"Assistant: {msg}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type instead of speaking")
    args = ap.parse_args()

    voice = None
    if not args.text:
        from .voice import Voice
        voice = Voice()
    agent, approvals = build(voice)
    approvals.interactive_confirm = voice.confirm if voice else text_confirm

    if voice and config.TTS_ENGINE == "elevenlabs":
        print("Voice: ElevenLabs (Vikram)." if config.ELEVENLABS_API_KEY
              else f"Voice: {config.TTS_VOICE} (add ELEVENLABS_API_KEY to .env to use the Vikram voice).")
    if voice:
        if voice.using_speakers():
            print("Using the laptop speakers: say 'hey happy' before each request, and press Enter to stop it talking. "
                  "(With earbuds you can talk over it and chat without the wake word.)")
        else:
            print("Headphones detected: you can talk over it, and keep chatting without the wake word.")
    print("Ready. Say or type 'quit' to exit.")
    greet(voice)
    failures = 0
    try:
        while True:
            try:
                text = voice.listen() if voice else input("\nYou: ").strip()
                if not text:
                    failures = 0
                    continue
                if voice:
                    print(f"You: {text}")
                if re.fullmatch(r"\W*(quit|exit|goodbye|stop listening)\W*", text, re.I):
                    break
                reply = handle(agent, approvals, text)
                failures = 0
                if not reply:
                    continue
                if voice:
                    voice.speak(reply)
                else:
                    print(f"Assistant: {reply}")
            except (KeyboardInterrupt, EOFError):
                raise
            except Exception as e:
                # Never die: after the laptop sleeps/wakes, the mic or audio device can briefly be unavailable.
                failures += 1
                delay = min(2 * failures, 15)
                print(f"(hiccup: {type(e).__name__}: {str(e)[:120]}. Retrying in {delay}s...)")
                time.sleep(delay)
    except (KeyboardInterrupt, EOFError):
        pass
    print("Bye.")
    sys.exit(0)


if __name__ == "__main__":
    main()
