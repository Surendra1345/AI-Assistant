"""Wake-word check.  python -m assistant.wakediag   -- say 'hey jarvis' a few times; Ctrl-C to stop.
Shows the live mic level and the wake-word score (it triggers when score > WAKE_THRESHOLD)."""
import numpy as np
import sounddevice as sd

from . import config
from .voice import Voice

v = Voice()
model = v._load_wake()
dev = v.input_device()
print(f"Device: {sd.query_devices(dev)['name'] if dev is not None else 'default'} | word: {config.WAKE_WORD} | "
      f"threshold: {config.WAKE_THRESHOLD}\nSay 'hey jarvis' (Ctrl-C to stop)\n")
best = 0.0
peaks = []
with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280, device=dev) as stream:
    try:
        while True:
            data, _ = stream.read(1280)
            x = np.squeeze(data)
            level = max(peaks + [int(np.abs(x).max())]) / 32768  # loudest in the last ~2.4 s
            peaks = (peaks + [int(np.abs(x).max())])[-30:]
            score = max(model.predict(v._boost(x, max(peaks))).values() or [0])
            best = max(best, score)
            bar = "#" * int(score * 40)
            print(f"\rloudest {level:5.3f}  score {score:4.2f}  best {best:4.2f} |{bar:<40}|", end="", flush=True)
    except KeyboardInterrupt:
        print(f"\n\nBest score: {best:.2f}. If it stayed under {config.WAKE_THRESHOLD}, lower WAKE_THRESHOLD in .env "
              f"(e.g. 0.3), speak louder/closer, or raise macOS input volume.")
