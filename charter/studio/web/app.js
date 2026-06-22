// charter studio — beat-grid & structure editor.
// Top: a Clone-Hero highway where beat/bar lines fly toward a strikeline with a
// metronome click, so you can SEE and HEAR whether the grid matches the music.
// Bottom: a DAW timeline (waveform + beats/bars + sections + tempo curve).
// The grid is the foundation; this tool exists to ground and correct it.
//
// The global pass picks one tempo for the whole song, so it mis-tracks sections
// at a different tempo/feel. So you can SELECT a section and rework just its grid:
// re-track it with its own tempo controls, tap a tempo in time with the music, or
// mark beat 1 — then re-run the algo SEEDED by that suggestion. The section's new
// beats are spliced back into the global grid; the rest of the song is untouched.
import * as THREE from 'three';

const $ = (id) => document.getElementById(id);
const el = {
  songinfo:$('songinfo'), bpmOut:$('bpmOut'), beatsOut:$('beatsOut'), barsOut:$('barsOut'),
  tempo_mult:$('tempo_mult'), tempo_hint:$('tempo_hint'), hintOut:$('hintOut'),
  beats_per_bar:$('beats_per_bar'), phaseShift:$('phaseShift'), reanalyze:$('reanalyze'),
  sectionCount:$('sectionCount'), sectionList:$('sectionList'), diag:$('diag'),
  highway:$('highway'), play:$('play'), click:$('click'), clock:$('clock'), status:$('status'),
  tl:$('tl'),
  // per-section rework panel
  sectionPanel:$('sectionPanel'), secTarget:$('secTarget'), secBpmOut:$('secBpmOut'), secBeatsOut:$('secBeatsOut'),
  sec_tempo_mult:$('sec_tempo_mult'), sec_tempo_hint:$('sec_tempo_hint'), secHintOut:$('secHintOut'),
  sec_beats_per_bar:$('sec_beats_per_bar'), secTap:$('secTap'), secAnchor:$('secAnchor'), secSeed:$('secSeed'),
  secPhaseShift:$('secPhaseShift'), secReanalyze:$('secReanalyze'), secReset:$('secReset'),
  secSplit:$('secSplit'), secMerge:$('secMerge'), secLock:$('secLock'), secLockHint:$('secLockHint'),
};

// section palette by label letter
const SECT_COLORS = ['#3a82f6','#33c66b','#f2c83f','#e6549a','#ff8c2e','#9b6cf2','#37d6d0','#e6394a'];
const sectColor = (label) => SECT_COLORS[(label.charCodeAt(0) - 65) % SECT_COLORS.length];

let base = null;                 // last GLOBAL analysis payload (the foundation)
let data = null;                 // composed grid (base + per-section overrides) — what renders
const regions = new Map();       // sectionKey -> {start,end,beats,downbeats,bpm,phase,knobs}
let selected = null;             // {key,start,end,label,mult,hint,bpb,phase,anchor,taps[]}
let _downset = new Set();        // rounded-ms downbeat times of the COMPOSED grid (strong clicks)
let duration = 0;
let phase = 0, bpb = 4;          // global downbeat phase / beats-per-bar (section defaults)

const secKey = (s) => `${s.start}|${s.end}`;
const sectionAt = (t) => (data?.sections || []).find(s => t >= s.start && t < s.end) || null;

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

  // section-colored board segments (selected = brighter, overridden = mid)
  for (const s of d.sections) {
    const key = secKey(s);
    const isSel = selected && selected.key === key;
    const opacity = isSel ? 0.28 : (regions.has(key) ? 0.17 : 0.10);
    const len = (s.end - s.start) * SPEED;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(BOARD_W, Math.max(0.01, len)),
      new THREE.MeshBasicMaterial({ color:new THREE.Color(sectColor(s.label)), transparent:true, opacity }));
    m.rotation.x = -Math.PI / 2;
    m.position.set(0, 0.005, STRIKE_Z - (s.start + s.end) / 2 * SPEED);
    m.userData.span = [s.start, s.end]; gridGroup.add(m);
  }
  for (const t of d.beats) {
    const down = _downset.has(Math.round(t * 1000));
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
  // metronome: fire clicks for beats we just crossed (strong on composed downbeats)
  if (data && !audio.paused) {
    while (beatCursor < data.beats.length && data.beats[beatCursor] <= c) {
      const t = data.beats[beatCursor];
      if (c - t < 0.2) click(_downset.has(Math.round(t * 1000)));
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
// section-boundary editing state. `boundaries` is a per-frame hit-map [{x,t,i}] of every
// INTERNAL section start (the shared seam between sections[i-1] and sections[i]); rebuilt
// each draw so geometry is never stale. hot = under cursor, focused = keyboard target.
let boundaries = [], hotBoundary = null, focusedBoundary = null, boundaryDrag = null;
function drawTimeline(playT) {
  if (!data || !tlW) return;
  const ctx = ctx2d;
  ctx.clearRect(0, 0, tlW, tlH);
  const waveTop = SECT_H, waveBot = tlH - TEMPO_H, waveH = waveBot - waveTop, mid = (waveTop + waveBot) / 2;

  // sections band (overridden = accent left-bar). Every internal start is a draggable boundary.
  boundaries = [];
  data.sections.forEach((s, idx) => {
    const x0 = tToX(s.start), x1 = tToX(s.end);
    if (idx > 0) boundaries.push({ x: x0, t: s.start, i: idx });
    if (x1 < 0 || x0 > tlW) return;
    ctx.fillStyle = sectColor(s.label) + '33';
    ctx.fillRect(x0, 0, x1 - x0, SECT_H);
    ctx.fillStyle = regions.has(secKey(s)) ? '#37e0a6' : sectColor(s.label);
    ctx.fillRect(x0, 0, 2, SECT_H);
    ctx.fillStyle = '#e7ecf5'; ctx.font = '11px ui-sans-serif'; ctx.textBaseline = 'middle';
    if (x1 - x0 > 16) ctx.fillText(s.label, x0 + 6, SECT_H / 2);
  });
  // boundary handles: focused (dim) then hot/dragging (bright) so the active one wins
  const hb = boundaryDrag ? boundaryDrag.i : hotBoundary;
  for (const b of [focusedBoundary, hb]) {
    if (b == null || b <= 0 || b >= data.sections.length) continue;
    const x = tToX(data.sections[b].start);
    ctx.fillStyle = b === hb ? '#bcd2ff' : 'rgba(188,210,255,0.5)';
    ctx.fillRect(x - 1.5, 0, 3, SECT_H);
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
  const spacingOk = (view.end - view.start) / tlW < 0.06;  // hide beat ticks when too dense
  let bar = 0;
  for (const t of data.beats) {
    const x = tToX(t); if (x < -2 || x > tlW + 2) { continue; }
    const down = _downset.has(Math.round(t * 1000));
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

  // selected-region highlight + beat-1 anchor (overlay, under the playhead)
  if (selected) {
    const x0 = tToX(selected.start), x1 = tToX(selected.end);
    ctx.fillStyle = 'rgba(91,157,255,0.10)';
    ctx.fillRect(x0, 0, x1 - x0, tlH);
    ctx.strokeStyle = 'rgba(91,157,255,0.7)'; ctx.lineWidth = 1;
    ctx.strokeRect(x0 + 0.5, 0.5, Math.max(1, x1 - x0 - 1), tlH - 1);
    if (selected.anchor != null) {
      const ax = tToX(selected.anchor);
      ctx.strokeStyle = '#37e0a6'; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(ax, 0); ctx.lineTo(ax, tlH); ctx.stroke();
      ctx.fillStyle = '#37e0a6'; ctx.font = 'bold 10px ui-monospace'; ctx.textBaseline = 'top';
      ctx.fillText('1', ax + 3, 2);
    }
  }

  // playhead
  const px = tToX(playT);
  if (px >= 0 && px <= tlW) {
    ctx.strokeStyle = '#bcd2ff'; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, tlH); ctx.stroke();
  }
}

// Timeline interactions. In the section band (top ~28px): hover a boundary → col-resize
// cursor + bright handle; drag it to move the seam (snaps to a beat, Alt = free); double-click
// a section to split; right-click a boundary to merge; click a section body to select it.
// Below the band: click seeks, drag pans, wheel zooms.
const BAND = SECT_H + 4;
const boundaryAt = (x, y) => {
  if (y > BAND) return null;
  let hit = null;
  for (const b of boundaries) {
    const d = Math.abs(b.x - x);
    if (d <= 8 && (!hit || d < Math.abs(hit.x - x))) hit = b;
  }
  return hit;
};
let dragging = false, dragX = 0, dragY = 0, dragStart = null, moved = false;

tl.addEventListener('pointermove', (e) => {        // hover affordance (when no drag is active)
  if (dragging || boundaryDrag) return;
  const hit = boundaryAt(e.offsetX, e.offsetY);
  hotBoundary = hit ? hit.i : null;
  tl.style.cursor = hotBoundary != null ? 'col-resize' : (e.offsetY <= BAND ? 'pointer' : 'text');
});
tl.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;                       // only the primary button drags/pans; right-click → contextmenu
  dragX = e.offsetX; dragY = e.offsetY; moved = false;
  const hit = boundaryAt(e.offsetX, e.offsetY);
  if (hit) { boundaryDrag = { i: hit.i, moved: false, selSide: selSideOf(hit.i) }; return; }   // grab a boundary, not a pan
  dragging = true; dragStart = { ...view };
});
window.addEventListener('pointermove', (e) => {
  if (boundaryDrag) {
    const x = e.clientX - tl.getBoundingClientRect().left;
    if (Math.abs(x - dragX) > 3) boundaryDrag.moved = true;
    const raw = xToT(x);
    updateBoundary(boundaryDrag.i, e.altKey ? raw : snapToBeat(raw), false);   // live preview
    const L = data.sections[boundaryDrag.i - 1], R = data.sections[boundaryDrag.i];
    status(`${L.label}|${R.label} → ${fmt(L.end)} · ${(L.end - L.start).toFixed(0)}s | ${(R.end - R.start).toFixed(0)}s`, 'busy');
    return;
  }
  if (!dragging) return;
  const dx = e.offsetX - dragX; if (Math.abs(dx) > 3) moved = true;
  const span = dragStart.end - dragStart.start, dt = -dx / tlW * span;
  let s = dragStart.start + dt, en = dragStart.end + dt;
  if (s < 0) { en -= s; s = 0; } if (en > duration) { s -= en - duration; en = duration; }
  view = { start:Math.max(0, s), end:Math.min(duration, en) };
});
window.addEventListener('pointerup', () => {
  if (boundaryDrag) {
    const i = boundaryDrag.i;
    if (boundaryDrag.moved) { updateBoundary(i, data.sections[i].start, true); refreshSelection(i, boundaryDrag.selSide); }
    else { focusedBoundary = i; status(`boundary ${data.sections[i - 1].label}|${data.sections[i].label} selected — ←/→ nudge · ⌫ merge`); }
    boundaryDrag = null;
    return;
  }
  if (dragging && !moved) {
    const t = xToT(dragX);
    if (dragY <= BAND) { const s = sectionAt(t); if (s) selectSection(s); else seek(t); }
    else seek(t);
  }
  dragging = false;
});
// right-click context menu on the section bar: Split / Merge / Rename, depending on what's under it
const ctxEl = document.getElementById('ctxmenu');
function hideCtx() { ctxEl.hidden = true; ctxEl.innerHTML = ''; }
function showCtx(clientX, clientY, items) {
  ctxEl.innerHTML = '';
  for (const it of items) {
    const b = document.createElement('button');
    b.className = 'ctxitem' + (it.danger ? ' danger' : '');
    b.textContent = it.label;
    b.addEventListener('click', () => { hideCtx(); it.run(); });
    ctxEl.appendChild(b);
  }
  ctxEl.hidden = false;
  const w = ctxEl.offsetWidth, h = ctxEl.offsetHeight;   // clamp into the viewport
  ctxEl.style.left = Math.max(6, Math.min(clientX, window.innerWidth - w - 6)) + 'px';
  ctxEl.style.top = Math.max(6, Math.min(clientY, window.innerHeight - h - 6)) + 'px';
}
tl.addEventListener('contextmenu', (e) => {
  if (e.offsetY > BAND) return;            // only the section band; elsewhere keep the native menu
  e.preventDefault();
  const hit = boundaryAt(e.offsetX, e.offsetY);
  if (hit) {
    const L = data.sections[hit.i - 1], R = data.sections[hit.i];
    showCtx(e.clientX, e.clientY, [{ label: `⤺  Merge ${L.label} + ${R.label}`, run: () => mergeBoundary(hit.i), danger: true }]);
  } else {
    const t = snapToBeat(xToT(e.offsetX));
    const sec = sectionAt(t);
    if (!sec) return;
    showCtx(e.clientX, e.clientY, [
      { label: `✂  Split here  (${fmt(t)})`, run: () => splitAtTime(t) },
      { label: `✎  Rename ${sec.label}…`, run: () => renameSection(sec) },
    ]);
  }
});
document.addEventListener('pointerdown', (e) => { if (!ctxEl.hidden && !ctxEl.contains(e.target)) hideCtx(); });
window.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideCtx(); }, true);
window.addEventListener('blur', hideCtx);
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
//  Grid composition — base global grid spliced with per-section overrides
// ============================================================================
function tempoCurveFrom(beats) {
  if (beats.length < 2) return { curve: [], median: null };
  const curve = [], bpms = [];
  for (let i = 1; i < beats.length; i++) {
    const dt = beats[i] - beats[i - 1];
    let v = dt > 1e-3 ? 60 / dt : 400;
    v = Math.min(400, Math.max(30, v));
    curve.push({ t: +beats[i].toFixed(3), bpm: +v.toFixed(1) });
    bpms.push(v);
  }
  bpms.sort((a, b) => a - b);
  const m = bpms.length >> 1;
  const median = bpms.length % 2 ? bpms[m] : (bpms[m - 1] + bpms[m]) / 2;
  return { curve, median: +median.toFixed(1) };
}

function composeGrid() {
  if (!base) return;
  const ovs = [...regions.values()].sort((a, b) => a.start - b.start);
  // half-open [start, end) — MUST match analyze_window's mask so splice has no dup/gap at seams
  const covered = (t) => ovs.some(o => t >= o.start - 1e-6 && t < o.end);
  let beats = base.beats.filter(t => !covered(t));
  let downbeats = base.downbeats.filter(t => !covered(t));
  for (const o of ovs) { beats = beats.concat(o.beats); downbeats = downbeats.concat(o.downbeats); }
  beats.sort((x, y) => x - y); downbeats.sort((x, y) => x - y);
  const tc = tempoCurveFrom(beats);
  data = {
    ...base,
    beats, downbeats,
    tempoCurve: tc.curve,
    bpm: tc.median != null ? tc.median : base.bpm,
    analysis: { ...base.analysis, beats: beats.length, downbeats: downbeats.length },
  };
  _downset = new Set(downbeats.map(t => Math.round(t * 1000)));
}

// ============================================================================
//  Section selection + rework (the per-section tempo/beat correction loop)
// ============================================================================
function selectSection(s) {
  focusedBoundary = null;          // selecting a section body clears any boundary keyboard focus
  const key = secKey(s);
  const ov = regions.get(key);
  selected = {
    key, start: s.start, end: s.end, label: s.label,
    mult: ov?.knobs.mult ?? 1,
    hint: ov?.knobs.hint ?? 0,
    bpb: ov?.knobs.bpb ?? bpb,
    phase: ov?.knobs.phase ?? null,
    anchor: ov?.knobs.anchor ?? null,
    taps: [],
  };
  syncSectionPanel();
  renderSectionList();
  buildHighway(data);
  // bring the section into view + park the playhead at its start
  if (selected.start < view.start || selected.end > view.end) {
    const pad = (selected.end - selected.start) * 0.15;
    view = { start: Math.max(0, selected.start - pad), end: Math.min(duration, selected.end + pad) };
  }
  seek(s.start);
}

function tappedBpm() {
  const t = selected?.taps || [];
  if (t.length < 2) return 0;
  const diffs = [];
  for (let i = 1; i < t.length; i++) diffs.push(t[i] - t[i - 1]);
  diffs.sort((a, b) => a - b);
  const m = diffs.length >> 1;
  const med = diffs.length % 2 ? diffs[m] : (diffs[m - 1] + diffs[m]) / 2;
  return med > 0 ? Math.round(60 / med) : 0;
}

function updateSeedHint() {
  const t = selected?.taps || [];
  const parts = [];
  if (t.length >= 2 && tappedBpm() > 0) parts.push(`tapped <b>${tappedBpm()} BPM</b> · ${t.length} taps`);
  if (selected?.anchor != null) parts.push(`beat&nbsp;1 @ ${fmt(selected.anchor)}`);
  el.secSeed.innerHTML = parts.length
    ? '🎯 ' + parts.join(' · ') + ' — <b>Re-track</b> (detect) or <b>Lock</b> (use as-is)'
    : '▶ Play, then tap <b>T</b> in time with this section — that tempo seeds the re-track. <b>B</b> marks beat 1.';
  el.secTap.classList.toggle('armed', t.length >= 2 && tappedBpm() > 0);
  el.secAnchor.classList.toggle('armed', selected?.anchor != null);
  // the lock button needs a tempo (a tap or the hint slider) to build a grid from
  const hasTempo = !!(selected && selected.hint > 0);
  el.secLock.hidden = !hasTempo;
  el.secLockHint.hidden = !hasTempo;
  if (hasTempo) el.secLock.textContent = `🔒 Lock to ${selected.hint} BPM`;
}

function syncSectionPanel() {
  if (!selected) { el.sectionPanel.hidden = true; return; }
  el.sectionPanel.hidden = false;
  el.secTarget.textContent = `${selected.label} · ${fmt(selected.start)}–${fmt(selected.end)}`;
  el.sec_tempo_mult.value = String(selected.mult);
  el.sec_tempo_hint.value = String(selected.hint || 0);
  el.secHintOut.textContent = selected.hint > 0 ? selected.hint : 'auto';
  el.sec_beats_per_bar.value = String(selected.bpb);
  const ov = regions.get(selected.key);
  el.secReset.hidden = !ov;
  el.secBpmOut.textContent = (ov && ov.bpm != null) ? ov.bpm : '—';
  el.secBeatsOut.textContent = ov ? ov.beats.length : '—';
  const i = baseSectionIndex();
  el.secMerge.disabled = !(i >= 0 && i < base.sections.length - 1);
  updateSeedHint();
}

function flash(b) { b.classList.add('tapping'); setTimeout(() => b.classList.remove('tapping'), 130); }

function tap() {
  if (!selected) return;
  const now = audio.currentTime || 0;
  const t = selected.taps;
  if (t.length) {
    const dt = now - t[t.length - 1];
    if (dt > 2.5) t.length = 0;        // long gap ⇒ start a fresh run
    else if (dt < 0.01) return;        // audio paused / key-repeat ⇒ no usable interval, ignore
  }
  t.push(now);
  if (t.length > 8) t.shift();
  if (selected.anchor == null) selected.anchor = t[0];         // first tap also anchors beat 1
  const bpm = tappedBpm();
  if (bpm > 0) { selected.hint = bpm; el.sec_tempo_hint.value = String(bpm); el.secHintOut.textContent = bpm; }
  updateSeedHint();
  flash(el.secTap);
  click(true);
}

function markAnchor() {
  if (!selected) return;
  selected.anchor = audio.currentTime || selected.start;
  selected.phase = null;   // an explicit anchor supersedes a phase index
  updateSeedHint();
  flash(el.secAnchor);
}

async function analyzeRegion(lock = false) {
  if (!selected) return;
  if (lock && !(selected.hint > 0)) {   // lock needs a tempo — tap or set the hint first
    el.status.textContent = 'tap a tempo (T) or set the hint before locking';
    el.status.className = 'status err';
    return;
  }
  if (busy) { pending = { kind: 'region', lock }; return; }
  busy = true;
  el.status.textContent = lock ? 'locking section…' : 'tracking section…'; el.status.className = 'status busy';
  const s = selected;
  const p = new URLSearchParams({ start: String(s.start), end: String(s.end),
    tempo_mult: String(s.mult), beats_per_bar: String(s.bpb) });
  if (s.hint > 0) p.set('tempo_hint', String(s.hint));
  if (s.anchor != null) p.set('anchor', String(s.anchor));
  else if (s.phase != null) p.set('phase', String(s.phase));
  if (lock) p.set('lock', '1');
  try {
    const r = await fetch('/api/analyze_region?' + p.toString());
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
    // overrides must never overlap, or composeGrid would double-count the seam
    for (const [k, o] of [...regions]) {
      if (k !== s.key && o.start < d.end && o.end > d.start) regions.delete(k);
    }
    regions.set(s.key, {
      start: d.start, end: d.end, beats: d.beats, downbeats: d.downbeats, bpm: d.bpm,
      phase: d.phase, locked: !!d.locked,
      knobs: { mult: s.mult, hint: s.hint, bpb: s.bpb, phase: d.phase, anchor: s.anchor, lock },
    });
    selected.phase = d.phase;
    composeGrid(); renderAll(data); syncSectionPanel();
    el.status.textContent = `${d.locked ? '🔒 locked' : 'section'} ${s.label}: ${d.analysis.beats} beats · ${d.bpm ?? '—'} BPM`;
    el.status.className = 'status';
  } catch (e) {
    el.status.textContent = 'error: ' + e.message; el.status.className = 'status err';
  } finally { busy = false; runPending(); }
}

function resetRegion() {
  if (!selected) return;
  regions.delete(selected.key);
  Object.assign(selected, { mult: 1, hint: 0, bpb, phase: null, anchor: null, taps: [] });
  composeGrid(); renderAll(data); syncSectionPanel();
}

// ----- section boundary editing --------------------------------------------------
// base.sections is strictly contiguous & half-open (sections[i-1].end === sections[i].start),
// and composeGrid()'s covered() seams rely on that. So every internal start is ONE boundary
// shared by two sections; editing it sets both sides atomically → overlaps/gaps are impossible.
// Three primitives: split (insert a boundary), move (drag it), merge (delete it). Any override
// (tuned per-section grid) on a touched span is dropped, since its span no longer matches.
const snapToBeat = (t) => {
  if (!data || !data.beats.length) return t;
  let best = data.beats[0], bd = Infinity;
  for (const b of data.beats) { const d = Math.abs(b - t); if (d < bd) { bd = d; best = b; } }
  return best;
};
const stepBeat = (t, dir) => {        // nearest beat strictly past `t` in direction dir (±1)
  if (!data || !data.beats.length) return t + dir * 0.1;
  if (dir > 0) { for (const b of data.beats) if (b > t + 1e-4) return b; return t; }
  let prev = t; for (const b of data.beats) { if (b < t - 1e-4) prev = b; else break; } return prev;
};
const baseSectionIndex = () =>
  base ? base.sections.findIndex(s => secKey(s) === selected?.key) : -1;
const status = (msg, kind = '') => { el.status.textContent = msg; el.status.className = 'status' + (kind ? ' ' + kind : ''); };
const dropOverride = (sec) => regions.delete(secKey(sec));   // returns true if one existed

function splitAtTime(t) {              // insert a boundary at t (snapped); split the section there
  if (!base) return;
  t = +(+t).toFixed(3);
  const i = base.sections.findIndex(s => t > s.start && t < s.end);
  if (i < 0) return;
  const sec = base.sections[i];
  if (t - sec.start < 0.25 || sec.end - t < 0.25) { status('too close to a boundary — split nearer the middle', 'err'); return; }
  const had = dropOverride(sec);
  base.sections.splice(i, 1, { ...sec, end: t }, { ...sec, start: t });
  composeGrid(); renderAll(data);
  selectSection(base.sections[i]);     // land on the first half, ready to rework
  focusedBoundary = i + 1;             // the new seam (set after selectSection clears it)
  status(`split ${sec.label} at ${fmt(t)}${had ? ' — re-track cleared' : ''}`);
}

function mergeBoundary(i) {             // delete boundary i: merge sections[i-1] and sections[i]
  if (!base || i <= 0 || i >= base.sections.length) { status('nothing to merge there', 'err'); return; }
  const a = base.sections[i - 1], b = base.sections[i];
  const had = dropOverride(a) | dropOverride(b);
  base.sections.splice(i - 1, 2, { ...a, end: b.end });
  focusedBoundary = null;
  composeGrid(); renderAll(data);
  selectSection(base.sections[i - 1]);
  status(`merged into ${a.label} (${fmt(a.start)}–${fmt(b.end)})${had ? ' — re-track cleared' : ''}`);
}

function renameSection(sec) {           // free-text label (used for color + display; not the grid)
  const name = (prompt('Section name', sec.label) || '').trim();
  if (!name || name === sec.label) return;
  if (selected && selected.key === secKey(sec)) selected.label = name;   // key is span-based, unaffected
  sec.label = name;
  renderAll(data);
  status(`renamed → ${name}`);
}

// Is the rework selection on the left/right of boundary i? MUST be called BEFORE the boundary
// moves (a live drag mutates the section keys every frame, so this can't be deferred to commit).
const selSideOf = (i) => (!selected || !base || i <= 0 || i >= base.sections.length) ? null
  : (selected.key === secKey(base.sections[i - 1]) ? 'left' : (selected.key === secKey(base.sections[i]) ? 'right' : null));
// After boundary i moved, re-point `selected` at its (now-resized) section so key/start/end stay
// valid — else the highlight, panel, and any later tap/anchor/re-track act on a stale span.
function refreshSelection(i, side) {
  if (!side || !selected) return;
  const sec = base.sections[side === 'left' ? i - 1 : i];
  selected.start = sec.start; selected.end = sec.end; selected.key = secKey(sec);
  // updateBoundary already re-rendered with the OLD key, so refresh the list + highway too
  syncSectionPanel(); renderSectionList(); buildHighway(data);
}

// move shared boundary i to time t. commit=false = live drag preview (rects only, no recompute).
function updateBoundary(i, t, commit) {
  if (!base || i <= 0 || i >= base.sections.length) return;
  const left = base.sections[i - 1], right = base.sections[i];
  t = +Math.max(left.start + 0.25, Math.min(right.end - 0.25, t)).toFixed(3);
  if (commit) { dropOverride(left); dropOverride(right); }
  left.end = t; right.start = t;
  if (commit) { composeGrid(); renderAll(data); status(`boundary → ${fmt(t)} · ${(t - left.start).toFixed(0)}s | ${(right.end - t).toFixed(0)}s`); }
}

// rework-panel button/key wrappers (split the SELECTED section at the playhead; merge with next)
function splitSection() {
  const i = baseSectionIndex();
  if (i < 0) return;
  const sec = base.sections[i];
  const t = snapToBeat(audio.currentTime || (sec.start + sec.end) / 2);
  if (t <= sec.start || t >= sec.end) { status('move the playhead inside this section, then split', 'err'); return; }
  splitAtTime(t);
}
function mergeSection() {
  const i = baseSectionIndex();
  if (i < 0 || i >= base.sections.length - 1) { status('no section after this one to merge', 'err'); return; }
  mergeBoundary(i + 1);
}

// ============================================================================
//  Global analyze + render
// ============================================================================
// One request in flight at a time. A request made while busy is remembered as the
// latest pending intent (not silently dropped) and run when the in-flight one ends;
// knobs mutate `selected`/the DOM, so the coalesced re-run reads the newest values.
let busy = false, pending = null;   // pending: {kind:'global'} | {kind:'region', lock} | null
function runPending() {
  const p = pending; pending = null;
  if (!p) return;
  if (p.kind === 'global') analyze();
  else if (p.kind === 'region') analyzeRegion(p.lock);
}

async function analyze() {
  if (busy) { pending = { kind: 'global' }; return; }
  busy = true;
  el.status.textContent = 'analyzing…'; el.status.className = 'status busy';
  const p = new URLSearchParams({
    tempo_mult: el.tempo_mult.value, beats_per_bar: el.beats_per_bar.value, phase: String(phase),
  });
  if (+el.tempo_hint.value > 0) p.set('tempo_hint', el.tempo_hint.value);
  try {
    const r = await fetch('/api/analyze?' + p.toString());
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || ('HTTP ' + r.status));
    base = d; bpb = d.beatsPerBar; phase = d.phase;
    regions.clear(); selected = null; focusedBoundary = null; hotBoundary = null; syncSectionPanel();   // a new global grid retires old overrides
    composeGrid(); renderAll(data);
    el.status.textContent = `${data.analysis.beats} beats · ${d.analysis.sections} sections`;
    el.status.className = 'status';
  } catch (e) {
    el.status.textContent = 'error: ' + e.message; el.status.className = 'status err';
  } finally { busy = false; runPending(); }
}

function renderSectionList() {
  el.sectionList.innerHTML = '';
  (data?.sections || []).forEach((s) => {
    const key = secKey(s), ov = regions.get(key);
    const row = document.createElement('div');
    row.className = 'sectionRow' + (selected && selected.key === key ? ' active' : '');
    row.innerHTML = `<span class="swatch" style="background:${sectColor(s.label)}"></span>` +
      `<span class="lab">${s.label}</span><span>${fmt(s.start)}</span>` +
      (ov ? `<span class="badge">${ov.locked ? '🔒' : ''}${ov.bpm ?? '–'}bpm</span>` : '') +
      `<span class="tm">${(s.end - s.start).toFixed(0)}s</span>`;
    row.onclick = () => selectSection(s);
    el.sectionList.appendChild(row);
  });
}

function renderAll(d) {
  if (view.end <= view.start || view.end > duration + 0.5) view = { start:0, end:duration };
  el.bpmOut.textContent = d.bpm; el.beatsOut.textContent = d.analysis.beats; el.barsOut.textContent = d.analysis.downbeats;
  el.sectionCount.textContent = `${d.sections.length} found`;
  renderSectionList();
  const nOv = regions.size;
  el.diag.textContent = `raw ${base.analysis.rawBpm} → ${d.bpm} bpm (×${base.tempoMult})\n` +
    `${base.beatsPerBar}/4 · ${nOv} section override${nOv === 1 ? '' : 's'} · drift ${tempoRange(d)}`;
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

function togglePlay() { if (audio.paused) audio.play(); else audio.pause(); }

// global grid controls
el.tempo_mult.addEventListener('change', analyze);
el.beats_per_bar.addEventListener('change', () => { phase = 0; analyze(); });
el.tempo_hint.addEventListener('input', () => { el.hintOut.textContent = +el.tempo_hint.value > 0 ? el.tempo_hint.value : 'auto'; });
el.tempo_hint.addEventListener('change', analyze);
el.phaseShift.addEventListener('click', () => { phase = (phase + 1) % bpb; analyze(); });
el.reanalyze.addEventListener('click', analyze);

// per-section rework controls (auto-retrack on a knob change; tap/anchor wait for a button).
// A locked section stays locked when you nudge mult/bpb/hint — those feed the lock too.
const keepMode = () => (selected && regions.get(selected.key)?.locked) || false;
el.sec_tempo_mult.addEventListener('change', () => { if (selected) { selected.mult = +el.sec_tempo_mult.value; analyzeRegion(keepMode()); } });
el.sec_beats_per_bar.addEventListener('change', () => { if (selected) { selected.bpb = +el.sec_beats_per_bar.value; selected.phase = null; analyzeRegion(keepMode()); } });
el.sec_tempo_hint.addEventListener('input', () => {
  el.secHintOut.textContent = +el.sec_tempo_hint.value > 0 ? el.sec_tempo_hint.value : 'auto';
  if (selected) { selected.hint = +el.sec_tempo_hint.value; updateSeedHint(); }   // reveal Lock live
});
el.sec_tempo_hint.addEventListener('change', () => { if (selected) { selected.hint = +el.sec_tempo_hint.value; analyzeRegion(keepMode()); } });
el.secPhaseShift.addEventListener('click', () => {
  if (!selected) return;
  selected.anchor = null;
  selected.phase = (((selected.phase ?? 0) + 1) % selected.bpb);
  analyzeRegion(false);
});
el.secTap.addEventListener('click', tap);
el.secAnchor.addEventListener('click', markAnchor);
el.secReanalyze.addEventListener('click', () => analyzeRegion(false));
el.secLock.addEventListener('click', () => analyzeRegion(true));
el.secSplit.addEventListener('click', splitSection);
el.secMerge.addEventListener('click', mergeSection);
el.secReset.addEventListener('click', resetRegion);

el.play.addEventListener('click', togglePlay);
window.addEventListener('resize', () => { resizeHighway(); resizeTimeline(); });
window.addEventListener('keydown', (e) => {
  if (e.repeat) return;   // ignore key auto-repeat (would spam taps / toggles)
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (e.key === 't' || e.key === 'T') { if (selected) { e.preventDefault(); tap(); } }
  else if (e.key === 'b' || e.key === 'B') { if (selected) { e.preventDefault(); markAnchor(); } }
  else if (e.key === 's' || e.key === 'S') { if (selected) { e.preventDefault(); splitSection(); } }   // split selected at playhead
  else if (e.key === 'Delete' || e.key === 'Backspace') {                                                // merge across a boundary
    e.preventDefault();
    if (focusedBoundary != null) mergeBoundary(focusedBoundary);
    else if (selected) { const i = baseSectionIndex(); if (i >= 0 && i < base.sections.length - 1) mergeBoundary(i + 1); else status('no section after this one to merge', 'err'); }  // merge forward — matches ⤺ Merge next
  } else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && focusedBoundary != null) {              // nudge focused boundary
    e.preventDefault();
    const dir = e.key === 'ArrowRight' ? 1 : -1;
    const cur = base.sections[focusedBoundary].start;
    const side = selSideOf(focusedBoundary);
    updateBoundary(focusedBoundary, e.shiftKey ? cur + dir * 0.02 : stepBeat(cur, dir), true);
    refreshSelection(focusedBoundary, side);
  }
});

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
