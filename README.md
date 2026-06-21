# charter

Turn an **mp3** into a **playable Clone Hero 4-lane Pro Drums** chart — built
foundation-first, starting from an accurate, editable **beat grid**.

> **Status (2026-06-21):** reset to a **beat-grid studio**. Blind auto-transcription
> on dense/distorted music (metal) is unreliable, and *everything downstream
> (drums, bass, other lines) snaps to the beat grid* — so the current work grounds
> that foundation first: detect the beat + song structure, let you **judge and
> correct** them, then build on the locked grid. The earlier full auto-charter
> (ADT engines, genre pattern mode) is preserved on the **`studio-autocharter-v1`**
> branch and still valid — just paused.

📚 **Design & source of truth:** [`docs/`](./docs/README.md) → start there, then
[`docs/HANDOFF.md`](./docs/HANDOFF.md) for the current state and what's next.

---

## The beat-grid studio 🥁

```bash
python -m charter.studio mp3/your-song.mp3      # opens a browser; Ctrl-C to stop
```

Zero extra install (numpy / scipy / FFmpeg + a Three.js highway via CDN import-map).
Two synced views:

- **Clone-Hero highway** — beat & bar lines fly toward a strikeline with a
  **metronome click** (downbeat vs beat), so you judge whether the grid matches
  the music *by eye and ear*. The board tints by song section.
- **DAW timeline** — waveform, beat/bar grid with bar numbers, colored sections,
  a **tempo-drift curve**, and a playhead. Click to seek, wheel to zoom, drag to pan.

**Core idea — beats are ever-evolving.** The grid is a *per-beat* sequence, not a
single BPM, so tempo drift is preserved and drawn on the curve. Controls to
correct it: **Tempo ×½ / ×1 / ×2** (octave fix), **tempo hint**, **beats-per-bar**,
**shift-downbeat**, **re-analyze**.

What it detects today: **beats + downbeats + drift-tracking tempo** and **song
sections** (novelty segmentation). Next: manual per-beat editing, section
split/merge, then layering instrument lines onto the grid.

---

## The pipeline (the reusable backend)

The chart-format and audio backends underneath are intact and reused:

```
audio ─► [ingest] ─► [drum separation] ─► [beat/tempo] ─► [drum ADT] ─► [quantize → GM→CH map] ─► [.chart] ─► [scan-chart gate]
```

- **Symbolic backend** (`charter/drumnote`, `charter/mapping`): `DrumNote → .chart +
  song.ini`, the format firewall (tom/cymbal inversion, opt-in 2× kick, `BPM×1000`,
  `TS` exponent, same-color collisions), validated by Clone Hero's own parser
  (scan-chart). Deterministic, unit-tested.
- **Audio frontend** (`charter/audio`): numpy/scipy baseline — HPSS, DP beat
  tracker + per-beat tempo map, band-energy ADT. Optional **Demucs / DrumSep /
  Beat This!** adapters used if installed.

Batch CLI (no UI):
```bash
python -m charter.cli mp3tochart song.mp3 out/song --validate    # audio → song folder
python -m charter.cli midi2chart drums.mid out/x --validate      # GM-drum MIDI → chart
python -m charter.cli validate out/song                          # scan-chart gate
```
> **Loading into Clone Hero:** if drums show **"No Part,"** set the CH
> controller/instrument to **drums** (it's a CH setting, not a chart bug).

---

## Layout

```
charter/
├── docs/                  # design source of truth (read docs/README.md first)
├── charter/
│   ├── studio/            # 🥁 the beat-grid studio (active)
│   │   ├── analyze.py     #   beats + tempo curve + sections + waveform
│   │   ├── sections.py    #   novelty song-structure segmentation
│   │   ├── server.py      #   /api/analyze, /api/audio (HTTP Range)
│   │   └── web/           #   highway (Three.js) + DAW timeline (canvas)
│   ├── drumnote/          # ◀ FORMAT FIREWALL: DrumNote + .chart serializer + song.ini
│   ├── mapping/           # Stage 6: GM→CH table, collisions, 2× kick, SMF loader
│   ├── audio/             # ingest, separation, beats/tempo, ADT, quantize
│   ├── patterns/          # genre drum-pattern library (used by the branch studio)
│   ├── validate.py        # Python bridge to the scan-chart gate
│   └── cli.py             # mp3tochart / midi2chart / validate / download-weights
├── tools/validation/      # Node ≥24 — scan-chart (the canonical gate)
└── tests/                 # serializer / mapping / DSP / ADT tests + scan-chart round-trips
```

## Setup

```bash
python3 -m pip install numpy scipy pytest      # core (studio needs only numpy+scipy)
brew install ffmpeg                            # decode/normalize/encode audio (macOS)
cd tools/validation && npm install && cd -     # scan-chart gate (Node ≥24)
# OPTIONAL SOTA adapters (used by the studio-autocharter-v1 branch, auto-detected):
#   pip install demucs gdown beat-this
```

## Test

```bash
python -m pytest    # scan-chart / ffmpeg tests auto-skip if those tools are absent
```

> Source audio (`*.mp3`, …) and model weights (`*.th`) are **gitignored and never
> committed** — bring your own files; point the studio/CLI at a local path.

## Branches
- **`main`** — the beat-grid studio (current).
- **`studio-autocharter-v1`** — the full auto-charter: DrumSep per-drum engine,
  genre pattern mode + kick-from-audio hybrid, metal accuracy controls. Reference / resume point.
