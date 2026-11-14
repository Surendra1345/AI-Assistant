"""Thin wrappers around macOS features (AppleScript, notifications, speech). Degrades to prints elsewhere."""
import subprocess
import sys

IS_MAC = sys.platform == "darwin"


def osascript(script: str, *args: str, timeout: int = 30) -> str:
    """Run AppleScript. Arguments are passed via argv, never string-built, so text can't inject script."""
    if not IS_MAC:
        raise RuntimeError("AppleScript is only available on macOS.")
    r = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "osascript failed")
    return r.stdout.strip()


def notification(title: str, message: str) -> None:
    if not IS_MAC:
        print(f"[notification] {title}: {message}")
        return
    try:
        osascript(
            "on run argv\n display notification (item 2 of argv) with title (item 1 of argv)\nend run",
            title, message[:200],
        )
    except Exception:
        pass


def say(text: str, voice: str = "Samantha") -> None:
    if not IS_MAC:
        print(f"[say] {text}")
        return
    subprocess.run(["say", "-v", voice, text])
