"""Settings. Override any of these in a .env file in the project folder or as environment variables."""
import os
from pathlib import Path


def _load_dotenv():
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if candidate.is_file():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    v = v.split(" #", 1)[0].strip() if not v.strip().startswith("#") else ""  # drop inline comments
                    os.environ.setdefault(k.strip(), v.strip('"').strip("'"))
            break


_load_dotenv()

# Where the assistant keeps its data (database, notes, workspace for code it runs)
HOME = Path(os.environ.get("ASSISTANT_HOME", str(Path.home() / "Assistant"))).expanduser()
NOTES_DIR = HOME / "notes"
WORKSPACE = HOME / "workspace"
PLANS_DIR = HOME / "plans"

# Where "mail me ..." goes (your own address)
USER_EMAIL = os.environ.get("USER_EMAIL", "")

# Brain (cloud). Only the TEXT of your requests and tool results is sent. Audio never leaves the Mac.
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-sonnet-5-5")
MAX_STEPS = int(os.environ.get("ASSISTANT_MAX_STEPS", "14"))

# Groq (cloud, OpenAI-compatible, free tier). Works as main brain when you have no Anthropic key.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_REASONING = os.environ.get("GROQ_REASONING", "low")  # gpt-oss thinking effort: low = much faster replies
# When the main Groq model hits its rate limit (free tier: 8000 tokens/min per model), try these next; each has its own limit
GROQ_FALLBACK_MODELS = [m.strip() for m in os.environ.get("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b").split(",") if m.strip()]
GROQ_URL = os.environ.get("GROQ_URL", "https://api.groq.com/openai/v1")
# Order of brains to try; each is used only if configured. Ollama is local and runs the same tools; tools that change things still ask for approval.
BRAIN_ORDER = [b.strip() for b in os.environ.get("BRAIN_ORDER", "claude,groq,ollama").split(",") if b.strip()]

# Local brain (offline, free, private). Needs Ollama: https://ollama.com. Use a tool-capable model (llama3.2:3b, qwen2.5:7b, llama3.1:8b).
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

# Voice
WAKE_MODE = os.environ.get("WAKE_MODE", "wakeword")  # "wakeword" (tiny model), "whisper" (accent-tolerant, uses more CPU) or "enter" (press Enter)
WAKE_WORD = os.environ.get("WAKE_WORD", "hey_jarvis")
WAKE_DEBUG = os.environ.get("WAKE_DEBUG", "") == "1"  # print everything heard while waiting for the wake word
WAKE_THRESHOLD = float(os.environ.get("WAKE_THRESHOLD", "0.3"))
# Microphone: "auto" prefers the MacBook's built-in mic (Bluetooth earbuds give quiet, low-quality input).
# Or set part of a device name (e.g. "MacBook") or a device number.
INPUT_DEVICE = os.environ.get("INPUT_DEVICE", "auto")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")  # "small.en" is more accurate but slower
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "en") or None
# Speech output: "piper" = natural neural voice (offline, downloaded to ~/Assistant/voices), "say" = macOS voice
TTS_ENGINE = os.environ.get("TTS_ENGINE", "piper")
PIPER_MODEL = os.environ.get("PIPER_MODEL", str(HOME / "voices" / "en_US-ryan-medium.onnx"))
BARGE_IN = os.environ.get("BARGE_IN", "auto")             # talk over it to interrupt: auto = only with headphones (speakers make it hear itself), 1 = always, 0 = never
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto = Apple GPU (mps) if it works, else cpu
# ElevenLabs voice (cloud, natural). Needs a key from elevenlabs.io in .env. Falls back to the macOS voice on any problem.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "9375G6zswFk7v9bKTVQF")   # "Vikram", Indian English
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_flash_v2_5")            # fast, cheap (half price per character)
ELEVENLABS_MONTHLY_CHARS = int(os.environ.get("ELEVENLABS_MONTHLY_CHARS", "9000"))    # stop using it past this (free plan = 10,000)
TTS_RATE = int(os.environ.get("TTS_RATE", "170"))                 # macOS voice speed, words per minute
FOLLOWUP_SECONDS = int(os.environ.get("FOLLOWUP_SECONDS", "-1"))   # keep the conversation open: accept requests without the wake word for N seconds after it speaks; -1 = auto (20 on speakers, 30 with headphones), 0 = always need the wake word
TTS_VOICE = os.environ.get("TTS_VOICE", "Samantha")

# Background tasks. Keep low on an 8 GB Air.
MAX_BG_WORKERS = int(os.environ.get("MAX_BG_WORKERS", "2"))

# Tools that run WITHOUT asking you first (comma separated). Empty = always ask for risky actions.
AUTO_APPROVE = {t.strip() for t in os.environ.get("AUTO_APPROVE_TOOLS", "").split(",") if t.strip()}

# Credential/bank/browser-data blocking lives in guard.py

# Proactive heads-ups (spoken + notification)
PROACTIVE = os.environ.get("PROACTIVE", "1") == "1"
REMIND_LEAD_MIN = int(os.environ.get("REMIND_LEAD_MIN", "10"))   # warn this many minutes before a reminder is due
BATTERY_WARN = int(os.environ.get("BATTERY_WARN", "20"))         # warn at this % (and again at 10% and 5%)

# Personality ("Jarvis mode")
ASSISTANT_NAME = os.environ.get("ASSISTANT_NAME", "Jarvis")
USER_TITLE = os.environ.get("USER_TITLE", "")        # how it addresses you, e.g. "sir" or your first name; empty = rarely uses one
ACK_SPOKEN = os.environ.get("ACK_SPOKEN", "1") == "1"  # say a short "On it" before slow work (searching, markets, code)

# How long you can talk. A request ends after PAUSE_SECONDS of silence or MAX_REQUEST_SECONDS in total.
MAX_REQUEST_SECONDS = float(os.environ.get("MAX_REQUEST_SECONDS", "30"))
PAUSE_SECONDS = float(os.environ.get("PAUSE_SECONDS", "1.6"))    # raise to 2+ if it still cuts you off mid-thought

SHOW_VISUALIZER = os.environ.get("SHOW_VISUALIZER", "1") == "1"  # crystal-ring page (HTML/CSS/JS) that pulses with voice
VISUALIZER_PORT = int(os.environ.get("VISUALIZER_PORT", "8765"))

# Off by default: turning this on binds the web server to every network interface (not just this Mac),
# so your phone can reach http://<this-Mac's-LAN-IP>:8765/chat on the same Wi-Fi and talk to the same
# assistant, same conversation, same tools. No login, no encryption - fine on a home network you trust,
# not something to port-forward onto the internet.
REMOTE_ACCESS = os.environ.get("REMOTE_ACCESS", "0") == "1"
