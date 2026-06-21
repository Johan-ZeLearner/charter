// charter studio — beat-grid & structure editor.
// Top: a Clone-Hero highway where beat/bar lines fly toward a strikeline with a
// metronome click, so you can SEE and HEAR whether the grid matches the music.
// Bottom: a DAW timeline (waveform + beats/bars + sections + tempo curve).
// The grid is the foundation; this tool exists to ground and correct it.
import * as THREE from 'three';

const $ = (id) => document.getElementById(id);
const el = {
  songinfo:$('songinfo'), bpmOut:$('bpmOut'), beatsOut:$('beatsOut'), barsOut:$('barsOut'),
  tempo_mult:$('tempo_mult'), tempo_hint:$('tempo_hint'), hintOut:$('hintOut'),
  beats_per_bar:$('beats_per_bar'), phaseShift:$('phaseShift'), reanalyze:$('reanalyze'),
  sectionCount:$('sectionCount'), sectionList:$('sectionList'), diag:$('diag'),
  highway:$('highway'), play:$('play'), click:$('click'), clock:$('clock'), status:$('status'),
  tl:$('tl'),
};

// section palette by label letter
const SECT_COLORS = ['#3a82f6','#33c66b','#f2c83f','#e6549a','#ff8c2e','#9b6cf2','#37d6d0','#e6394a'];
const sectColor = (label) => SECT_COLORS[(label.charCodeAt(0) - 65) % SECT_COLORS.length];

let data = null;          // last analysis payload
let duration = 0;
let phase = 0, bpb = 4;   // current downbeat phase / beats-per-bar

// ============================================================================
//  Audio (full song) + metronome click
// ============================================================================
const audio = new Audio('/api/audio');
audio.preload = 'auto';
let actx = null;
const ensureCtx = () => (actx ||= new (window.AudioContext || window.webkitAudioContext)());
audio.addEventListener('play', () => { el.play.textContent = '⏸ Pause'; ensureCtx().resume(); });
audio.addEventListener('pause', () => { el.play.textContent = '▶ Play'; });
audio.addEventListener('ended', () => { el.play.textContent = '▶ Play'; });

function click(strong) {
  if (!el.click.checked) return;
  const ctx = ensureCtx(), t = ctx.currentTime;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.frequency.value = strong ? 1600 : 900;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(strong ? 0.5 : 0.28, t + 0.002);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.05);
  o.connect(g); g.connect(ctx.destination); o.start(t); o.stop(t + 0.06);
}

// ============================================================================
//  Highway (Three.js) — beat/bar lines + section tint scrolling to a strikeline
// ============================================================================
const BOARD_W = 4.2, SPEED = 6.0, STRIKE_Z = 3.5, LOOKAHEAD = 3.5, PAST = 0.5;
const FAR_Z = STRIKE_Z - LOOKAHEAD * SPEED;

const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
el.highway.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0c0e14);
const CAM = { y:6.0, z:STRIKE_Z + 5.2 };
const FAR_DIST = Math.hypot(CAM.z - FAR_Z, CAM.y);
scene.fog = new THREE.Fog(0x0c0e14, FAR_DIST * 0.5, FAR_DIST + 6);
const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 200);
camera.position.set(0, CAM.y, CAM.z);
camera.lookAt(0, 0, (STRIKE_Z + FAR_Z) / 2);
scene.add(new THREE.AmbientLight(0x9fb4e0, 0.8));

const boardLen = STRIKE_Z - FAR_Z + 3, boardCz = (STRIKE_Z + FAR_Z) / 2 - 1;
const board = new THREE.Mesh(new THREE.PlaneGeometry(BOARD_W, boardLen),
  new THREE.MeshBasicMaterial({ color:0x10141f }));
board.rotation.x = -Math.PI / 2; board.position.set(0, 0, boardCz); scene.add(board);
const strike = new THREE.Mesh(new THREE.BoxGeometry(BOARD_W + 0.2, 0.05, 0.18),
  new THREE.MeshBasicMaterial({ color:0xbcd2ff }));
strike.position.set(0, 0.04, STRIKE_Z); scene.add(strike);

const GEO_BEAT = new THREE.PlaneGeometry(BOARD_W, 0.05);
const GEO_BAR = new THREE.PlaneGeometry(BOARD_W + 0.12, 0.10);
let gridGroup = null;

function buildHighway(d) {
  if (gridGroup) { scene.remove(gridGroup); gridGroup.traverse(o => o.material && o.material.dispose()); }
  gridGroup = new THREE.Group(); scene.add(gridGroup);

  // section-colored board segments
  for (const s of d.sections) {
    const len = (s.end - s.start) * SPEED;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(BOARD_W, Math.max(0.01, len)),
      new THREE.MeshBasicMaterial({ color:new THREE.Color(sectColor(s.label)), transparent:true, opacity:0.10 }));
    m.rotation.x = -Math.PI / 2;
    m.position.set(0, 0.005, STRIKE_Z - (s.start + s.end) / 2 * SPEED);
    m.userData.span = [s.start, s.end]; gridGroup.add(m);
  }
  const downset = new Set(d.downbeats.map(t => Math.round(t * 1000)));
  for (const t of d.beats) {
    const down = downset.has(Math.round(t * 1000));
    const m = new THREE.Mesh(down ? GEO_BAR : GEO_BEAT, new THREE.MeshBasicMaterial({
      color: down ? 0x7d93c4 : 0x33415e, transparent:true, opacity: down ? 1 : 0.7 }));
    m.rotation.x = -Math.PI / 2; m.position.set(0, 0.02, STRIKE_Z - t * SPEED);
    m.userData.t = t; gridGroup.add(m);
  }
  beatCursor = 0;
}

let beatCursor = 0;  // next beat index to click
function animate() {
  requestAnimationFrame(animate);
  const c = audio.currentTime || 0;
  if (gridGroup) {
    gridGroup.position.z = c * SPEED;
    for (const o of gridGroup.children) {
      if (o.userData.t != null) { const dz = o.userData.t - c; o.visible = dz < LOOKAHEAD && dz > -PAST; }
      else if (o.userData.span) { const [a,b] = o.userData.span; o.visible = b - c > -PAST && a - c < LOOKAHEAD; }
    }
  }
  // metronome: fire clicks for beats we just crossed
  if (data && !audio.paused) {
    while (beatCursor < data.beats.length && data.beats[beatCursor] <= c) {
      const t = data.beats[beatCursor];
      if (c - t < 0.2) click(((beatCursor - phase) % bpb + bpb) % bpb === 0);
      beatCursor++;
    }
  }
  el.clock.textContent = fmt(c);
  drawTimeline(c);
  renderer.render(scene, camera);
}
function resizeHighway() {
  const w = el.highway.clientWidth, h = el.highway.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}

// ============================================================================
//  DAW timeline (2D canvas)
// ============================================================================
const tl = el.tl, ctx2d = tl.getContext('2d');
let view = { start:0, end:1 };   // visible time range (seconds)
let tlW = 0, tlH = 0, dpr = 1;

function resizeTimeline() {
  dpr = Math.min(window.devicePixelRatio, 2);
  tlW = tl.clientWidth; tlH = tl.clientHeight;
  tl.width = Math.round(tlW * dpr); tl.height = Math.round(tlH * dpr);
  ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
}
const tToX = (t) => (t - view.start) / (view.end - view.start) * tlW;
const xToT = (x) => view.start + x / tlW * (view.end - view.start);

const SECT_H = 24, TEMPO_H = 34;
function drawTimeline(playT) {
  if (!data || !tlW) return;
  const ctx = ctx2d;
  ctx.clearRect(0, 0, tlW, tlH);
  const waveTop = SECT_H, waveBot = tlH - TEMPO_H, waveH = waveBot - waveTop, mid = (waveTop + waveBot) / 2;

  // sections band
  for (const s of data.sections) {
    const x0 = tToX(s.start), x1 = tToX(s.end);
    if (x1 < 0 || x0 > tlW) continue;
    ctx.fillStyle = sectColor(s.label) + '33';
    ctx.fillRect(x0, 0, x1 - x0, SECT_H);
    ctx.fillStyle = sectColor(s.label);
    ctx.fillRect(x0, 0, 2, SECT_H);
    ctx.fillStyle = '#e7ecf5'; ctx.font = '11px ui-sans-serif'; ctx.textBaseline = 'middle';
    if (x1 - x0 > 16) ctx.fillText(s.label, x0 + 6, SECT_H / 2);
  }

  // waveform
  const wf = data.waveform, bt = duration / wf.length;
  ctx.strokeStyle = '#2f3b54'; ctx.beginPath();
  for (let px = 0; px <= tlW; px++) {
    const t = xToT(px), i = Math.floor(t / bt);
    if (i < 0 || i >= wf.length) continue;
    const a = wf[i] * waveH * 0.48;
    ctx.moveTo(px, mid - a); ctx.lineTo(px, mid + a);
  }
  ctx.stroke();

  // beats + bars
  const downset = new Set(data.downbeats.map(t => Math.round(t * 1000)));
  const spacingOk = (view.end - view.start) / tlW < 0.06;  // hide beat ticks when too dense
  let bar = 0;
  for (const t of data.beats) {
    const x = tToX(t); if (x < -2 || x > tlW + 2) { continue; }
    const down = downset.has(Math.round(t * 1000));
    if (down) {
      ctx.strokeStyle = '#7d93c4'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, waveTop); ctx.lineTo(x, waveBot); ctx.stroke();
      ctx.fillStyle = '#5d6781'; ctx.font = '9px ui-monospace';
      ctx.fillText(String(++bar), x + 2, waveTop + 8);
    } else if (spacingOk) {
      ctx.strokeStyle = '#222c41'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, mid - waveH * 0.3); ctx.lineTo(x, mid + waveH * 0.3); ctx.stroke();
    }
  }

  // tempo curve strip
  const ty = tlH - TEMPO_H, tc = data.tempoCurve;
  ctx.fillStyle = '#0e1320'; ctx.fillRect(0, ty, tlW, TEMPO_H);
  if (tc.length) {
    let lo = Infinity, hi = -Infinity;
    for (const p of tc) { lo = Math.min(lo, p.bpm); hi = Math.max(hi, p.bpm); }
    const pad = Math.max(4, (hi - lo) * 0.15); lo -= pad; hi += pad;
    ctx.strokeStyle = '#37e0a6'; ctx.lineWidth = 1.5; ctx.beginPath();
    let started = false;
    for (const p of tc) {
      const x = tToX(p.t); if (x < 0 || x > tlW) { started = false; continue; }
      const y = ty + TEMPO_H - (p.bpm - lo) / (hi - lo) * TEMPO_H;
      started ? ctx.lineTo(x, y) : ctx.moveTo(x, y); started = true;
    }
    ctx.stroke();
    ctx.fillStyle = '#5d6781'; ctx.font = '9px ui-monospace';
    ctx.fillText(`${Math.round(hi)} bpm`, 4, ty + 9);
    ctx.fillText(`${Math.round(lo)}`, 4, ty + TEMPO_H - 3);
  }

  // playhead
  const px = tToX(playT);
  if (px >= 0 && px <= tlW) {
    ctx.strokeStyle = '#bcd2ff'; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, tlH); ctx.stroke();
  }
}

// timeline interactions: click seeks, wheel zooms, drag pans
let dragging = false, dragX = 0, dragStart = null, moved = false;
tl.addEventListener('pointerdown', (e) => { dragging = true; moved = false; dragX = e.offsetX; dragStart = { ...view }; });
window.addEventListener('pointerup', () => {
  if (dragging && !moved) seek(xToT(dragX));
  dragging = false;
});
window.addEventListener('pointermove', (e) => {
  if (!dragging) return;
  const dx = e.offsetX - dragX; if (Math.abs(dx) > 3) moved = true;
  const span = dragStart.end - dragStart.start, dt = -dx / tlW * span;
  let s = dragStart.start + dt, en = dragStart.end + dt;
  if (s < 0) { en -= s; s = 0; } if (en > duration) { s -= en - duration; en = duration; }
  view = { start:Math.max(0, s), end:Math.min(duration, en) };
});
tl.addEventListener('wheel', (e) => {
  e.preventDefault();
  const span = view.end - view.start, f = e.deltaY > 0 ? 1.2 : 1 / 1.2;
  const ns = Math.min(duration, Math.max(0.5, span * f));
  const cx = xToT(e.offsetX), r = e.offsetX / tlW;
  let s = cx - ns * r, en = cx + ns * (1 - r);
  if (s < 0) { en -= s; s = 0; } if (en > duration) { s -= en - duration; en = duration; }
  view = { start:Math.max(0, s), end:Math.min(duration, en) };
}, { passive:false });

function seek(t) {
  t = Math.max(0, Math.min(duration, t));
  audio.currentTime = t;
  beatCursor = data ? data.beats.findIndex(b => b >= t) : 0;
  if (beatCursor < 0) beatCursor = data ? data.beats.length : 0;
}

// ============================================================================
//  Analyze + render
// ============================================================================
let busy = false;
async function analyze() {
  if (busy) return; busy = true;
  el.status.textContent = 'analyzing…'; el.status.className = 'status busy';
  const p = new URLSearchParams({
    tempo_mult: el.tempo_mult.value, beats_per_bar: el.beats_per_bar.value, phase: String(phase),
  });
  if (+el.tempo_hint.value > 0) p.set('tempo_hint', el.tempo_hint.value);
  try {
    const r = await fetch('/api/analyze?' + p.toString());
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
    data = d; bpb = d.beatsPerBar; phase = d.phase;
    renderAll(d);
    el.status.textContent = `${d.analysis.beats} beats · ${d.analysis.sections} sections`;
    el.status.className = 'status';
  } catch (e) {
    el.status.textContent = 'error: ' + e.message; el.status.className = 'status err';
  } finally { busy = false; }
}

function renderAll(d) {
  if (view.end <= view.start || view.end > duration + 0.5) view = { start:0, end:duration };
  el.bpmOut.textContent = d.bpm; el.beatsOut.textContent = d.analysis.beats; el.barsOut.textContent = d.analysis.downbeats;
  el.sectionCount.textContent = `${d.sections.length} found`;
  el.sectionList.innerHTML = '';
  d.sections.forEach((s) => {
    const row = document.createElement('div'); row.className = 'sectionRow';
    row.innerHTML = `<span class="swatch" style="background:${sectColor(s.label)}"></span>` +
      `<span class="lab">${s.label}</span><span>${fmt(s.start)}</span>` +
      `<span class="tm">${(s.end - s.start).toFixed(0)}s</span>`;
    row.onclick = () => seek(s.start);
    el.sectionList.appendChild(row);
  });
  el.diag.textContent = `raw ${d.analysis.rawBpm} → ${d.bpm} bpm (×${d.tempoMult})\n` +
    `${bpb}/4 · phase ${phase} · drift ${tempoRange(d)}`;
  buildHighway(d);
}
function tempoRange(d) {
  if (!d.tempoCurve.length) return '—';
  let lo = Infinity, hi = -Infinity;
  for (const p of d.tempoCurve) { lo = Math.min(lo, p.bpm); hi = Math.max(hi, p.bpm); }
  return `${lo.toFixed(0)}–${hi.toFixed(0)}`;
}

// ============================================================================
//  Controls
// ============================================================================
const fmt = (s) => { s = Math.max(0, s); const m = Math.floor(s / 60); const r = (s % 60); return `${m}:${r.toFixed(1).padStart(4, '0')}`; };

el.tempo_mult.addEventListener('change', analyze);
el.beats_per_bar.addEventListener('change', () => { phase = 0; analyze(); });
el.tempo_hint.addEventListener('input', () => { el.hintOut.textContent = +el.tempo_hint.value > 0 ? el.tempo_hint.value : 'auto'; });
el.tempo_hint.addEventListener('change', analyze);
el.phaseShift.addEventListener('click', () => { phase = (phase + 1) % bpb; analyze(); });
el.reanalyze.addEventListener('click', analyze);
el.play.addEventListener('click', () => { if (audio.paused) audio.play(); else audio.pause(); });
window.addEventListener('resize', () => { resizeHighway(); resizeTimeline(); });

// ============================================================================
//  Init
// ============================================================================
async function init() {
  resizeHighway(); resizeTimeline(); animate();
  try {
    const meta = await (await fetch('/api/meta')).json();
    duration = meta.duration_s || 60; view = { start:0, end:duration };
    el.songinfo.textContent = `${meta.name} — ${meta.artist} · ${fmt(duration)}`;
  } catch (e) { el.songinfo.textContent = 'could not load song meta'; }
  await analyze();
}
init();
