// charter studio — Clone Hero-style drum highway previewer.
// Renders the auto-charted notes scrolling toward a strikeline, in sync with the
// clip audio, plus an audible drum overlay so you can judge "does it match" by
// ear. The Three.js scene here maps 1:1 onto React-Three-Fiber for the future
// OCTAVE-style editor.
import * as THREE from 'three';

// ---- layout constants -------------------------------------------------------
const LANES = ['red', 'yellow', 'blue', 'green'];
const COL = { red:0xe6394a, yellow:0xf2c83f, blue:0x3a82f6, green:0x33c66b, kick:0xff8c2e };
const LANE_W = 1.05;
const BOARD_W = LANE_W * 4;
const SPEED = 7.0;            // world units per second of scroll
const STRIKE_Z = 3.5;        // where notes are "hit" (near the camera)
const LOOKAHEAD = 2.6;       // seconds of chart visible ahead of the strike
const FAR_Z = STRIKE_Z - LOOKAHEAD * SPEED;
const laneX = (i) => (i - 1.5) * LANE_W;

// ---- dom --------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const el = {
  panel:$('panel'), highway:$('highway'), songinfo:$('songinfo'), diag:$('diag'),
  start:$('start'), startOut:$('startOut'), length:$('length'), lenOut:$('lenOut'),
  shuffle:$('shuffle'), engine:$('engine'), engineHint:$('engineHint'),
  baselineGroup:$('baselineGroup'), genre:$('genre'), separation:$('separation'),
  subdivisions:$('subdivisions'), dynamics:$('dynamics'), double_kick:$('double_kick'),
  tom_split:$('tom_split'), repreview:$('repreview'), play:$('play'), overlay:$('overlay'),
  clock:$('clock'), status:$('status'),
  // tuning sliders — referenced as el[k] in the SLIDERS loop, so they MUST be here
  onset_delta:$('onset_delta'), kick_low_ratio:$('kick_low_ratio'),
  snare_mid_ratio:$('snare_mid_ratio'), hat_vhigh_ratio:$('hat_vhigh_ratio'),
};
const SLIDERS = ['onset_delta', 'kick_low_ratio', 'snare_mid_ratio', 'hat_vhigh_ratio'];
const SLIDER_OUT = { onset_delta:'onsetOut', kick_low_ratio:'kickOut', snare_mid_ratio:'snareOut', hat_vhigh_ratio:'hatOut' };

// ---- state ------------------------------------------------------------------
let duration = 0;            // full song length (s)
let settings = null;         // server-resolved settings (source of truth)
let preview = null;          // last preview payload
let noteGroup = null;        // scrolling group of note + beat meshes
const targets = [];          // strike-line lane pads (for hit flashes)
let kickTarget = null;

// ============================================================================
//  THREE.js scene
// ============================================================================
const renderer = new THREE.WebGLRenderer({ antialias:true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
el.highway.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0c0e14);
scene.fog = new THREE.Fog(0x0c0e14, Math.abs(FAR_Z) * 0.45, Math.abs(FAR_Z) + 6);

const camera = new THREE.PerspectiveCamera(52, 1, 0.1, 200);
camera.position.set(0, 4.7, STRIKE_Z + 4.3);
camera.lookAt(0, 0, STRIKE_Z - 8.5);

scene.add(new THREE.AmbientLight(0x9fb4e0, 0.65));
const key = new THREE.DirectionalLight(0xffffff, 1.0);
key.position.set(-4, 9, 6); scene.add(key);

// board + faint lane tints + side rails
const boardLen = STRIKE_Z - FAR_Z + 3;
const boardCz = (STRIKE_Z + FAR_Z) / 2 - 1;
const board = new THREE.Mesh(
  new THREE.PlaneGeometry(BOARD_W, boardLen),
  new THREE.MeshStandardMaterial({ color:0x10141f, roughness:0.95 }));
board.rotation.x = -Math.PI / 2; board.position.set(0, 0, boardCz); scene.add(board);

for (let i = 0; i < 4; i++) {
  const tint = new THREE.Mesh(
    new THREE.PlaneGeometry(LANE_W * 0.94, boardLen),
    new THREE.MeshBasicMaterial({ color:COL[LANES[i]], transparent:true, opacity:0.07 }));
  tint.rotation.x = -Math.PI / 2; tint.position.set(laneX(i), 0.005, boardCz); scene.add(tint);
}
for (let i = 0; i <= 4; i++) {            // lane separators
  const ln = new THREE.Mesh(
    new THREE.PlaneGeometry(0.03, boardLen),
    new THREE.MeshBasicMaterial({ color:0x2a3346 }));
  ln.rotation.x = -Math.PI / 2; ln.position.set((i - 2) * LANE_W, 0.01, boardCz); scene.add(ln);
}

// strikeline + lane target pads + kick target bar
const strike = new THREE.Mesh(
  new THREE.BoxGeometry(BOARD_W + 0.1, 0.06, 0.16),
  new THREE.MeshStandardMaterial({ color:0xeef3ff, emissive:0xbcd2ff, emissiveIntensity:0.7 }));
strike.position.set(0, 0.04, STRIKE_Z); scene.add(strike);

for (let i = 0; i < 4; i++) {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.30, 0.46, 28),
    new THREE.MeshStandardMaterial({ color:COL[LANES[i]], emissive:COL[LANES[i]],
      emissiveIntensity:0.25, side:THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.set(laneX(i), 0.03, STRIKE_Z);
  scene.add(ring); targets.push({ mesh:ring, flash:0 });
}
kickTarget = new THREE.Mesh(
  new THREE.BoxGeometry(BOARD_W, 0.05, 0.12),
  new THREE.MeshStandardMaterial({ color:COL.kick, emissive:COL.kick, emissiveIntensity:0.18 }));
kickTarget.position.set(0, 0.015, STRIKE_Z + 0.16); scene.add(kickTarget);
kickTarget.userData.flash = 0;

// shared geometries
const GEO = {
  tom: new THREE.BoxGeometry(0.82, 0.34, 0.40),
  cym: new THREE.CylinderGeometry(0.46, 0.46, 0.13, 24),
  kick: new THREE.BoxGeometry(BOARD_W * 0.98, 0.16, 0.30),
  beat: new THREE.PlaneGeometry(BOARD_W, 0.04),
};

function laneIndex(lane) { return LANES.indexOf(lane); }

function buildScene(p) {
  if (noteGroup) { scene.remove(noteGroup); disposeGroup(noteGroup); }
  noteGroup = new THREE.Group(); scene.add(noteGroup);

  // beat / downbeat lines
  const downset = new Set((p.downbeats || []).map((t) => Math.round(t * 1000)));
  for (const t of p.beats || []) {
    const down = downset.has(Math.round(t * 1000));
    const m = new THREE.Mesh(GEO.beat, new THREE.MeshBasicMaterial({
      color: down ? 0x5b6e92 : 0x2c3550, transparent:true, opacity: down ? 0.9 : 0.5 }));
    m.rotation.x = -Math.PI / 2; m.position.set(0, 0.008, STRIKE_Z - t * SPEED);
    noteGroup.add(m);
  }

  // notes
  for (const n of p.notes) {
    const z = STRIKE_Z - n.t * SPEED;
    let mesh;
    if (n.lane === 'kick') {
      mesh = new THREE.Mesh(GEO.kick, mat(COL.kick, n));
      mesh.position.set(0, 0.06, z);
    } else {
      const c = COL[n.lane];
      mesh = new THREE.Mesh(n.cymbal ? GEO.cym : GEO.tom, mat(c, n));
      mesh.position.set(laneX(laneIndex(n.lane)), n.cymbal ? 0.27 : 0.21, z);
      if (n.dyn === 'ghost') mesh.scale.setScalar(0.66);
      else if (n.dyn === 'accent') mesh.scale.setScalar(1.14);
    }
    mesh.userData.note = n; n.fired = false;
    noteGroup.add(mesh);
  }
}

function mat(color, n) {
  const ghost = n.dyn === 'ghost';
  return new THREE.MeshStandardMaterial({
    color, emissive:color, emissiveIntensity: n.dyn === 'accent' ? 0.85 : 0.4,
    roughness:0.45, metalness: n.cymbal ? 0.6 : 0.15,
    transparent:ghost, opacity: ghost ? 0.5 : 1.0,
  });
}

function disposeGroup(g) {
  g.traverse((o) => { if (o.material) o.material.dispose(); });
}

function resize() {
  const w = el.highway.clientWidth, h = el.highway.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);

// ============================================================================
//  Audio + drum overlay
// ============================================================================
const audio = new Audio();
audio.preload = 'auto';
let actx = null;
function ensureCtx() { if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)(); return actx; }

audio.addEventListener('seeked', resetFired);
audio.addEventListener('play', () => { el.play.textContent = '⏸ Pause'; ensureCtx().resume(); });
audio.addEventListener('pause', () => { el.play.textContent = '▶ Play'; });
audio.addEventListener('ended', () => { el.play.textContent = '▶ Play'; });

function resetFired() {
  if (!preview) return;
  const c = audio.currentTime;
  for (const n of preview.notes) n.fired = n.t < c - 0.02;
}

let noiseBuf = null;
function noise() {
  const ctx = ensureCtx();
  if (!noiseBuf) {
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 0.4, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  const s = ctx.createBufferSource(); s.buffer = noiseBuf; return s;
}
function env(node, t0, peak, dur) {
  const g = ensureCtx().createGain();
  g.gain.setValueAtTime(0.0001, t0);
  g.gain.exponentialRampToValueAtTime(peak, t0 + 0.004);
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
  node.connect(g); g.connect(ensureCtx().destination); return g;
}
function playHit(n) {
  const ctx = ensureCtx(), t0 = ctx.currentTime, vel = (n.vel || 90) / 127;
  if (n.lane === 'kick') {
    const o = ctx.createOscillator(); o.type = 'sine';
    o.frequency.setValueAtTime(150, t0); o.frequency.exponentialRampToValueAtTime(52, t0 + 0.11);
    env(o, t0, 0.9 * vel, 0.14); o.start(t0); o.stop(t0 + 0.16);
  } else if (n.cymbal) {                                  // hi-hat / cymbal
    const s = noise(), f = ctx.createBiquadFilter();
    f.type = 'highpass'; f.frequency.value = 7000; s.connect(f);
    env(f, t0, 0.35 * vel, n.lane === 'yellow' ? 0.05 : 0.3); s.start(t0); s.stop(t0 + 0.4);
  } else if (n.lane === 'red') {                          // snare
    const s = noise(), f = ctx.createBiquadFilter();
    f.type = 'bandpass'; f.frequency.value = 1900; f.Q.value = 0.7; s.connect(f);
    env(f, t0, 0.6 * vel, 0.13); s.start(t0); s.stop(t0 + 0.2);
    const o = ctx.createOscillator(); o.type = 'triangle'; o.frequency.value = 190;
    env(o, t0, 0.3 * vel, 0.09); o.start(t0); o.stop(t0 + 0.1);
  } else {                                                // toms (blue/green)
    const o = ctx.createOscillator(); o.type = 'sine';
    const base = n.lane === 'blue' ? 220 : 150;
    o.frequency.setValueAtTime(base, t0); o.frequency.exponentialRampToValueAtTime(base * 0.7, t0 + 0.12);
    env(o, t0, 0.6 * vel, 0.16); o.start(t0); o.stop(t0 + 0.18);
  }
}

// ============================================================================
//  Animation
// ============================================================================
function tick() {
  requestAnimationFrame(tick);
  const c = audio.currentTime || 0;
  if (noteGroup) noteGroup.position.z = c * SPEED;

  // fire hits (visual flash + audio overlay) as notes cross the strike
  if (preview && !audio.paused) {
    for (const n of preview.notes) {
      if (!n.fired && c >= n.t) {
        n.fired = true;
        if (c - n.t < 0.25) {
          if (el.overlay.checked) playHit(n);
          if (n.lane === 'kick') kickTarget.userData.flash = 1;
          else { const ti = targets[laneIndex(n.lane)]; if (ti) ti.flash = 1; }
        }
      }
    }
  }
  // decay flashes + cull far/old notes
  for (const t of targets) {
    t.flash = Math.max(0, t.flash - 0.06);
    t.mesh.material.emissiveIntensity = 0.25 + t.flash * 1.4;
    t.mesh.scale.setScalar(1 + t.flash * 0.18);
  }
  kickTarget.userData.flash = Math.max(0, kickTarget.userData.flash - 0.06);
  kickTarget.material.emissiveIntensity = 0.18 + kickTarget.userData.flash * 1.2;

  if (noteGroup) {
    for (const o of noteGroup.children) {
      const n = o.userData.note; if (!n) continue;
      const dz = n.t - c;                    // seconds until hit
      o.visible = dz < 0.3 && dz > -LOOKAHEAD;
    }
  }
  el.clock.textContent = c.toFixed(1) + 's';
  renderer.render(scene, camera);
}

// ============================================================================
//  Controls + preview fetching
// ============================================================================
function fmtTime(s) { const m = Math.floor(s / 60); return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`; }

function syncControls() {
  if (!settings) return;
  el.engine.value = settings.engine || 'baseline';
  el.separation.value = settings.separation;
  el.subdivisions.value = String(settings.subdivisions);
  el.dynamics.checked = !!settings.dynamics;
  el.double_kick.checked = !!settings.double_kick;
  el.tom_split.checked = !!settings.tom_split;
  for (const k of SLIDERS) { el[k].value = settings[k]; $(SLIDER_OUT[k]).textContent = (+settings[k]).toFixed(2); }
  updateEngineUI();
}
function readControls() {
  const s = { ...settings };
  s.engine = el.engine.value;
  s.separation = el.separation.value;
  s.subdivisions = +el.subdivisions.value;
  s.dynamics = el.dynamics.checked;
  s.double_kick = el.double_kick.checked;
  s.tom_split = el.tom_split.checked;
  for (const k of SLIDERS) s[k] = +el[k].value;
  return s;
}

// The DrumSep engine self-separates, so the band-energy "Separation"/genre knobs
// don't apply; dim them and flag if the weights aren't installed.
function updateEngineUI() {
  const drumsep = el.engine.value === 'drumsep';
  el.baselineGroup.style.opacity = drumsep ? 0.4 : 1;
  el.separation.disabled = drumsep;
  if (drumsep && preview && preview.drumsepAvailable === false) {
    el.engineHint.innerHTML =
      'DrumSep weights not found — runs as <b>baseline</b>. Install:<br>' +
      '<code>pip install demucs gdown</code> then download the model to ' +
      '<code>model/drumsep.th</code>.';
  } else if (drumsep) {
    el.engineHint.innerHTML = 'Per-drum-stem separation — slower (~10 s / window), much truer lanes.';
  } else {
    el.engineHint.textContent = '';
  }
}

let busy = false;
async function doPreview(payload) {
  if (busy) return; busy = true;
  el.panel.classList.add('busy'); el.status.classList.remove('err');
  el.status.textContent = (payload.engine === 'drumsep' || el.engine.value === 'drumsep')
    ? 'separating drums… (~10s)' : 'transcribing…';
  const start = +el.start.value, length = +el.length.value;
  try {
    const r = await fetch('/api/preview', {
      method:'POST', headers:{ 'Content-Type':'application/json' },
      body: JSON.stringify({ start_s:start, length_s:length, settings:payload }),
    });
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || ('HTTP ' + r.status));
    preview = data; settings = data.settings; syncControls();
    buildScene(data);
    audio.pause(); audio.src = data.audioUrl; audio.currentTime = 0; resetFired();
    showDiag(data);
    const eng = data.engine === 'drumsep' ? 'drumsep' : 'baseline';
    el.status.textContent = `${eng} · ${data.notes.length} notes · ${data.bpm} bpm`;
  } catch (e) {
    el.status.textContent = 'error: ' + e.message; el.status.classList.add('err');
  } finally {
    busy = false; el.panel.classList.remove('busy');
  }
}
// Genre resets the band-energy knobs to a preset, but keep the chosen engine.
const previewGenre = (g) => doPreview({ genre:g, engine: el.engine.value });
const previewTuned = () => doPreview(readControls());

function showDiag(d) {
  const g = d.diagnostics, lanes = {};
  for (const n of d.notes) lanes[n.lane] = (lanes[n.lane] || 0) + 1;
  const cym = d.notes.filter((n) => n.cymbal).length;
  const gl = g.gate.toLowerCase();
  el.diag.innerHTML =
    `engine <b>${d.engine}</b>\n` +
    `gate <span class="${gl}">${g.gate}</span>  rms ${g.drum_rms}\n` +
    `sep <b>${g.separator}</b>  ·  onsets <b>${g.onsets}</b>\n` +
    `notes <b>${g.notes}</b>  cymbals <b>${cym}</b>\n` +
    `lanes ${Object.entries(lanes).map(([k, v]) => `${k}:${v}`).join('  ')}` +
    (g.warnings.length ? `\n\n⚠ ${g.warnings.slice(0, 4).join('\n⚠ ')}` : '');
}

// wire events
el.start.addEventListener('input', () => { el.startOut.textContent = fmtTime(+el.start.value); });
el.length.addEventListener('input', () => { el.lenOut.textContent = el.length.value + 's'; });
el.start.addEventListener('change', previewTuned);
el.length.addEventListener('change', previewTuned);
el.shuffle.addEventListener('click', () => {
  const max = Math.max(0, duration - (+el.length.value));
  el.start.value = (Math.random() * max).toFixed(1);
  el.startOut.textContent = fmtTime(+el.start.value); previewTuned();
});
el.engine.addEventListener('change', () => { updateEngineUI(); previewTuned(); });
el.genre.addEventListener('change', () => previewGenre(el.genre.value));
el.separation.addEventListener('change', previewTuned);
el.subdivisions.addEventListener('change', previewTuned);
el.dynamics.addEventListener('change', previewTuned);
el.double_kick.addEventListener('change', previewTuned);
el.tom_split.addEventListener('change', previewTuned);
for (const k of SLIDERS) {
  el[k].addEventListener('input', () => { $(SLIDER_OUT[k]).textContent = (+el[k].value).toFixed(2); });
  el[k].addEventListener('change', previewTuned);
}
el.repreview.addEventListener('click', previewTuned);
el.play.addEventListener('click', () => { if (audio.paused) audio.play(); else audio.pause(); });

// ============================================================================
//  Init
// ============================================================================
async function init() {
  resize(); tick();
  try {
    const meta = await (await fetch('/api/meta')).json();
    duration = meta.duration_s || 60;
    el.songinfo.textContent = `${meta.name} — ${meta.artist} · ${fmtTime(duration)}`;
    el.start.max = Math.max(1, duration - (+el.length.value)).toFixed(1);
    // start somewhere with drums (skip a possible intro), then first preview
    el.start.value = Math.min(40, Math.max(0, duration * 0.25)).toFixed(1);
    el.startOut.textContent = fmtTime(+el.start.value);
    el.lenOut.textContent = el.length.value + 's';
  } catch (e) { el.songinfo.textContent = 'could not load song meta'; }
  await previewGenre(el.genre.value);
}
init();
