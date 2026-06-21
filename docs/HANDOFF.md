# Handoff & Open Issues

> **Status:** Living handoff · **Last updated:** 2026-06-21 · **Audience:** the next build agent(s)
> **Purpose:** Where the project actually stands, the BLOCKING open bug, what was already tried (so you don't repeat it), and the remaining work. Read [README.md](./README.md) first for the doc map, then this.

---

## 🔄 DIRECTION RESET (2026-06-21) — grounding the beat grid first

The user reset the build to a **simpler, foundation-first** version. Rationale: blind ADT on dense/distorted metal is unreliable, and **everything downstream (drums, bass, other instrument lines) snaps to the beat grid** — so the grid must be accurate, drift-tracking, and *correctable* before anything is built on it.

- **The full auto-charter studio** (ADT engines: baseline/drumsep, pattern mode, the kick-from-audio hybrid, tempo/metal accuracy controls) is **preserved on the `studio-autocharter-v1` branch** for reference. All of that work (drumsep per-drum engine, pattern library, etc.) is still valid — it's just paused while the foundation is grounded.
- **`main` now hosts the beat-grid studio** (`charter/studio/`, rewritten): `analyze.py` (beats + drift-tracking tempo curve + sections + waveform), `sections.py` (novelty segmentation), `server.py` (`/api/analyze`, `/api/audio` with HTTP Range for full-song seek). Frontend = a **Clone-Hero highway** (beat/bar lines fly to a strikeline + **metronome click** to judge the beat by ear) **+ a DAW timeline** (waveform, beats/bars, colored sections, green tempo-drift curve, playhead, click-seek, wheel-zoom, drag-pan). Controls: tempo ×½/×1/×2, tempo hint, beats-per-bar, shift-downbeat, re-analyze. Run `python -m charter.studio mp3/clay.mp3`.
- **Core concern handled:** beats are "ever-evolving" — the grid is a *per-beat* sequence (not one BPM), so drift is preserved and shown on the tempo curve; the metronome click is how the user verifies alignment; ×2/×½ + tempo-hint + phase-shift fix the gross errors.
- **Verified in a real browser** (clay, melodic death metal): 593 beats, 149 bars, 7 sections, drift 108–126 BPM; highway scrolls + section tint; timeline + playhead + tempo curve render; full-song playback/seek works; zero console errors.
- **Next on this track (open):** manual **beat editing** (drag/add/delete individual beats on the timeline — the real fix for where the detector loses the beat); **section boundary editing** (split/merge/rename); better segmentation (the 135 s block should subdivide); per-region tempo correction; then start layering instrument lines onto the grid.

The sections below describe the (still-valid, branch-preserved) auto-charter work.

---

## ✅ RESOLVED — the "No Part" bug was a Clone Hero **controller setting**, not our code

**Top priority is now transcription QUALITY (see the next section).**

### What it actually was (2026-06-20)
The user's Clone Hero **controller/instrument was bound to "guitar."** With no drums controller active, CH hides the drums part and shows **"No Part"** — for *every* drum chart, not just ours. **Setting the controller to "drums" made the chart appear and play.** `scan-chart` (which byte-matches CH's parser) was correct the entire time: `drumType=fourLanePro, playable=True, expert=1690, PASS` was a true verdict. The folder/format/serializer were never broken.

### Lessons (don't repeat the chase)
- **Before suspecting the chart, verify the CH side:** controller bound to drums, the right instrument selected, a clean rescan. A known-good community drums chart failing to show as drums is the tell that it's a CH-setup issue, not the file.
- The earlier "format hardening" (commit `ef4483c`: full Moonscraper `[Song]` block, empty `[Events]`, `song.ini` cleanup) was **not** what fixed it — but it's harmless and keeps us spec-faithful, so it stays.
- Trust the `scan-chart` PASS. It held.

### Useful facts (still relevant for quality work)
- `mp3/clay.mp3` is **electronic** with a **~13 s drumless intro** (first note ~tick 4992). ~5.5 min (`song_length=334288` ms).
- Files in `out/clay/`: `notes.chart` (40 KB, 1690 notes), `song.ini` (`pro_drums=True`), `song.opus` (plays fine).

---

## 🔴 PRIORITY #1 — Transcription quality: the chart "doesn't match the music"

The chart now loads, but on real music it is **not playable-as-the-song**. Root cause is the **baseline ADT** (`charter/audio/adt.py`), a 3-band energy classifier that fails on real mixes in four compounding ways. On `clay.mp3` the 1690 gems broke down as:

| Symptom | Count | Cause (in `_classify`, `adt.py`) |
|---|---|---|
| Kick fires on the **bassline**, not the kick | **874** kick events (435 `N 0` + 439 `N 32`) | `low(20–150Hz)/total > 0.28 → KICK`; bass dominates the low band on electronic tracks |
| **No hi-hat groove** | **1** hi-hat note total | hat needs `vhigh(8kHz–Nyq)/total > 0.45` — almost no real mix clears this, so hats collapse into snare |
| **Snare on everything else** | **815** snares | every non-kick onset with `mid > 0.18` → snare |
| **Spurious ghost / 2× floods** | 666 ghost flags, 439 false 2× | velocity `30+97·(env/peak)` lands most hits ≤60 → ghost; the ~150 ms gap rule over-fires 2× kick |

This is a **fundamental** limit of band-energy classification — it cannot be tuned into a chart that matches the song.

### The real lever — ✅ BUILT (2026-06-20): the DrumSep per-drum engine
The environment is **torch-native**: `.venv` has **torch 2.12 + torchaudio 2.11 + MPS (M1 GPU)**, demucs 4.0.1 — but **NO TensorFlow / librosa / madmom / adtof / omnizart**. So the docs' ADTOF (TensorFlow) engine is the *wrong first pick*. We shipped the **torch-native per-drum-stem approach** instead:

- **Model:** `inagoy/drumsep` — a Hybrid Demucs checkpoint that splits into **4 stems: kick / snare / cymbals / toms** (Spanish source names `bombo/redoblante/platillos/toms`). Reuses the **already-installed demucs** (no new framework). Weights = one ~167 MB Google-Drive download (gdrive id `1-Dm666ScPkg8Gt2-lK3Ua0xOudWHZBGC`). Runs on **MPS** (~8–10 s per 12 s window).
- **Engine:** `charter/audio/drumsep.py` → `DrumSepTranscriber`. Separates, then runs **onset detection per stem** (reusing `dsp.onset_envelope`/`peak_pick`), so "which drum" = "which stem fired." Maps kick→36, snare→38, cymbals→**42 yellow hi-hat cymbal** (owns yellow exclusively), toms→**blue/green by spectral centroid** (never yellow, so they can't collide with the hi-hat and force a fake blue crash).
- **Two torch-2.12 gotchas solved (don't re-hit these):** (1) gdown dropped the `--id` flag — use positional id; (2) demucs 4.0.1's `load_model` calls `torch.load(weights_only=True)` (the torch≥2.6 default), which rejects the pickled `HDemucs` class — so we `torch.load(..., weights_only=False)` ourselves (trusted checkpoint) and hand the dict to `load_model`.
- **Result on a clay window:** baseline = 22 notes, 0 cymbals (snare mush); **drumsep = ~62 notes with kick + snare + ~17 yellow hi-hats + blue/green toms** — a real kit. The two worst failures (bass-as-kick, no-hi-hat) are fixed because the kick stem has no bassline and the cymbals stem carries the groove.
- **Wired everywhere:** `choose_transcriber("drumsep")` (graceful fallback to baseline if weights/demucs absent); studio **Engine** dropdown (Baseline fast / DrumSep quality) + tom-split toggle + availability hint; CLI `mp3tochart --engine drumsep` and `charter download-weights`. Pipeline now beat-tracks on an HPSS signal when the separator is passthrough (drumsep self-separates from the raw mix), so the tempo grid stays good.

### Accuracy controls for fast metal (2026-06-21)
Melodic death metal exposed three linked failures — **double bass missing, snare-heavy, wrong patterns** — all downstream of tempo/grid/onset, not isolation. Fixes shipped (studio + CLI):
- **Tempo multiplier** (`resample_grid` in `quantize.py`; studio "Tempo ×½/×1/×2", CLI `--tempo-mult`). The DP tracker's 120-BPM-centered prior *mathematically prefers half-time* for fast metal; at half tempo a 16th grid becomes 8th-note spacing and adjacent double-bass hits **merge 2-into-1** (→ missing double bass + relative snare excess). ×2 recovers true tempo. **This is the #1 metal fix** — tell the user: if the BPM readout is half the real tempo, set ×2.
- **Finer grid** `1/32` (subdiv 8; studio Grid + CLI `--grid 8`) so fast double bass lands on distinct ticks.
- **Per-stem onset tuning in `DrumSepConfig`** (was one-size-fits-all): kick gets a fine gap (`kick_min_gap_s` 0.030, exposed as "Kick gap") to catch sustained double bass; snare gets a higher threshold (`snare_delta`, exposed as "Snare amount") to curb over-detection. These improved defaults apply to ALL drumsep runs automatically.
- **Metal preset** retuned for drumsep (1/32, fine kick, less snare, 2× kick on) and **picking Metal/Rock auto-switches the engine to DrumSep**. The studio shows engine-appropriate knobs (drumsep tuning vs baseline band-energy).
- Verified in a real browser: tempo ×2 doubles the BPM readout (120→240); Metal preset produces a dense kit with "N kicks marked as 2× (double-bass)".
- **Still unmeasured on the user's actual metal track** (sandbox only has electronic `clay.mp3`) — the user validates in the studio. Likely next tuning: if double bass is still merged at ×2, drop the grid to triplets or lower `kick_gap_s`; if snare-heavy, raise "Snare amount".

### Pattern mode — genre templates for where ADT fails (2026-06-21)
**The user's key insight: blind ADT on dense/distorted metal is unreliable (stems bleed → a smear of toms/cymbals/snare), and fixing it note-by-note = rewriting.** So we added a **template approach** alongside ADT — `charter/patterns/` + a studio **Mode** toggle (Detect / Pattern):
- **Pattern library** (`patterns/library.py`): genre grooves as 1-bar/16-step voice maps (kick/snare/hihat/ride/toms → CH lanes via `VOICE_MAP`). Metal-heavy (double-bass 8th/16th, blast beat, thrash/skank, d-beat, half-time) + rock/punk. `apply_pattern` tiles a groove across the window's bars and places phrase crashes.
- **The hybrid (the important bit):** in metal the **kick pattern is song-specific but robustly detectable**, while **snare/cymbal voicing is genre-conventional but where ADT fails**. So **"kick from audio"** takes the kick from the drumsep kick stem (quantized to the grid) and the snare/ride/hi-hat voicing from the template — the song's real double bass under a clean conventional voicing. This directly uses the audio/ML to *refine* a template, not transcribe from scratch (the user's exact ask).
- **Studio:** Mode dropdown; Pattern panel (groove select + "kick from audio"); the *window* is the region selector for v1 (set Start+Length to a section). Verified in a real browser: pattern mode renders a clean repeating groove (orange kick on 8ths, green ride, red snare on 2&4, blue crash) instead of ADT smear; hybrid shows "kick from audio: N hits".
- **Next on this track (open):** finer region selection (sub-bar / multi-segment on the timeline, not just the window); per-bar fill insertion (detect fills via onset-density spikes → swap a fill template); crash/section placement from audio (cymbal-energy spikes at phrase starts); more patterns per genre; **Export** the tuned section to a chart. Also: `clay.mp3` IS melodic death metal (not electronic — a stale earlier note was wrong); ADT/drumsep results on it are genuinely poor, which is *why* pattern mode exists.

**Honest limits (next levers):** 4 stems means hi-hat shares the cymbals stem with crash/ride — v1 maps the whole cymbals stem to a yellow hi-hat (safe, no blue/green crash calls). Ride-vs-crash + open/closed hat is still the blue-lane frontier. A **5-stem model (LarsNet)** would separate hi-hat from cymbals, but its env pins python 3.11 / torch 2.1 / numpy 1.26 (conflicts with this env) + CC BY-NC — documented upgrade, not v1. drumsep weights are **gitignored** (`/model/`, `*.th`) — fetch with `charter download-weights`.

---

## 🎛️ The preview studio (`charter/studio/`) — built 2026-06-20

A **tune-and-preview loop**, since the baseline can't be tuned blind but can be tuned fast. Run:

```bash
python -m charter.studio mp3/clay.mp3      # opens a browser previewer; --port/--host/--no-open
```

- **Zero new deps:** a stdlib `http.server` (no FastAPI) serves a **Three.js Clone-Hero-style highway** (notes scroll to a strikeline, lane targets flash on hit, beat/downbeat lines) loaded via import-map (no npm/build). Reuses the existing pipeline.
- **Loop:** pick a 10-20 s window (anywhere in the tune) → choose a **genre preset** + nudge sliders (separation, onset sensitivity, kick/snare/hi-hat gates, grid, dynamics, 2× kick) → **Re-preview** (~1.8 s for a 16 s HPSS window) → watch the highway **synced to the clip audio** + hear a **synthesized drum overlay** → iterate → (export wiring is the obvious next step).
- **Architecture:** `presets.py` (settings + genre bundles → `BaselineConfig`/`MapConfig`/separator/subdiv), `service.py` (`run_preview` inlines the stages to expose the beat grid; note times offset by `beat_times[0]` so the highway doesn't drift), `server.py` (3 routes: `/api/meta`, `/api/preview`, `/api/audio` WAV), `web/` (`index.html`/`styles.css`/`app.js`). The Three.js scene maps 1:1 onto **React-Three-Fiber** for the planned OCTAVE-style editor (north stars: `opria123/octave`, `chart-forge.app` — both are R3F highways; neither auto-charts, which is our niche).
- **Two small pipeline hooks added:** `decode_audio(..., start_seconds=)` for window seeking; `BaselineConfig.onset_delta/onset_min_gap_s` to fight onset over-detection.
- **Honest result on `clay`:** the studio makes the baseline's ceiling visible — even tuned, it's mostly snare with few kicks and ~no hi-hats (band-energy can't split broadband hat transients from snare). That's the case for the **torch per-drum-stem engine**, which slots into the same UI as another "Separation" option.

---

## What is built and working (as of 2026-06-20)

The pipeline runs **end-to-end**: `audio file → out/<song>/ (notes.chart + song.ini + song.opus)` that **scan-chart** reports as `fourLanePro` / `playable=True`. See [README.md](./README.md) for run/test commands and [10-mvp-roadmap.md](./10-mvp-roadmap.md) for phase status.

- **Phases 1–2 (symbolic backend):** `charter/drumnote/` (DrumNote model + `.chart` serializer + song.ini — the format firewall) and `charter/mapping/` (GM→CH table, collision resolver, 2× kick, dependency-free SMF loader). Deterministic, unit-tested.
- **Phase 3 (audio frontend):** `charter/audio/` — FFmpeg ingest, HPSS separation (+ optional Demucs), numpy DP beat tracker + smoothed tempo map, band-energy kick/snare/hat ADT, quantization. **Baseline-grade.**
- **Phase 4 (partial):** GO/CAUTION/REFUSE drum-RMS gate is in; **REVIEW.md artifact is NOT** (see remaining work).
- **Validation gate:** `tools/validation/` (Node ≥24 scan-chart) + `charter/validate.py`.
- **37 tests pass** (`python -m pytest`). scan-chart / ffmpeg tests auto-skip if absent.
- **CLI:** `mp3tochart` / `midi2chart` / `validate`, with `--sep`, `--device`, `--max-seconds`, `--quiet`, `--validate`, and per-stage progress logging.

---

## Known quality issues (non-blocking, but real)

1. **Bass bleeds into kick detection (over-busy kicks).** On bass-heavy tracks the HPSS+low-band ADT marks far too many kicks (Clay: 1690 notes, **439** flagged "2× kick"). The chart is playable but machine-gun on the kick. **Biggest single quality win:** stricter low-band gating in `charter/audio/adt.py` + more conservative 2× inference in `charter/mapping/stage6.py` (the ~150 ms gap over-fires). The user explicitly offered this as the next tuning task.
2. **Demucs is track-dependent.** Verified: on `clay.mp3`, Demucs routes percussion into `other` (RMS 0.139) and leaves `drums` near-silent (0.0002) — it's trained on acoustic kits, so electronic/programmed percussion is stripped. `--sep auto` now uses `SmartSeparator`, which detects the empty drum stem and **falls back to HPSS** (commit `cdffa25`). Caveat: on a full song, `auto` runs the slow Demucs pass *first* before falling back — for known electronic tracks tell the user to use `--sep hpss` directly.
3. **Baseline ADT = kick/snare/hi-hat only.** No toms, no ride-vs-crash, no velocity dynamics. Tested on **synthetic drums only** — real-music accuracy is unmeasured.
4. **4/4 assumed; tempo map is good but not downbeat-anchored.** Odd meters not detected.

---

## Remaining work (carried over)

**First: fix BLOCKING BUG #1 above.** Then, from [10-mvp-roadmap.md](./10-mvp-roadmap.md) Part B, in payoff order:

- [ ] **Bass-as-kick tuning** (quality issue #1 above) — highest-value, no new deps.
- [ ] **Phase 6 — RoFormer** separation (better drum stem than Demucs on real kits; doesn't help electronic tracks).
- [ ] **Phase 7 — DrumSep per-drum arbiter** → toms + ride-vs-crash (the blue-lane frontier). This is what makes charts feel non-empty.
- [ ] **Phase 8 — velocity / dynamics** (ghost/accent) — per-stem loudness now, ADT model later.
- [ ] **Phase 9 — allin1 segments** for fills / star-power / meter-disagreement flags.
- [ ] **Phase 10 — difficulty reduction** (Expert → Hard/Medium/Easy via EasyChartGenerator logic; `charter/mapping` currently emits Expert only). *Note: confirm whether CH needs lower difficulties to show the part — possibly related to BUG #1.*
- [ ] **Phase 4 — write `REVIEW.md`** (the confidence surface: low-RMS regions, inferred 2× runs, meter guess). Currently only printed to stdout.
- [ ] **ADTOF adapter** in `charter/audio/adt.py` is a stub (`NotImplementedError`) — wire the `drumTranscriptor` call for the real 5-class ADT.

---

## How to reproduce / test (for the next agent)

```bash
cd /Users/johanleche/Documents/Code/charter
python -m pytest -q                                  # 37 tests

# the failing case (electronic track; bug #1 reproduces in the user's CH):
python -m charter.cli mp3tochart mp3/clay.mp3 out/clay --sep hpss --validate
#  -> 1690 notes, scan-chart PASS, but user's CH shows "No Part"

# fast clip test on any audio:
python -m charter.cli mp3tochart <audio> out/x --max-seconds 30 --validate
```
- **Optional SOTA:** Demucs is installed in the user's env (4.0.1 — note: **`demucs.api` is absent in this build**, use `demucs.apply.apply_model` + manual normalization, see `charter/audio/separation.py`). M1 has MPS; Demucs runs on it but is slow on full songs.
- **Sandbox note:** the Bash sandbox is an ephemeral snapshot — `out/` and pip-installs there do NOT reflect the user's real terminal env. Don't rely on sandbox state persisting between commands.

## Commit trail (this session)
```
cdffa25  feat: progress logging, --max-seconds, robust Demucs path + HPSS fallback
ef4483c  fix: Moonscraper-complete .chart/song.ini   (attempted bug #1 fix — INSUFFICIENT)
d50c107  feat: audio frontend (Phase 3)
f63112b  docs: sync roadmap (Phases 1-2)
903854f  feat: symbolic backend (Phases 1-2)
e6cb205  docs: research source-of-truth
```
