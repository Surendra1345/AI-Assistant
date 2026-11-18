// Crystal-sphere visualizer: a rotating 3D wireframe ball made of points connected to their
// nearest neighbors (a Fibonacci sphere), glowing and reacting live to the assistant's mic/speech
// levels over Server-Sent Events. Pure Canvas 2D - no WebGL/Three.js - with a small hand-rolled
// perspective projection so the mesh reads as a sphere, not a flat ring.

const canvas = document.getElementById("ring");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");

// Render at device pixel ratio for a crisp (not blurry) look on retina screens.
const DPR = window.devicePixelRatio || 1;
const SIZE = canvas.width;
canvas.width = SIZE * DPR;
canvas.height = SIZE * DPR;
canvas.style.width = SIZE + "px";
canvas.style.height = SIZE + "px";
ctx.scale(DPR, DPR);

const CENTER = SIZE / 2;
const N_POINTS = 180;
const NEIGHBORS = 3;           // mesh lines per point
const BASE_RADIUS = 140;
const FOCAL = 420;             // perspective: smaller = more dramatic depth

const COLORS = {
  idle: [140, 180, 255],       // soft blue-white
  listening: [120, 230, 240],  // cyan
  speaking: [210, 160, 255],   // violet-white
};

const state = { mode: "idle", level: 0, target: 0, rotY: 0, rotX: 0.3 };

function lerp(a, b, t) { return a + (b - a) * t; }

// ---- build a Fibonacci sphere: N points spread evenly over a unit sphere's surface
function buildSphere(n) {
  const pts = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;        // -1..1
    const r = Math.sqrt(1 - y * y);
    const theta = golden * i;
    pts.push({ x: Math.cos(theta) * r, y, z: Math.sin(theta) * r });
  }
  return pts;
}

// ---- connect each point to its nearest neighbors once; rigid rotation preserves these edges
function buildEdges(pts, k) {
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
        edges.push([i, j]);
      }
    }
  }
  return edges;
}

const sphere = buildSphere(N_POINTS);
const edges = buildEdges(sphere, NEIGHBORS);

function rotate(p, rx, ry) {
  // rotate around X then Y
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
    depth: (p.z + 1) / 2,   // 0 (far) .. 1 (near), for brightness
    scale,
  };
}

function draw() {
  state.level = lerp(state.level, state.target, 0.18);
  const spin = 0.004 + state.level * 0.01;
  state.rotY += spin;
  state.rotX = 0.3 + Math.sin(state.rotY * 0.6) * 0.08;

  ctx.clearRect(0, 0, SIZE, SIZE);

  const [r, g, b] = COLORS[state.mode] || COLORS.idle;
  const breathing = state.mode === "idle" ? 0.5 + 0.5 * Math.sin(state.rotY * 1.3) : 0;
  const radius = BASE_RADIUS + state.level * 45 + breathing * 6;

  const projected = sphere.map((p) => project(rotate(p, state.rotX, state.rotY), radius));

  // mesh lines first (so points/glow sit on top)
  for (const [i, j] of edges) {
    const a = projected[i], c = projected[j];
    const depth = (a.depth + c.depth) / 2;
    const alpha = 0.08 + depth * 0.35 + state.level * 0.15;
    ctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
    ctx.lineWidth = 0.6 + depth * 0.5;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(c.x, c.y);
    ctx.stroke();
  }

  // glowing points on top
  for (const p of projected) {
    const alpha = 0.3 + p.depth * 0.6;
    const size = (0.9 + p.depth * 1.6) * p.scale;
    ctx.beginPath();
    ctx.fillStyle = `rgba(${Math.min(255, r + 40)}, ${Math.min(255, g + 40)}, ${Math.min(255, b + 40)}, ${alpha.toFixed(3)})`;
    ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.9)`;
    ctx.shadowBlur = 6 + state.level * 8;
    ctx.arc(p.x, p.y, size, 0, 2 * Math.PI);
    ctx.fill();
  }
  ctx.shadowBlur = 0;

  // soft core glow at the centre, brighter with level
  const coreR = 30 + state.level * 35;
  const gradient = ctx.createRadialGradient(CENTER, CENTER, 0, CENTER, CENTER, coreR);
  gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${0.25 + state.level * 0.25})`);
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
      // malformed event: keep the sphere's current state, don't crash the loop
    }
  };
  es.onerror = () => {
    es.close();
    setTimeout(connect, 1500);   // browser-side retry; the sphere keeps breathing meanwhile
  };
}

connect();
requestAnimationFrame(draw);
