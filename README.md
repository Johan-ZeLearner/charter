# charter

Turn an uploaded **mp3** into a **playable Clone Hero 4-lane Pro Drums** chart.

> Status: early build. The **symbolic backend** (GM-drum MIDI → `.chart`,
> validated against Clone Hero's own parser) works end-to-end with zero ML. The
> audio frontend (separation → transcription → beat tracking) is not built yet.

📚 **Design & source of truth:** [`docs/`](./docs/README.md) — start there. The
thesis, the 8-stage pipeline, the chart-format bible, and the MVP roadmap all
live in those documents. This README is just the build/run entry point.

## What works today (Phase 1–2 of the roadmap)

`GM-drum MIDI → DrumNote model → .chart + song.ini → scan-chart validation`

This is the deterministic, fully-testable half of the pipeline (docs/10 §0). It
is built first, on hand-made MIDI, so every Clone Hero format footgun — the
tom/cymbal inversion, opt-in 2× kick, `BPM×1000`, the `TS` exponent, illegal
same-color tom+cymbal collisions — is killed with **zero ML noise**.

## Layout

```
charter/
├── docs/                  # design source of truth (read docs/README.md first)
├── charter/               # the Python package
│   ├── drumnote/          # ◀ FORMAT FIREWALL: DrumNote model + .chart serializer + song.ini
│   ├── mapping/           # Stage 6: GM→CH table, collision resolver, 2× kick, SMF loader
│   ├── validate.py        # Python bridge to the scan-chart gate
│   └── cli.py             # `midi2chart` / `validate`
├── tools/validation/      # Node ≥24 — scan-chart subprocess (the canonical gate)
└── tests/                 # serializer/mapping unit tests + scan-chart round-trip
```

## Setup

```bash
# Python: no runtime deps; just pytest for the suite
python3 -m pip install pytest

# Node validation gate (the canonical Clone Hero acceptance check, needs Node ≥24)
cd tools/validation && npm install && cd -
```

## Use

```bash
# Generate the hand-made GM-drum MIDI fixtures (optional, for inspection)
python -m tests.fixtures.make_fixtures

# GM-drum MIDI -> Clone Hero song folder, then validate it
python -m charter.cli midi2chart tests/fixtures/basic_groove.mid out/basic --validate

# Validate any existing song folder against scan-chart
python -m charter.cli validate out/basic
```

`midi2chart` writes `notes.chart` + `song.ini` (drums = 4-lane Pro, Expert) and
prints review notes (collisions resolved, kicks marked 2×). `--validate` runs
scan-chart and asserts Clone Hero detects it as `fourLanePro`.

## Test

```bash
python -m pytest           # full suite; scan-chart round-trips auto-skip if Node is absent
```

The milestone (docs/10) is **a green scan-chart on a real song**:
`test_basic_groove_scanchart_detects_four_lane_pro`.
