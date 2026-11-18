"""Entry point.  python -m assistant          (voice)
                python -m assistant --text   (type instead of talk; good for testing)"""
import argparse
import random
import re
import sys
import time

from datetime import datetime

from . import config, finance, logging_config, macos, router, store, tools  # noqa: F401 (finance registers its tools)
from .brain import Agent
from .health import HealthCheck
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
DISMISS = re.compile(r"^\W*(?:ok(?:ay)?\s+|alright\s+)?(thanks|thank you|cheers|that'?s all|that will be all|that'?ll be all|go to sleep|dismissed|"
                     r"i'?m good|nothing else|that'?s it)(?:\s+(?:so much|a lot|very much))?(?:\s+\w+)?\W*$", re.I)
# Said just before slow work starts, so the assistant never goes silent while it thinks.
ACKS = {"web_search": "Searching now.", "news_search": "Checking the latest news.", "fetch_page": "Reading that page.",
        "market_movers": "Scanning the markets.", "stock_quote": "Pulling the prices.", "investment_scenario": "Running the numbers.",
        "find_files": "Looking for it.", "read_file": "Reading it now.", "organize_plan": "Taking a look at the folder.",
        "start_background_task": "On it.", "check_mail": "Checking your mail.", "read_email": "Opening that email."}


def make_ack(voice):
    def ack(tool_name: str):
        phrase = ACKS.get(tool_name)
        if phrase and voice and config.ACK_SPOKEN:
            voice.speak(phrase, barge=False, settle=False)
    return ack


QUICK_APPROVAL = re.compile(r"^\W*(approve|deny)\s+#?(\d+)\W*$", re.I)


def handle(agent: Agent, approvals: Approvals, text: str, confidence: float = 1.0) -> str:
    m = QUICK_APPROVAL.match(text)  # fast path so approvals never wait on the model
    if m:
        ok = approvals.resolve(int(m.group(2)), m.group(1).lower() == "approve")
        return "Done." if ok else "There's no pending approval with that number."
    if STOP_WORDS.match(text):  # "stop", "never mind"...: just stay quiet
        return ""
    if DISMISS.match(text):     # "thanks", "that's all": close the conversation
        return random.choice(["Anytime.", "Of course.", "At your service.", "Standing by."])
    fast = router.route(text)  # simple commands skip the model entirely
    if fast is not None:
        return fast
    return agent.run(text, confidence)


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
    who = f", {config.USER_TITLE}" if config.USER_TITLE else ""
    msg = f"{hello}{who}. " + (brief + "." if brief else "Nothing urgent on the schedule.")
    voice.speak(msg) if voice else print(f"Assistant: {msg}")


def main():
    # Set up logging and health checks first
    logger = logging_config.setup()
    hc = HealthCheck()
    if not hc.check_all():
        hc.report()
        return
    hc.report()
    
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="type instead of speaking")
    args = ap.parse_args()

    voice = None
    if not args.text:
        from .voice import Voice
        voice = Voice()
        if config.SHOW_VISUALIZER:
            from .visualizer import Visualizer
            vis = Visualizer()
            vis.start()
            voice.visualizer = vis
    agent, approvals = build(voice)
    approvals.interactive_confirm = voice.confirm if voice else text_confirm
    agent.on_first_tool = make_ack(voice)

    if voice and config.TTS_ENGINE == "elevenlabs":
        print("Voice: ElevenLabs (Vikram)." if config.ELEVENLABS_API_KEY
              else f"Voice: {config.TTS_VOICE} (add ELEVENLABS_API_KEY to .env to use the Vikram voice).")
    if voice:
        if voice.using_speakers():
            print(f"Using the laptop speakers: say '{config.WAKE_WORD.replace('_', ' ')}' before each request, and press Enter to stop it talking. "
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
                conf = getattr(voice, "last_conf", 1.0) if voice else 1.0
                reply = handle(agent, approvals, text, conf)
                failures = 0
                if not reply:
                    continue
                if voice:
                    voice.speak(reply)
                    if DISMISS.match(text):            # conversation over: back to waiting for the wake word
                        voice.last_active, voice.follow_until = 0.0, 0.0
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
    if voice and voice.visualizer:
        voice.visualizer.stop()
    print("Bye.")
    sys.exit(0)


if __name__ == "__main__":
    main()
