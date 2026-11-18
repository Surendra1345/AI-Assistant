"""Startup diagnostics: check mic, API keys, permissions, models."""
import subprocess
import sys
from pathlib import Path

from . import config, macos

class HealthCheck:
    def __init__(self):
        self.ok = True
        self.issues = []

    def check_all(self) -> bool:
        """Run all checks. Return True if all passed."""
        self._check_microphone()
        self._check_api_key()
        if macos.IS_MAC:
            self._check_mail_permission()
        self._check_whisper_model()
        self._check_ollama() if config.BRAIN_ORDER and "ollama" in config.BRAIN_ORDER else None
        return self.ok

    def report(self):
        """Print the status report."""
        if not self.issues:
            print("✓ Health check passed. Ready to go.")
            return
        print("⚠ Startup issues found:\n")
        for issue in self.issues:
            print(f"  {issue}")
        if self.ok:
            print("\n(Continuing anyway.)")
        else:
            print("\n(Exiting.)")
            sys.exit(1)

    def _check_microphone(self):
        """Microphone permission and device availability."""
        try:
            import sounddevice as sd
            sd._terminate()
            sd._initialize()
            devs = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
            if not devs:
                self.issues.append("❌ Microphone: no input devices found")
                self.ok = False
                return
            print(f"✓ Microphone: {devs[0][1]} ready")
        except Exception as e:
            if "permission" in str(e).lower() or "access" in str(e).lower():
                self.issues.append(
                    "❌ Microphone: permission denied. "
                    "Open System Settings > Privacy & Security > Microphone and turn on Terminal."
                )
                self.ok = False
            else:
                self.issues.append(f"⚠ Microphone: {e}")

    def _check_api_key(self):
        """API keys: Anthropic or Groq."""
        if config.API_KEY:
            print("✓ Anthropic API key: set")
        elif config.GROQ_API_KEY:
            print("✓ Groq API key: set (free tier)")
        else:
            self.issues.append("⚠ No ANTHROPIC_API_KEY or GROQ_API_KEY. Using local Ollama only.")

    def _check_mail_permission(self):
        """Mail automation permission."""
        try:
            macos.osascript('tell application "Mail" to return name')
            print("✓ Mail permission: OK")
        except RuntimeError as e:
            if "1743" in str(e) or "not allowed" in str(e).lower():
                self.issues.append(
                    "⚠ Mail permission: not granted yet. "
                    "Open System Settings > Privacy & Security > Automation and allow Terminal."
                )
            else:
                self.issues.append(f"⚠ Mail: {e}")

    def _check_whisper_model(self):
        """Whisper speech-to-text model availability."""
        model_path = Path(config.WHISPER_MODEL)
        if model_path.exists():
            print(f"✓ Whisper model: {model_path.name}")
            return
        try:
            from faster_whisper import WhisperModel
            print(f"✓ Whisper: will download {config.WHISPER_MODEL} on first use (~150 MB)")
        except ImportError:
            self.issues.append("❌ Whisper: faster_whisper not installed")
            self.ok = False

    def _check_ollama(self):
        """Local Ollama for offline fallback."""
        try:
            r = subprocess.run(["curl", "-s", f"{config.OLLAMA_URL}/api/tags"],
                             capture_output=True, timeout=2)
            if r.returncode == 0:
                print(f"✓ Ollama: running ({config.OLLAMA_MODEL})")
            else:
                self.issues.append(f"⚠ Ollama: not reachable at {config.OLLAMA_URL}")
        except Exception:
            self.issues.append(f"⚠ Ollama: not reachable at {config.OLLAMA_URL}")
