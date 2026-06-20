# charter

Turn an uploaded **mp3** into a **playable Clone Hero 4-lane Pro Drums** chart.

> Status: early build, end-to-end runnable. **`audio file → playable song folder`
> works today** with a dependency-light baseline (numpy/scipy + FFmpeg, no model
> downloads). Quality is "instant draft": the kick/snare/hi-hat backbone, a real
> tempo map, and a valid 4-lane Pro chart Clone Hero loads — **not** hand-charter
> quality. Toms / ride-vs-crash and the SOTA models (Demucs/Beat This!/ADTOF) are
> the next quality levers (wired as optional adapters; see docs/10 Part B).

📚 **Design & source of truth:** [`docs/`](./docs/README.md) — start there. The
thesis, the 8-stage pipeline, the chart-format bible, and the MVP roadmap all
live in those documents. This README is just the build/run entry point.

## What works today

```
audio file ──► [ingest] ──► [drum separation] ──► [beat/tempo] ──► [drum ADT]
                                                                       │
   playable song folder ◄── [scan-chart gate] ◄── [.chart serialize] ◄── [quantize → GM→CH map]
   (notes.chart + song.ini + song.opus)
```

- **Symbolic backend** (roadmap Phase 1–2): `DrumNote → .chart + song.ini`, the
  format firewall (tom/cymbal inversion, opt-in 2× kick, `BPM×1000`, `TS`
  exponent, same-color collisions) — deterministic, validated by Clone Hero's own
  parser (scan-chart).
- **Audio frontend** (roadmap Phase 3): `mp3 → drum onsets + tempo grid` with a
  numpy/scipy baseline — HPSS percussive separation, a DP beat tracker with a
  smoothed per-beat tempo map, and a band-energy kick/snare/hat transcriber.
  Optional **Demucs / Beat This! / ADTOF** adapters are used automatically if
  installed.

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
│   ├── validate.py        # Python bridge to the scan-chart gate
│   └── cli.py             # `mp3tochart` / `midi2chart` / `validate`
├── tools/validation/      # Node ≥24 — scan-chart subprocess (the canonical gate)
└── tests/                 # serializer/mapping/DSP/ADT unit tests + scan-chart round-trips
```

## Setup

```bash
# Python deps (audio frontend needs numpy + scipy; pytest for the suite)
python3 -m pip install numpy scipy pytest

# FFmpeg (system binary — decode/normalize/encode audio)
brew install ffmpeg            # macOS

# Node validation gate (canonical Clone Hero acceptance check, needs Node ≥24)
cd tools/validation && npm install && cd -

# OPTIONAL — SOTA adapters (heavy; install in a venv, used automatically if present):
#   pip install demucs beat-this        # better stem + beat tracking
```

## Use

```bash
# Audio file -> playable Clone Hero song folder (+ song.opus), then validate
python -m charter.cli mp3tochart song.mp3 out/song --validate

# GM-drum MIDI -> song folder (the symbolic backend, no audio/ML)
python -m charter.cli midi2chart tests/fixtures/basic_groove.mid out/basic --validate

# Validate any existing song folder against scan-chart
python -m charter.cli validate out/song
```

`mp3tochart` prints a **GO / CAUTION / REFUSE** drum-prominence gate, the picked
adapters, the tempo/onset/note counts, and review notes; with `--validate` it
asserts Clone Hero detects `fourLanePro`. Drop the result into Clone Hero's songs
folder (or open in Moonscraper to clean up).

## Test

```bash
python -m pytest    # full suite; scan-chart / ffmpeg tests auto-skip if those tools are absent
```

37 tests cover the serializer (format invariants), GM mapping/collision/2× kick,
the DSP/tempo/ADT baseline, and end-to-end `audio → scan-chart fourLanePro`.
