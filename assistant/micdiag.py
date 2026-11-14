"""Microphone check.  python -m assistant.micdiag   -- speak for 5 seconds after it starts."""
import numpy as np
import sounddevice as sd

print("Input devices:")
for i, d in enumerate(sd.query_devices()):
    if d["max_input_channels"] > 0:
        print(f"  [{i}] {d['name']}{'   <- default' if i == sd.default.device[0] else ''}")
print("\nRecording 5 seconds. SPEAK NOW...")
from .voice import Voice
v = Voice()
dev = v.input_device()
print(f"\nUsing device: {sd.query_devices(dev)['name'] if dev is not None else 'system default'}")
audio = sd.rec(int(5 * 16000), samplerate=16000, channels=1, dtype="float32", device=dev)
sd.wait()
a = np.squeeze(audio)
peak, rms = float(np.abs(a).max()), float(np.sqrt(np.mean(a ** 2)))
print(f"peak={peak:.4f}  rms={rms:.4f}   (speech is usually peak > 0.1, rms > 0.01)")
if peak == 0.0:
    print("\nTotally silent = macOS is blocking the mic. System Settings > Privacy & Security > Microphone:"
          " turn ON Terminal (or VS Code if you run it there), then quit and reopen it.")
else:
    if peak < 0.05:
        print("\nQuiet signal (the assistant boosts this automatically). For better accuracy, raise"
              " System Settings > Sound > Input > Input volume, and speak closer to the Mac.")
    print("\nTranscribing...")
    print("Heard:", repr(v.transcribe(a)))
