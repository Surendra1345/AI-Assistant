"""py2app entry point: packaged as Jarvis.app so macOS attributes microphone and
Apple Events (Mail/System Events) permission prompts to 'Jarvis' instead of to
whatever terminal or editor happens to launch the script."""
from assistant.main import main

if __name__ == "__main__":
    main()
