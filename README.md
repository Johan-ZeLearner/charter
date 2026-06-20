# charter

Turn an **mp3** into a **playable Clone Hero 4-lane Pro Drums** chart — and **tune
the transcription per song** in a Clone-Hero-style preview studio instead of
guessing.

> **Status:** end-to-end runnable. The pipeline turns `audio → playable song
> folder` today (numpy/scipy + FFmpeg, no model downloads), and a **preview
> studio** lets you audition the auto-chart on a scrolling CH highway over a
> 10–20 s window, tune settings by music type, and iterate in ~2 s. Output is an
> "instant draft," not hand-charter quality — the studio exists to make that
> draft *tunable*, and to make the baseline's limits *visible*. The next quality
> lever is a per-drum-stem ADT (kick/snare/hi-hat/tom/cymbal).

📚 **Design & source of truth:** [`docs/`](./docs/README.md) — the thesis, the
8-stage pipeline, the chart-format bible, and the roadmap. Current state and
next steps live in [`docs/HANDOFF.md`](./docs/HANDOFF.md).

---

## The product: a tuning studio 🎛️

charter is **human-in-the-loop**. Drum charting is *transcription*, not creative
choreography — so the realistic target is an **AI draft you tune in minutes**, not
a perfect one-shot. The studio is where you do that: load a song, preview the
auto-charted drums on a Clone-Hero-style 3D highway synced to the audio, adjust
the transcription by ear, and iterate.

```bash
python -m charter.studio mp3/your-song.mp3      # opens a browser previewer; Ctrl-C to stop
```

**Zero extra install** — it reuses what the pipeline already needs (numpy / scipy
/ FFmpeg). A tiny stdlib HTTP server serves a **Three.js** highway loaded via
import-map (no FastAPI, no npm, no build step).

In the browser:

- **Pick a 10–20 s window** anywhere in the tune (the loop is seconds, not a
  full-song render).
- **Choose a genre preset** (Electronic / Rock / Metal / Pop / Jazz) and nudge
  sliders — separation, onset sensitivity, kick/snare/hi-hat gates, grid,
  dynamics, 2× kick.
- **Re-preview (~2 s)** → notes scroll to a strikeline in sync with the clip
  audio, lane pads flash on hit, and a **synthesized drum overlay** lets you hear
  whether the chart matches the music.
- Live diagnostics: note/lane counts, separator, and the GO/CAUTION/REFUSE gate.

> **North stars:** [`opria123/octave`](https://github.com/opria123/octave) and
> [chart-forge.app](https://chart-forge.app/) — both are React-Three-Fiber chart
> editors with the same highway. Neither auto-charts from audio; **that gap is our
> niche.** The Three.js scene here ports ~1:1 to R3F for the planned
> OCTAVE-style / Moonscraper-replacement editor.

---

## The pipeline (under the studio)

```
audio file ──► [ingest] ──► [drum separation] ──► [beat/tempo] ──► [drum ADT]
                                                                       │
   playable song folder ◄── [scan-chart gate] ◄── [.chart serialize] ◄── [quantize → GM→CH map]
   (notes.chart + song.ini + song.opus)
```

- **Symbolic backend** (Phase 1–2): `DrumNote → .chart + song.ini`, the format
  firewall (tom/cymbal inversion, opt-in 2× kick, `BPM×1000`, `TS` exponent,
  same-color collisions) — deterministic, validated by Clone Hero's own parser
  (scan-chart).
- **Audio frontend** (Phase 3): `mp3 → drum onsets + tempo grid` with a
  numpy/scipy baseline — HPSS percussive separation, a DP beat tracker with a
  smoothed per-beat tempo map, and a band-energy kick/snare/hat transcriber.
  Optional **Demucs / Beat This! / ADTOF** adapters are used automatically if
  installed.

Batch use without the UI:

```bash
# Audio file -> playable Clone Hero song folder (+ song.opus), then validate
python -m charter.cli mp3tochart song.mp3 out/song --validate

# GM-drum MIDI -> song folder (the symbolic backend, no audio/ML)
python -m charter.cli midi2chart tests/fixtures/basic_groove.mid out/basic --validate

# Validate any existing song folder against scan-chart
python -m charter.cli validate out/song
```

> **Loading into Clone Hero:** drop the song folder into CH's songs folder. If the
> drums show **"No Part,"** your controller/instrument is bound to *guitar* — set
> it to **drums** and the chart appears. (This is a CH setting, not a chart bug.)

---

## Layout

```
charter/
├── docs/                  # design source of truth (read docs/README.md first)
├── charter/               # the Python package
│   ├── drumnote/          # ◀ FORMAT FIREWALL: DrumNote model + .chart serializer + song.ini
│   ├── mapping/           # Stage 6: GM→CH table, collision resolver, 2× kick, SMF loader
│   ├── audio/             # Stages 0-5: ingest, separation, beats/tempo, ADT, quantize
│   │   ├── dsp.py         #   numpy/scipy DSP (STFT, HPSS, onset, tempo, DP beat track)
│   │   ├── separation.py  #   HPSS baseline + optional Demucs adapter
│   │   ├── beats.py       #   numpy DP tracker + optional Beat This! adapter
│   │   ├── adt.py         #   band-energy baseline + optional ADTOF adapter
│   │   └── pipeline.py    #   mp3 → Song orchestrator
│   ├── studio/            # 🎛️ the preview/tuning UI (stdlib server + Three.js highway)
│   │   ├── presets.py     #   genre presets + settings → pipeline configs
│   │   ├── service.py     #   window + settings → notes-with-times JSON
│   │   ├── server.py      #   stdlib HTTP routes (/api/preview, /api/audio …)
│   │   └── web/           #   index.html + app.js (Three.js highway) + styles.css
│   ├── validate.py        # Python bridge to the scan-chart gate
│   └── cli.py             # `mp3tochart` / `midi2chart` / `validate`
├── tools/validation/      # Node ≥24 — scan-chart subprocess (the canonical gate)
└── tests/                 # serializer/mapping/DSP/ADT unit tests + scan-chart round-trips
```

## Setup

```bash
# Python deps (audio frontend + studio need numpy + scipy; pytest for the suite)
python3 -m pip install numpy scipy pytest

# FFmpeg (system binary — decode/normalize/encode audio)
brew install ffmpeg            # macOS

# Node validation gate (canonical Clone Hero acceptance check, needs Node ≥24)
cd tools/validation && npm install && cd -

# OPTIONAL — SOTA adapters (heavy; install in a venv, used automatically if present):
#   pip install demucs beat-this        # better stem + beat tracking
```

> The studio itself needs **no extra packages** beyond numpy/scipy/FFmpeg — it
> serves a Three.js highway from a CDN via import-map, so there's nothing to build.

## Test

```bash
python -m pytest    # full suite; scan-chart / ffmpeg tests auto-skip if those tools are absent
```

Tests cover the serializer (format invariants), GM mapping/collision/2× kick, the
DSP/tempo/ADT baseline, and end-to-end `audio → scan-chart fourLanePro`.

> **Note:** source audio (`*.mp3`, etc.) is **gitignored and never committed** —
> bring your own files; point the CLI/studio at a local path.
