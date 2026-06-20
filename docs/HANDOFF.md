# Handoff & Open Issues

> **Status:** Living handoff · **Last updated:** 2026-06-20 · **Audience:** the next build agent(s)
> **Purpose:** Where the project actually stands, the BLOCKING open bug, what was already tried (so you don't repeat it), and the remaining work. Read [README.md](./README.md) first for the doc map, then this.

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

### The real lever (matches the env)
The environment is **torch-native**: `.venv` has **torch 2.12 + torchaudio 2.11 + MPS (M1 GPU)**, demucs 4.0.1 — but **NO TensorFlow / librosa / madmom / adtof / omnizart**. So the docs' ADTOF (TensorFlow) engine is the *wrong first pick* on this machine. Prefer a **torch-native per-drum-stem approach** (the docs' Phase-7 DrumSep/LarsNet arbiter): split the drum signal into kick / snare / hi-hat / toms / cymbals stems, then run onset detection **per stem** — classification becomes "which stem fired," which directly fixes all four failure modes above and unlocks toms + ride-vs-crash (non-empty charts). See [05-drum-transcription.md](./05-drum-transcription.md) and [04-source-separation.md](./04-source-separation.md).

### Cheap interim hardening (no new deps, partial)
If a quick win is wanted before the model lands: lower the hi-hat `vhigh` gate so a groove returns, gate kicks on transient sharpness (not raw low-band energy) to reject bass, disable the ghost/2×-kick floods by default. This makes the chart *recognizable*, not *good*.

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
