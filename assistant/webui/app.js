// Crystal-ring visualizer: a ring of crystal shapes around a glowing core that
// ripples like waves while the assistant listens or speaks. Receives live
// mode/level updates from the Python assistant over Server-Sent Events.

const canvas = document.getElementById("ring");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");

const SIZE = canvas.width;
const CENTER = SIZE / 2;
const N_CRYSTALS = 16;
const BASE_RADIUS = 90;

const COLORS = {
  idle: [70, 130, 220],       // soft blue
  listening: [60, 220, 230],  // cyan
  speaking: [170, 110, 240],  // violet
};

const state = {
  mode: "idle",
  level: 0,
  target: 0,
  phase: 0,
};

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function draw() {
  state.level = lerp(state.level, state.target, 0.22);
  state.phase += 0.1 + state.level * 0.22;

  ctx.clearRect(0, 0, SIZE, SIZE);

  const [r, g, b] = COLORS[state.mode] || COLORS.idle;
  const idleBreath = 0.5 + 0.5 * Math.sin(state.phase * 0.5);
  const waveAmp = 10 + state.level * 55 + (state.mode === "idle" ? 6 * idleBreath : 0);

  for (let i = 0; i < N_CRYSTALS; i++) {
    const angle = (2 * Math.PI * i) / N_CRYSTALS;
    const wobble = Math.sin(state.phase + i * 0.9) * waveAmp;
    const radius = BASE_RADIUS + wobble;
    const cx = CENTER + radius * Math.cos(angle);
    const cy = CENTER + radius * Math.sin(angle);
    const crystalSize = 9 + state.level * 12 + 3 * Math.sin(state.phase * 1.3 + i);
    const glow = 0.4 + 0.6 * ((Math.sin(state.phase + i * 0.9) + 1) / 2);

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(angle);
    ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.9)`;
    ctx.shadowBlur = 16;
    ctx.fillStyle = `rgba(${Math.round(r * glow)}, ${Math.round(g * glow)}, ${Math.round(b * glow)}, 0.95)`;
    ctx.beginPath();
    ctx.moveTo(crystalSize, 0);
    ctx.lineTo(0, crystalSize);
    ctx.lineTo(-crystalSize, 0);
    ctx.lineTo(0, -crystalSize);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  // glowing core
  const coreR = 24 + state.level * 22;
  const coreGlow = 0.5 + 0.5 * state.level;
  const gradient = ctx.createRadialGradient(CENTER, CENTER, 0, CENTER, CENTER, coreR);
  gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${0.9 * coreGlow})`);
  gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(CENTER, CENTER, coreR, 0, 2 * Math.PI);
  ctx.fill();

  requestAnimationFrame(draw);
}

function connect() {
  const es = new EventSource("/events");
  es.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "level") {
        state.target = Math.max(0, Math.min(1, msg.value));
      } else if (msg.type === "mode") {
        state.mode = msg.value;
        statusEl.textContent = msg.value;
      }
    } catch (err) {
      // ignore malformed events; the ring just keeps its last state
    }
  };
  es.onerror = () => {
    // browser auto-retries EventSource; meanwhile keep breathing idly
    es.close();
    setTimeout(connect, 1500);
  };
}

connect();
requestAnimationFrame(draw);
