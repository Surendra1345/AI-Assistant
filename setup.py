"""Packages the assistant as Jarvis.app so macOS treats it as its own app for
permission purposes (microphone, Automation/Apple Events for Mail and System Events)
instead of attributing those prompts to whatever terminal or IDE launched the script -
the same way Siri or any other installed app owns its own permission entries.

Build (on macOS, inside your activated venv):
    python setup.py py2app -A

The -A ("alias mode") build is intentionally lightweight: instead of freezing and
copying every dependency (numpy, faster-whisper/ctranslate2, sounddevice/PortAudio,
onnxruntime, piper-tts - all native-heavy and easy to break in a full freeze), it
builds a small real .app bundle whose bundled executable runs your code in-process
but loads your dependencies from this project's own existing venv. That's exactly why
the real macOS identity trick still works (the process touching the microphone really
is Jarvis.app's own executable) without the fragility of fully bundling heavy ML
dependencies. The trade-off: this venv and project folder must stay where they are -
alias mode is for running on this machine, not for handing the .app to someone else.
Only pursue a full/standalone build later if you specifically need a copy you can move
or give away; alias mode is enough to fix the permission-attribution problem.

Run the result from Finder (double-click dist/Jarvis.app) or:
    open dist/Jarvis.app
First run will prompt for microphone and Automation access under the name 'Jarvis'.
"""
from setuptools import setup

APP = ["jarvis_launcher.py"]
DATA_FILES = [("assistant/webui", [
    "assistant/webui/index.html",
    "assistant/webui/style.css",
    "assistant/webui/app.js",
])]
OPTIONS = {
    "argv_emulation": False,
    "arch": "arm64",   # Apple Silicon Macs; change to "x86_64" or "universal2" if needed
    "plist": {
        "CFBundleName": "Jarvis",
        "CFBundleDisplayName": "Jarvis",
        "CFBundleIdentifier": "com.jarvis.assistant",
        "CFBundleShortVersionString": "1.0.0",
        "NSMicrophoneUsageDescription": "Jarvis needs the microphone to hear your voice commands.",
        "NSAppleEventsUsageDescription": "Jarvis uses Mail and System Events to check mail and control your Mac on your behalf.",
        "LSUIElement": False,   # set True later if you'd rather it not show a Dock icon
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
