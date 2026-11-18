"""Floating 'crystal ring' visualizer: a circle of crystal shapes that ripple like waves while the
assistant listens or speaks. Runs in its own process (Tkinter needs the main thread on macOS, and the
voice loop already owns this process's main thread), so it talks to the rest of the app over a
multiprocessing Queue and can never block or crash the assistant itself - if the display, Tkinter,
or the subprocess is unavailable for any reason, start() just logs once and does nothing.

States: "idle" (slow breathing), "listening" (reacts to mic level), "speaking" (reacts to the
assistant's own speech envelope). Call set_level(0..1) often while in a reactive state; the ring
smooths it internally so levels can arrive in little bursts without looking jerky.
"""
import logging
import math
import multiprocessing as mp
import time

log = logging.getLogger("visualizer")

_COLORS = {
    "idle": (70, 130, 220),        # soft blue
    "listening": (60, 220, 230),   # cyan
    "speaking": (170, 110, 240),   # violet
}
N_CRYSTALS = 16
SIZE = 260                          # window is SIZE x SIZE
CENTER = SIZE / 2
BASE_RADIUS = 70
FPS = 30


def _lerp(a, b, t):
    return a + (b - a) * t


def _run(q: "mp.Queue"):
    try:
        import tkinter as tk
    except Exception:
        return  # no Tk available (e.g. headless/no display) - stay silent, assistant works without it

    try:
        _run_gui(q, tk)
    except Exception:
        return  # any GUI failure here must never surface as a crash - the voice loop doesn't depend on this


def _run_gui(q: "mp.Queue", tk):
    root = tk.Tk()
    root.title("Jarvis")
    root.overrideredirect(True)          # no title bar/border: looks like a floating orb
    root.attributes("-topmost", True)
    try:
        root.wm_attributes("-transparent", True)
        root.config(bg="black")
    except tk.TclError:
        pass
    root.geometry(f"{SIZE}x{SIZE}+80+80")

    canvas = tk.Canvas(root, width=SIZE, height=SIZE, bg="black", highlightthickness=0)
    canvas.pack()
    # let the user drag the window around by its background
    drag = {"x": 0, "y": 0}

    def start_drag(e):
        drag["x"], drag["y"] = e.x, e.y

    def do_drag(e):
        root.geometry(f"+{root.winfo_x() + e.x - drag['x']}+{root.winfo_y() + e.y - drag['y']}")

    canvas.bind("<ButtonPress-1>", start_drag)
    canvas.bind("<B1-Motion>", do_drag)

    state = {"mode": "idle", "level": 0.0, "target": 0.0, "phase": 0.0, "closed": False}

    def poll_queue():
        try:
            while True:
                msg = q.get_nowait()
                if msg[0] == "level":
                    state["target"] = max(0.0, min(1.0, msg[1]))
                elif msg[0] == "mode":
                    state["mode"] = msg[1]
                elif msg[0] == "stop":
                    state["closed"] = True
        except Exception:
            pass
        if state["closed"]:
            root.destroy()
            return
        root.after(max(1, int(1000 / FPS)), poll_queue)

    def draw():
        if state["closed"]:
            return
        # smooth toward the latest level so bursty updates still look like waves, not jumps
        state["level"] = _lerp(state["level"], state["target"], 0.25)
        state["phase"] += 0.12 + state["level"] * 0.25
        canvas.delete("all")
        r, g, b = _COLORS.get(state["mode"], _COLORS["idle"])
        idle_breath = 0.5 + 0.5 * math.sin(state["phase"] * 0.5)
        wave_amp = 10 + state["level"] * 55 + (6 if state["mode"] == "idle" else 0) * idle_breath

        for i in range(N_CRYSTALS):
            angle = (2 * math.pi * i) / N_CRYSTALS
            wobble = math.sin(state["phase"] + i * 0.9) * wave_amp
            radius = BASE_RADIUS + wobble
            cx = CENTER + radius * math.cos(angle)
            cy = CENTER + radius * math.sin(angle)
            crystal_size = 7 + state["level"] * 10 + 3 * math.sin(state["phase"] * 1.3 + i)
            glow = 0.4 + 0.6 * ((math.sin(state["phase"] + i * 0.9) + 1) / 2)
            fill = f"#{int(r * glow):02x}{int(g * glow):02x}{int(b * glow):02x}"
            pts = []
            for k in range(4):
                a2 = angle + k * math.pi / 2
                pts.append(cx + crystal_size * math.cos(a2))
                pts.append(cy + crystal_size * math.sin(a2))
            canvas.create_polygon(*pts, fill=fill, outline="")
        # soft center core
        core_r = 18 + state["level"] * 20
        core_glow = 0.5 + 0.5 * state["level"]
        core_fill = f"#{int(r * core_glow):02x}{int(g * core_glow):02x}{int(b * core_glow):02x}"
        canvas.create_oval(CENTER - core_r, CENTER - core_r, CENTER + core_r, CENTER + core_r,
                            fill=core_fill, outline="")
        root.after(max(1, int(1000 / FPS)), draw)

    root.after(0, poll_queue)
    root.after(0, draw)
    try:
        root.mainloop()
    except Exception:
        pass


class Visualizer:
    """Non-blocking handle: start() spawns the window in its own process. Safe to call set_mode/
    set_level/stop from any thread; failures here never raise into the caller."""

    def __init__(self):
        self._queue = None
        self._proc = None
        self._ok = False

    def start(self):
        try:
            ctx = mp.get_context("spawn")
            self._queue = ctx.Queue()
            self._proc = ctx.Process(target=_run, args=(self._queue,), daemon=True)
            self._proc.start()
            self._ok = True
            log.info("visualizer window started")
        except Exception as e:
            log.warning(f"visualizer unavailable: {e}")
            self._ok = False

    def set_mode(self, mode: str):
        if self._ok:
            try:
                self._queue.put_nowait(("mode", mode))
            except Exception:
                pass

    def set_level(self, level: float):
        if self._ok:
            try:
                self._queue.put_nowait(("level", level))
            except Exception:
                pass

    def stop(self):
        if self._ok:
            try:
                self._queue.put_nowait(("stop", None))
            except Exception:
                pass
            self._ok = False
