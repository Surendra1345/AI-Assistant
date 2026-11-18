// Crystal-sphere visualizer: a tangled ball of glowing white threads on a solid blue background -
// a sphere's worth of points, jittered off a perfect lattice and connected with both short mesh
// edges and long chords through the interior, so it reads as a scribbled yarn-ball of light rather
// than a clean geometric wireframe. Reacts live to the assistant's mic/speech levels over SSE.

const canvas = document.getElementById("ring");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");

const DPR = window.devicePixelRatio || 1;
const SIZE = canvas.width;
canvas.width = SIZE * DPR;
canvas.height = SIZE * DPR;
canvas.style.width = SIZE + "px";
canvas.style.height = SIZE + "px";
ctx.scale(DPR, DPR);

const CENTER = SIZE / 2;
const N_POINTS = 260;
const SURFACE_NEIGHBORS = 3;   // short mesh edges per point (surface-hugging)
const CHORDS = 220;            // long random edges through the interior (the "tangled" look)
const BASE_RADIUS = 150;
const FOCAL = 460;

// mostly white, with a faint tint per mode so idle/listening/speaking stay distinguishable
const TINTS = {
  idle: [235, 240, 255],
  listening: [210, 245, 255],
  speaking: [245, 225, 255],
};

const state = { mode: "idle", level: 0, target: 0, rotY: 0, rotX: 0.3, t: 0 };

function lerp(a, b, t) { return a + (b - a) * t; }
function rand(a, b) { return a + Math.random() * (b - a); }

// ---- Fibonacci sphere, jittered so it reads as scribbled rather than a perfect lattice
function buildSphere(n) {
  const pts = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = golden * i;
    const jitter = rand(0.85, 1.12);   // uneven radius: breaks up the clean grid look
    pts.push({
      x: Math.cos(theta) * r * jitter,
      y: y * jitter,
      z: Math.sin(theta) * r * jitter,
      twinkle: Math.random() * Math.PI * 2,
    });
  }
  return pts;
}

function buildSurfaceEdges(pts, k) {
  const edges = [];
  const seen = new Set();
  for (let i = 0; i < pts.length; i++) {
    const dists = [];
    for (let j = 0; j < pts.length; j++) {
      if (i === j) continue;
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, dz = pts[i].z - pts[j].z;
      dists.push([j, dx * dx + dy * dy + dz * dz]);
    }
    dists.sort((a, b) => a[1] - b[1]);
    for (let m = 0; m < k; m++) {
      const j = dists[m][0];
      const key = i < j ? `${i}-${j}` : `${j}-${i}`;
      if (!seen.has(key)) {
        seen.add(key);
        edges.push([i, j, "surface"]);
      }
    }
  }
  return edges;
}

// ---- long chords connecting roughly-opposite-ish points through the interior: this is what
// makes it look like a tangled ball of thread instead of a clean geodesic globe
function buildChords(pts, count) {
  const chords = [];
  for (let c = 0; c < count; c++) {
    const i = Math.floor(Math.random() * pts.length);
    let j = Math.floor(Math.random() * pts.length);
    if (j === i) j = (j + 1) % pts.length;
    chords.push([i, j, "chord"]);
  }
  return chords;
}

const sphere = buildSphere(N_POINTS);
const edges = [...buildSurfaceEdges(sphere, SURFACE_NEIGHBORS), ...buildChords(sphere, CHORDS)];

function rotate(p, rx, ry) {
  let { x, y, z } = p;
  const cosX = Math.cos(rx), sinX = Math.sin(rx);
  const y1 = y * cosX - z * sinX, z1 = y * sinX + z * cosX;
  const cosY = Math.cos(ry), sinY = Math.sin(ry);
  const x2 = x * cosY + z1 * sinY, z2 = -x * sinY + z1 * cosY;
  return { x: x2, y: y1, z: z2 };
}

function project(p, radius) {
  const scale = FOCAL / (FOCAL + p.z * radius);
  return {
    x: CENTER + p.x * radius * scale,
    y: CENTER + p.y * radius * scale,
    depth: (p.z + 1) / 2,
    scale,
  };
}

function draw() {
  state.level = lerp(state.level, state.target, 0.18);
  state.t += 1;
  const spin = 0.0035 + state.level * 0.009;
  state.rotY += spin;
  state.rotX = 0.3 + Math.sin(state.rotY * 0.5) * 0.1;

  ctx.clearRect(0, 0, SIZE, SIZE);

  const [r, g, b] = TINTS[state.mode] || TINTS.idle;
  const breathing = state.mode === "idle" ? 0.5 + 0.5 * Math.sin(state.rotY * 1.2) : 0;
  const radius = BASE_RADIUS + state.level * 35 + breathing * 5;

  const projected = sphere.map((p, idx) => {
    const rp = project(rotate(p, state.rotX, state.rotY), radius);
    rp.twinkle = sphere[idx].twinkle;
    return rp;
  });

  // fine threads: thin, low-opacity, lots of them - the chaotic web look
  for (const [i, j, kind] of edges) {
    const a = projected[i], c = projected[j];
    const depth = (a.depth + c.depth) / 2;
    const base = kind === "chord" ? 0.05 : 0.12;
    const alpha = base + depth * 0.22 + state.level * 0.12;
    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
    ctx.lineWidth = kind === "chord" ? 0.4 : 0.55;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(c.x, c.y);
    ctx.stroke();
  }

  // sparkle points: small, twinkling, brighter near the viewer
  for (const p of projected) {
    const twinkle = 0.6 + 0.4 * Math.sin(state.t * 0.07 + p.twinkle);
    const alpha = (0.25 + p.depth * 0.55) * twinkle;
    const size = (0.6 + p.depth * 1.1) * p.scale;
    ctx.beginPath();
    ctx.fillStyle = `rgba(255, 255, 255, ${alpha.toFixed(3)})`;
    ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.95)`;
    ctx.shadowBlur = 4 + state.level * 6;
    ctx.arc(p.x, p.y, size, 0, 2 * Math.PI);
    ctx.fill();
  }
  ctx.shadowBlur = 0;

  // soft bright wash near the centre so it glows like the reference, not just a wire mesh
  const coreR = radius * 0.9;
  const gradient = ctx.createRadialGradient(CENTER, CENTER, 0, CENTER, CENTER, coreR);
  gradient.addColorStop(0, `rgba(255, 255, 255, ${0.12 + state.level * 0.1})`);
  gradient.addColorStop(0.6, `rgba(255, 255, 255, ${0.04 + state.level * 0.05})`);
  gradient.addColorStop(1, "rgba(255, 255, 255, 0)");
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
      // malformed event: keep current state, don't crash the loop
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connect, 1500);
  };
}

connect();
requestAnimationFrame(draw);
