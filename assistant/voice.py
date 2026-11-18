"""Voice layer, all local: wake word -> record -> Whisper speech-to-text; Piper (or macOS `say`) for speech out.
You can interrupt it: start talking while it speaks and it stops and listens."""
import difflib
import logging
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor

from datetime import datetime

from . import config, guard, macos, store


class Voice:
    def __init__(self):
        self._stt = None
        self._wake = None
        self._speak_lock = threading.Lock()
        self._sd = None
        self.last_rms = 0.0
        self.last_active = 0.0   # when we last spoke/heard a command: follow-ups need no wake word
        self._piper = None
        self._piper_failed = False
        self.barged = False      # True when the user talked over the assistant
        self.barge_audio = None  # the start of what they said
        self.barge_text = None   # what they said while we were paused (already transcribed)
        self.speaking = False     # True while we are talking
        self.stop_requested = False  # Enter pressed while talking: stop at once
        self.ptt_until = 0.0     # pressing Enter = 'I'm talking to you now': no wake word needed for a few seconds
        self._ptt_thread = None
        self.last_spoken = ""    # what we last said out loud (to recognise our own voice coming back through the mic)
        self.spoke_end = 0.0
        self.speaking_text = ""  # what we are saying right now (to recognise our own voice in the mic)
        self.follow_until = 0.0  # after a question from us: accept the answer without the wake word until then
        self.last_conf = 0.0     # Whisper's confidence in the last transcript (avg log-prob)
        self.visualizer = None   # optional Visualizer: fed mic/speech levels so the crystal ring reacts

    # ---- lazy loading keeps startup fast and memory low
    def _audio(self):
        if self._sd is None:
            import sounddevice as sd
            self._sd = sd
        return self._sd

    def input_device(self):
        """Pick the mic: explicit INPUT_DEVICE, else the built-in MacBook mic, else the system default."""
        sd = self._audio()
        try:  # PortAudio caches the device list; refresh so headphones connected later are noticed
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        want = config.INPUT_DEVICE.strip()
        devs = [(i, d["name"]) for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        if want.isdigit():
            return int(want)
        if want and want.lower() != "auto":
            for i, n in devs:
                if want.lower() in n.lower():
                    return i
        for i, n in devs:
            if "macbook" in n.lower() or "built-in" in n.lower():
                return i
        return None

    def using_speakers(self) -> bool:
        """True when sound comes out of the laptop's own speakers (the mic then hears everything we say)."""
        try:
            name = str(self._audio().query_devices(kind="output")["name"]).lower()
        except Exception:
            return True
        return any(k in name for k in ("speaker", "macbook", "built-in", "imac", "display"))

    def barge_enabled(self) -> bool:
        if config.BARGE_IN in ("1", "true", "on"):
            return True
        if config.BARGE_IN in ("0", "false", "off"):
            return False
        return not self.using_speakers()                     # auto

    def followup_seconds(self) -> int:
        if config.FOLLOWUP_SECONDS >= 0:
            return config.FOLLOWUP_SECONDS
        return 20 if self.using_speakers() else 30   # a conversation stays open; "thanks" or silence closes it

    def _load_stt(self):
        if self._stt is None:
            from faster_whisper import WhisperModel
            self._stt = None
            if config.WHISPER_DEVICE in ("auto", "mps"):  # newer CTranslate2 has an (experimental) Apple GPU backend
                try:
                    self._stt = WhisperModel(config.WHISPER_MODEL, device="mps", compute_type="float16")
                    self._stt_dev = "mps"
                except Exception:
                    self._stt = None                      # older build: use the CPU (transcribe() also falls back if the GPU errors)
            if self._stt is None:
                self._stt = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
                self._stt_dev = "cpu"
        return self._stt

    def _load_wake(self):
        if self._wake is None:
            from openwakeword.model import Model
            self._wake = Model(wakeword_models=[config.WAKE_WORD], inference_framework="onnx")
        return self._wake

    # ---- listening
    @staticmethod
    def _boost(x, recent_peak: float):
        """Lift a quiet mic toward a healthy level (max 20x) with noise floor subtraction."""
        import numpy as np
        if recent_peak <= 0 or recent_peak > 8000:
            return x
        gain = min(10000 / recent_peak, 20.0)   # more conservative: 20x not 40x
        x_float = x.astype("float32") * gain
        x_float = np.clip(x_float, -32768, 32767)
        return x_float.astype("int16")

    def wait_for_wake(self):
        if config.WAKE_MODE == "enter":
            input("\n[Press Enter, then speak] ")
            return
        import numpy as np
        model = self._load_wake()
        sd = self._audio()
        print(f"Listening for '{config.WAKE_WORD.replace('_', ' ')}'...")
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16", blocksize=1280, device=self.input_device()) as stream:
            peaks, last_hint = [], 0.0
            while True:
                data, _ = stream.read(1280)
                x = np.squeeze(data)
                peaks = (peaks + [int(np.abs(x).max())])[-30:]       # ~2.4 s of history
                scores = model.predict(self._boost(x, max(peaks)))
                top = max(scores.values()) if scores else 0.0
                if 0.12 < top <= config.WAKE_THRESHOLD and time.time() - last_hint > 3:
                    last_hint = time.time()  # near miss: tell the user so they can tune WAKE_THRESHOLD
                    print(f"  (almost: wake score {top:.2f}, needs {config.WAKE_THRESHOLD})")
                if top > config.WAKE_THRESHOLD:
                    if hasattr(model, "reset"):
                        model.reset()
                    return

    def record(self, max_seconds: float = None, silence_seconds: float = None, first_word_timeout: float = 6,
               min_threshold: float = 0.003):
        """Record until you stop talking. Returns float32 mono audio at 16 kHz (empty if nothing was said).
        Keeps a 0.5 s pre-roll so the first syllable isn't clipped; max_seconds counts from when you start talking."""
        import numpy as np
        from collections import deque
        max_seconds = config.MAX_REQUEST_SECONDS if max_seconds is None else max_seconds
        silence_seconds = config.PAUSE_SECONDS if silence_seconds is None else silence_seconds
        sd = self._audio()
        block = 1600  # 100 ms
        self.last_rms = 0.0
        preroll, chunks, noise = deque(maxlen=5), [], []
        started, quiet, t0, t_start = False, 0.0, time.time(), 0.0
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=block, device=self.input_device()) as stream:
            while True:
                data, _ = stream.read(block)
                data = np.squeeze(data).copy()
                rms = float(np.sqrt(np.mean(data ** 2)))
                self.last_rms = max(self.last_rms, rms)
                if self.visualizer is not None:
                    self.visualizer.set_level(min(1.0, rms * 12))   # mic RMS is tiny; scale up for the ring
                if len(noise) < 3:                       # first 0.3 s: measure room noise (audio is still kept)
                    noise.append(rms)
                # quietest block = true room noise; capped so normal speech is always detectable
                threshold = min(max(0.03, min_threshold), max(min_threshold, 4 * min(noise)))
                if not started:
                    preroll.append(data)
                    if len(noise) >= 3 and rms > threshold:
                        started, t_start = True, time.time()
                        chunks = list(preroll)
                    elif time.time() - t0 > first_word_timeout:
                        return np.zeros(0, dtype="float32")
                    continue
                chunks.append(data)
                quiet = 0.0 if rms > threshold else quiet + 0.1
                if quiet >= silence_seconds or time.time() - t_start > max_seconds:
                    break
        return np.concatenate(chunks)

    @staticmethod
    def _reduce_noise(audio):
        """Reduce background noise using spectral subtraction on quiet frames."""
        import numpy as np

        # Identify noise profile from quietest 500ms
        frame_len = 512
        hop = 160
        frames_rms = [np.sqrt(np.mean(audio[i:i+frame_len]**2)) for i in range(0, min(len(audio), 8000), hop)]
        noise_level = min(frames_rms) if frames_rms else 0.01
        threshold = noise_level * 2.5

        # Apply noise gate: suppress frames below threshold
        result = np.zeros_like(audio)
        for i in range(0, len(audio) - frame_len, hop):
            frame = audio[i:i+frame_len]
            rms = np.sqrt(np.mean(frame**2))
            if rms > threshold:
                result[i:i+frame_len] = frame
            else:
                # Smooth fade-out for quiet frames to avoid clicks
                result[i:i+frame_len] = frame * (rms / threshold)

        # Handle last frame
        if len(audio) > len(result):
            result = np.concatenate([result, audio[len(result):]])

        return result.astype("float32")

    def transcribe(self, audio, prompt=None) -> tuple[str, float]:
        """Transcribe audio. Return (text, confidence) where confidence is -9 (silent) to 1 (perfect)."""
        if len(audio) < 1600:
            return "", -9.0
        import numpy as np

        peak = float(np.abs(audio).max())
        if 0 < peak < 0.5:  # quiet mic: boost (up to 8x) so Whisper gets a healthy signal
            audio = np.clip(audio * min(0.7 / peak, 8.0), -1.0, 1.0).astype("float32")
        kw = dict(language=config.WHISPER_LANGUAGE, vad_filter=True, beam_size=1, initial_prompt=prompt,
                  condition_on_previous_text=False)
        try:
            segments = list(self._load_stt().transcribe(audio, **kw)[0])
        except Exception:
            if getattr(self, "_stt_dev", "cpu") != "mps":
                raise
            from faster_whisper import WhisperModel  # GPU hiccup: fall back to cpu for good
            self._stt, self._stt_dev = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8"), "cpu"
            segments = list(self._stt.transcribe(audio, **kw)[0])
        # drop Whisper's classic hallucinations on silence/noise ("Thank you.", "Productivity. Productivity. ...")
        good = [s for s in segments if s.no_speech_prob < 0.7 and s.avg_logprob > -1.4 and s.compression_ratio < 2.4]
        self.last_conf = sum(s.avg_logprob for s in good) / len(good) if good else -9.0
        text = " ".join(s.text.strip() for s in good).strip()
        return text, self.last_conf

    _FILLER = re.compile(r"^\W*(oh|ah|uh|um|hmm+|wow|huh|whoa|ugh|oops|god)\b", re.I)   # remarks, not requests ("Oh, my God.")
    _JUNK = re.compile(r"^\W*(thank you|thanks|thanks for watching|you|bye|okay|ok|yeah|yes|no|hmm+|uh+|um+|so|the|oh|ah|hi|hello)\W*$", re.I)

    @staticmethod
    def _echo_of(text: str, said: str, min_ratio: float = 0.7, min_words: int = 1) -> bool:
        """True if (nearly) every word in `text` also appears in `said`. Prefix-tolerant, because the mic often catches
        only the start of one of our words ("after" from "afternoon")."""
        mine = re.findall(r"[a-z0-9']+", text.lower())
        theirs = set(re.findall(r"[a-z0-9']+", said.lower()))
        if len(mine) < min_words or not theirs:
            return False
        hit = sum(1 for w in mine if w in theirs or (len(w) >= 3 and any(t.startswith(w) or w.startswith(t) for t in theirs if len(t) >= 3)))
        return hit / len(mine) >= min_ratio

    def _is_echo(self, text: str) -> bool:
        """True if `text` is just our own last reply coming back through the speakers into the mic."""
        age = time.time() - self.spoke_end
        if age > 30 or not self.last_spoken:
            return False
        if age < 6:                                       # right after we spoke, even one or two echoed words count
            return self._echo_of(text, self.last_spoken)
        return self._echo_of(text, self.last_spoken, 0.6, 3)

    def _plausible_followup(self, text: str) -> bool:
        """Mid-conversation we accept speech without a wake word, so be strict: clear, real, more than a filler word."""
        words = text.split()
        return (len(words) >= 2 and self.last_conf > -0.8 and not self._JUNK.match(text)
                and not (len(words) <= 4 and self._FILLER.match(text)) and not self._is_echo(text))

    @staticmethod
    def after_wake(text: str):
        """If `text` contains the wake word (fuzzy, so 'jarvas'/'jervis' still match) return what follows it, else None."""
        wake = config.WAKE_WORD.split("_")[-1].lower()
        words = re.findall(r"[a-z0-9']+", text.lower())
        for i, w in enumerate(words):
            if difflib.SequenceMatcher(None, w, wake).ratio() >= 0.6:
                return " ".join(words[i + 1:])
        return None

    def _start_ptt(self):
        """Press Enter in the terminal any time to skip the wake word (handy when 'hey happy' isn't being picked up)."""
        if self._ptt_thread is not None or not sys.stdin or not sys.stdin.isatty():
            return

        def loop():
            import logging
            log = logging.getLogger("voice")
            while True:
                try:
                    sys.stdin.readline()
                except Exception:
                    return
                self.ptt_until = time.time() + 12
                if self.speaking:
                    self.stop_requested = True               # Enter while it talks = stop talking
                print("  (listening: just talk)")
        self._ptt_thread = threading.Thread(target=loop, daemon=True)
        self._ptt_thread.start()

    def _listen_whisper(self) -> str:
        """Wake word via Whisper: far more tolerant of accents than the tiny wake-word model."""
        self._start_ptt()
        print(f"Listening for '{config.WAKE_WORD.replace('_', ' ')}' (say it, then your request). Or press Enter, then just talk.")
        if self.visualizer is not None:
            self.visualizer.set_mode("listening")
        while True:
            wake = config.WAKE_WORD.split("_")[-1].capitalize()
            audio = self.record(max_seconds=config.MAX_REQUEST_SECONDS, silence_seconds=config.PAUSE_SECONDS, first_word_timeout=10, min_threshold=0.006)
            text, conf = self.transcribe(audio, prompt=f"Hey {wake}. {wake}, what time is it?")  # biases Whisper toward the wake word
            log = logging.getLogger("voice")
            log.debug(f"heard {repr(text)} (confidence {conf:.2f})")
            if config.WAKE_DEBUG and (len(audio) or self.last_rms > 0.003):
                print(f"  [loudest {self.last_rms:.3f}, {len(audio)/16000:.1f}s recorded, recognised: {text!r}]")
            if not text or self._is_echo(text):
                continue
            if time.time() < self.ptt_until:              # Enter was pressed: take whatever was said
                self.ptt_until = 0.0
                rest = self.after_wake(text)
                return rest if rest else text
            if time.time() < self.follow_until or time.time() - self.last_active < self.followup_seconds():   # mid-conversation: no wake word needed
                if self._plausible_followup(text):
                    self.last_active = time.time()
                    return text
                if self.after_wake(text) is None:
                    continue
            rest = self.after_wake(text)
            if rest is None:
                if config.WAKE_DEBUG:
                    print(f"  (heard: {text!r} - no wake word)")
                continue
            if rest.strip():
                return rest                      # "hey jarvis what time is it" in one go
            print("(heard wake word, listening...)")
            subprocess.run(["afplay", "/System/Library/Sounds/Tink.aiff"]) if macos.IS_MAC else None
            time.sleep(0.25)
            return self.transcribe(self.record())

    def _listen_after_barge(self) -> str:
        """The user talked over the assistant: keep recording what they were saying (no wake word needed)."""
        import numpy as np
        self.barged = False
        if self.barge_text is not None:                  # we already listened while paused
            text, self.barge_text = self.barge_text, None
            print("(interrupted)")
            return text
        print("(interrupted, listening...)")
        rest = self.record(first_word_timeout=3, min_threshold=0.006)
        audio = np.concatenate([self.barge_audio, rest]) if self.barge_audio is not None else rest
        self.barge_audio = None
        text, conf = self.transcribe(audio)
        return "" if self._is_echo(text) else text

    def listen(self) -> str:
        if self.barged:
            return self._listen_after_barge()
        if config.WAKE_MODE != "whisper" and time.time() < self.follow_until:   # we just asked a question: hear the answer
            text = self.transcribe(self.record(first_word_timeout=6, min_threshold=0.006))
            if text and self._plausible_followup(text):
                self.last_active = time.time()
                return text
            self.follow_until = 0.0
        if config.WAKE_MODE == "whisper":
            return self._listen_whisper()
        self.wait_for_wake()
        print("(heard wake word, listening...)")
        subprocess.run(["afplay", "/System/Library/Sounds/Tink.aiff"]) if macos.IS_MAC else None
        time.sleep(0.25)  # let the chime fade so the mic doesn't hear it
        audio = self.record()
        text, conf = self.transcribe(audio)
        if not text:
            print(f"(didn't catch anything; loudest sound heard {self.last_rms:.4f}. Speak right after the Tink. "
                  f"If this stays near 0, run: python -m assistant.micdiag)")
        return text

    def listen_now(self) -> str:
        """Record immediately, no wake word (used for yes/no approvals)."""
        return self.transcribe(self.record(max_seconds=8, first_word_timeout=8), prompt="Yes. No. Yes, approve. No, deny.")[0]

    # ---- speaking
    def _piper_voice(self):
        if self._piper is None and not self._piper_failed:
            try:
                from piper import PiperVoice
                self._piper = PiperVoice.load(config.PIPER_MODEL)
            except Exception:
                self._piper_failed = True   # not installed / voice file missing: use the macOS voice
        return self._piper

    _el_blocked_until = 0.0

    def _synth_elevenlabs(self, sentence: str, path: str) -> bool:
        """ElevenLabs -> wav at `path`. Any problem (no key, no credits, offline, plan doesn't allow the voice) returns
        False so the caller falls back to the offline voice; we then stay off it for a while instead of retrying every sentence."""
        if not config.ELEVENLABS_API_KEY or time.time() < self._el_blocked_until:
            return False
        month = f"el_chars_{datetime.now():%Y-%m}"
        used = int((store.query("SELECT value FROM meta WHERE key=?", (month,)) or [{"value": 0}])[0]["value"] or 0)
        text = guard.redact(sentence)                      # never send secrets to a cloud voice
        if used + len(text) > config.ELEVENLABS_MONTHLY_CHARS:
            self._el_blocked_until = time.time() + 3600
            print("(ElevenLabs monthly character budget reached: using the Mac voice.)")
            return False
        try:
            import httpx
            r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}",
                           params={"output_format": "pcm_16000"}, timeout=20,
                           headers={"xi-api-key": config.ELEVENLABS_API_KEY},
                           json={"text": text, "model_id": config.ELEVENLABS_MODEL})
        except Exception:
            self._el_blocked_until = time.time() + 60      # offline / timeout: try again in a minute
            return False
        if r.status_code != 200:
            why = {401: "the API key was rejected", 402: "your ElevenLabs plan doesn't include this voice via the API",
                   429: "rate limited"}.get(r.status_code, f"error {r.status_code}")
            print(f"(ElevenLabs: {why}; using the Mac voice for now.)")
            self._el_blocked_until = time.time() + (60 if r.status_code == 429 else 1800)
            return False
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(r.content)
        store.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (month, str(used + len(text))))
        return True

    def _synth(self, sentence: str):
        """Render one sentence to a wav file (ElevenLabs, Piper, or the macOS voice via `say -o`). None = play it live."""
        path = os.path.join(tempfile.gettempdir(), f"assistant_tts_{os.getpid()}_{time.time_ns()}.wav")
        if config.TTS_ENGINE == "elevenlabs" and self._synth_elevenlabs(sentence, path):
            return path
        voice = self._piper_voice() if config.TTS_ENGINE == "piper" else None
        if voice is not None:
            try:
                with wave.open(path, "wb") as w:
                    voice.synthesize_wav(sentence, w)
                return path
            except Exception:
                self._piper_failed = True
        if macos.IS_MAC:
            aiff = path[:-4] + ".aiff"
            try:
                subprocess.run(["say", "-v", config.TTS_VOICE, "-r", str(config.TTS_RATE), "-o", aiff, "--", sentence],
                               check=True, capture_output=True, timeout=30)
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, path],
                               check=True, capture_output=True, timeout=30)
                return path
            except Exception:
                return None
            finally:
                try:
                    os.remove(aiff)
                except OSError:
                    pass
        return None

    @staticmethod
    def _envelope(path: str):
        """Loudness of our own speech per 100 ms, so we can tell it apart from the user talking over it."""
        import numpy as np
        try:
            with wave.open(path, "rb") as w:
                sr, n = w.getframerate(), w.getnframes()
                x = np.frombuffer(w.readframes(n), dtype=np.int16).astype("float32") / 32768
                if w.getnchannels() > 1:
                    x = x.reshape(-1, w.getnchannels()).mean(axis=1)
            hop = max(1, sr // 10)
            return np.array([float(np.sqrt(np.mean(x[i:i + hop] ** 2))) for i in range(0, len(x), hop) if len(x[i:i + hop])])
        except Exception:
            return None

    @staticmethod
    def _sentences(text: str) -> list:
        parts = [p.strip() for p in re.split(r"(?<=[.!?:;])\s+|\n+", text) if p.strip()]
        out = []
        for p in parts:                       # merge tiny fragments so playback isn't choppy
            if out and (len(out[-1]) < 10 or len(p) < 10):
                out[-1] += " " + p
            else:
                out.append(p)
        return out or [text]

    def _wait(self, proc, stream, st, env=None) -> bool:
        """Wait for playback to end. Returns True if the user started talking over it (playback is stopped).
        With `env` (our own loudness over time) the echo of our voice is predicted block by block, so a short word
        like "stop" in a pause or over a quiet syllable is caught; without it a fixed echo level is used."""
        import numpy as np
        if stream is None:
            k = 0
            while proc.poll() is None:
                if self.stop_requested:
                    proc.terminate()
                    return True
                if self.visualizer is not None:
                    level = float(env[min(k, len(env) - 1)]) * 3 if env is not None and len(env) \
                        else 0.3 + 0.2 * math.sin(k * 0.5)
                    self.visualizer.set_level(min(1.0, level))
                time.sleep(0.05)
                k += 1
            return False
        st.setdefault("k", 0)
        st.setdefault("gains", [])
        while proc.poll() is None:
            if self.stop_requested:
                proc.terminate()
                return True
            data, _ = stream.read(1600)
            data = np.squeeze(data).copy()
            rms = float(np.sqrt(np.mean(data ** 2)))
            st["buf"] = (st["buf"] + [data])[-6:]
            st["t"] += 0.1
            st["k"] += 1
            if self.visualizer is not None:
                lvl = float(env[min(st["k"], len(env) - 1)]) * 3 if env is not None and len(env) else rms * 10
                self.visualizer.set_level(min(1.0, lvl))
            if env is not None and len(env):
                k = st["k"]
                expected = float(env[max(0, k - 3):k + 2].max()) if k - 3 < len(env) else 0.0
                if st["t"] < 0.8:                        # calibrate: how much of our voice does the mic pick up?
                    if expected > 0.02:
                        st["gains"].append(rms / expected)
                    continue
                gain = sorted(st["gains"])[len(st["gains"]) // 2] if st["gains"] else 0.3
                hot = rms > (min(gain, 3.0) * expected * 2.0 + 0.035) * st.get("boost", 1.0)
                need = 3                                 # 0.3 s of unexpected sound
                if config.WAKE_DEBUG:
                    print(f"    k={k:3d} mic={rms:.3f} expected_echo={min(gain, 3.0) * expected:.3f} (own voice {expected:.3f}, gain {gain:.2f}) {'HOT' if hot else ''}")
            else:
                if st["t"] < 0.8:
                    st["base"] = max(st["base"], rms)
                    continue
                hot = rms > max(0.03, 2.5 * st["base"]) * st.get("boost", 1.0)
                need = 3
            st["hot"] = st["hot"] + 1 if hot else 0
            if st["hot"] >= need:
                # Something loud: PAUSE our speech and listen. If it's really the user, stop for good; if it was
                # a noise, resume exactly where we were, so we never leave a sentence half said.
                if self._heard_user(proc, stream, st):
                    return True
                st["hot"] = 0
        return False

    def _heard_user(self, proc, stream, st) -> bool:
        import numpy as np
        try:
            os.kill(proc.pid, signal.SIGSTOP)
        except (OSError, TypeError):
            return False
        audio, quiet, peak = list(st["buf"]), 0.0, 0.0
        for _ in range(60):                                # up to 6 s of what the user says
            data, _ = stream.read(1600)
            data = np.squeeze(data).copy()
            audio.append(data)
            rms = float(np.sqrt(np.mean(data ** 2)))
            peak = max(peak, rms)
            quiet = 0.0 if rms > max(0.012, 0.35 * peak) else quiet + 0.1
            if quiet >= 0.6 and len(audio) >= 12:
                break
        text = self.transcribe(np.concatenate(audio))
        own_voice = bool(text) and self._echo_of(text, self.speaking_text)
        if own_voice:                                      # we heard ourselves: be less jumpy for the rest of this message
            st["boost"] = min(st.get("boost", 1.0) * 1.6, 6.0)
        if text and not own_voice and self.last_conf > -1.1 and not self._JUNK.match(text):
            proc.terminate()
            try:
                os.kill(proc.pid, signal.SIGCONT)          # let the pending terminate take effect
            except OSError:
                pass
            self.barge_audio, self.barge_text = None, text
            return True
        try:
            os.kill(proc.pid, signal.SIGCONT)              # false alarm: carry on talking
        except OSError:
            pass
        return False

    _EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200d\u2B50\u2B06\u2934\u3030]+")

    @classmethod
    def tts_clean(cls, text: str) -> str:
        """Text as it should be SPOKEN: no links, e-mail addresses, emoji or list markers read out letter by letter."""
        t = re.sub(r"https?://\S+", "link", text)
        t = re.sub(r"\s*<[^<>\s]*@[^<>\s]*>", "", t)                       # "Priya <priya@x.com>" -> "Priya"
        t = re.sub(r"#(\d+)\s*\[unread\]", r"Number \1, unread:", t)        # check_mail lines
        t = re.sub(r"#(\d+)", r"Number \1", t)
        t = cls._EMOJI.sub("", t)
        t = re.sub(r"[*#`_>\[\]]", "", t)
        return re.sub(r"[ \t]{2,}", " ", t).strip()

    def speak(self, text: str, barge: bool = True, settle: bool = True):
        clean = self.tts_clean(text)
        print(f"Assistant: {text}")
        self._start_ptt()
        if self.visualizer is not None:
            self.visualizer.set_mode("speaking")
        with self._speak_lock:
            self.speaking, self.stop_requested = True, False
            self.speaking_text = clean
            stream = None
            if barge and self.barge_enabled() and threading.current_thread() is threading.main_thread():
                try:
                    stream = self._audio().InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=1600,
                                                       device=self.input_device())
                    stream.start()
                except Exception:
                    stream = None
            st = {"buf": [], "t": 0.0, "base": 0.0, "hot": 0, "k": 0, "gains": []}
            sentences = self._sentences(clean)
            pool = ThreadPoolExecutor(1)
            try:
                fut = pool.submit(self._synth, sentences[0])
                for i, sentence in enumerate(sentences):
                    wav = fut.result()
                    if i + 1 < len(sentences):
                        fut = pool.submit(self._synth, sentences[i + 1])   # prepare the next while this one plays
                    env = None
                    if wav:
                        env = self._envelope(wav)
                        proc = subprocess.Popen(["afplay", wav])
                    elif macos.IS_MAC:
                        proc = subprocess.Popen(["say", "-v", config.TTS_VOICE, sentence])
                    else:
                        print(f"[say] {sentence}")
                        continue
                    st["k"] = 0                      # envelope index restarts with every sentence
                    cut = self._wait(proc, stream, st, env)
                    if wav:
                        try:
                            os.remove(wav)
                        except OSError:
                            pass
                    if cut:
                        self.barged = True
                        break
            finally:
                pool.shutdown(wait=False)
                if stream is not None:
                    stream.stop()
                    stream.close()
        self.last_spoken, self.spoke_end, self.speaking_text, self.speaking = clean, time.time(), "", False
        self.follow_until = time.time() + 15 if clean.rstrip().endswith("?") and barge else 0.0   # asked something: no wake word needed to answer
        if self.visualizer is not None:
            self.visualizer.set_mode("idle")
            self.visualizer.set_level(0.0)
        if not self.barged and settle:
            time.sleep(0.8 if self.using_speakers() else 0.4)   # let the room's echo die down before listening again
        self.last_active = time.time()

    def confirm(self, description: str) -> bool:
        """Spoken yes/no approval."""
        first = description.split("\n", 1)[0]
        spoken = first if len(first) <= 140 and "\n" not in description else first[:100].rsplit(" ", 1)[0] + ", the details are on screen"
        if "\n" in description or len(description) > 140:
            print(f"\n  APPROVAL NEEDED:\n  {description}\n")     # long text (code, email body) is shown, not read out
        for _ in range(2):
            self.speak(f"I need your approval to {spoken}. Say yes or no.", barge=False)
            heard = self.listen_now().lower()
            print(f"(heard: {heard!r})")
            if re.search(r"\b(yes|yeah|yep|approve|go ahead|do it|sure|okay)\b", heard):
                return True
            if re.search(r"\b(no|nope|deny|cancel|stop|don't)\b", heard):
                return False
        self.speak("I didn't catch that, so I won't do it.", barge=False)
        return False
