# Pipeline Architecture

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** The end-to-end, 8-stage map of the mp3 → playable Clone Hero Pro Drums chart pipeline — the spine every other technical doc hangs off.

## Related docs
- [Chart Format Reference](./03-chart-format-reference.md) — `.chart`/`.ini` syntax, tom/cymbal inversion, tick math, the serializer contract.
- [Drum Transcription](./05-drum-transcription.md) — separation, onset, lane classification, velocity (Stages 1–4 internals).
- [Tech Stack & Deployment](./08-tech-stack-and-deployment.md) — repos, licenses, polyglot runtime, Apple-Silicon paths.

---

## What this pipeline is (and is not)

Charter turns an uploaded mp3 into a Clone Hero **4-lane Pro Drums** chart that is **instantly playable**, plus a few minutes of Moonscraper cleanup to be sharable. **This is a TRANSCRIPTION problem — reproduce what the drummer actually played** — not a creative-choreography problem like Beat Saber. That single framing is why the whole thing collapses to "ADT + format mapping," both of which have strong off-the-shelf components.

**DECIDED:** The realistic target is *"AI draft that is instantly playable + a few minutes of Moonscraper cleanup,"* NOT flawless hand-charter quality. End-to-end drum accuracy lands around STRUM's **~0.84 F1 at ±100ms** — roughly **1 in 6 events missing or mis-placed**, concentrated in (a) busy fills, (b) two-cymbal ride+crash sections, and (c) quiet ghost notes. The one thing guaranteed fully automatically is **format validity**: we gate on Clone Hero's own parser, so the game loads and parses it as 4-lane Pro every time.

---

## The 8-stage pipeline

Each stage below states: **purpose · input→output · recommended tool · why**. Stage internals live in the per-stage docs — keep this page the map. Tool maturity caveats (no tagged release, unreleased code, synthetic→real domain gap) are flagged here and carried in full in [Tech Stack & Deployment](./08-tech-stack-and-deployment.md).

### Stage 0 — Ingest, decode, loudness-normalize
- **Purpose:** Turn an arbitrary user mp3 into a clean canonical PCM working copy and harvest metadata for `song.ini`, so every later stage sees identical, loudness-normalized audio.
- **In → Out:** User `mp3` (any bitrate/tags) → `work.wav` (44.1kHz stereo float) + `work_22k.mono.wav` (22050Hz mono, the STRUM/ADT/Beat-This native rate) + tags `{title, artist, album, year, length_ms}` as JSON.
- **Tool:** **FFmpeg** + **pyloudnorm** (or `ffmpeg loudnorm`, ITU-R BS.1770-4) + **Mutagen** for ID3.
- **Why:** Every downstream model expects normalized PCM; the QMUL ADT recipe specifically applies ReplayGain/BS.1770 normalization before transcription and it materially helps onset/velocity stability. Tags pre-fill `song.ini`; missing tags fall back to filename parsing then `Unknown Artist`. Fully automatic and reliable.
- Details in [Drum Transcription](./05-drum-transcription.md) (audio prep) and [Tech Stack & Deployment](./08-tech-stack-and-deployment.md) (FFmpeg/libopus).

### Stage 1 — Drum-stem source separation
- **Purpose:** Isolate the cleanest possible drum stem from the full mix. This stage gates everything downstream.
- **In → Out:** `work.wav` → `drums.stem.wav` (+ other stems kept for reuse as CH audio) + `drum_stem_RMS` scalar.
- **Tool:** **Mel-Band RoFormer / BS-RoFormer** drum checkpoint via **`audio-separator`** (pip, MIT; CoreML on Apple Silicon / CUDA / CPU). Fallback: **Demucs v4 `htdemucs_ft`** (pip, MIT, no-GPU). Optional cloud "max quality" tier: **MVSEP** drum ensemble (~14.3 dB).
- **Why:** Single biggest cheap quality lever — a drum stem gives **~+15 F-measure** for ADT vs full mix (~0.65 → ~0.80). RoFormer beats Demucs on drums by ~0.5–3 dB SDR; Demucs is the trivial-install fallback only. **RISK:** RoFormer can *smear* dense cymbal/hi-hat transients even at high SDR — score the separator on onset/transient preservation, not the SDR leaderboard number, because a softened cymbal attack makes the blue/green problem *worse*. `drum_stem_RMS` feeds the soft quality gate (STRUM screened at RMS ≥ 0.018; only ~63% of songs passed) — we do **not** block, we propagate a low-confidence flag.
- Details in [Drum Transcription](./05-drum-transcription.md).

### Stage 2 — Per-drum split (disambiguation signal only)
- **Purpose:** Produce per-instrument sub-stems whose spectral energy at each onset acts as the **arbiter** for the hardest lane calls: tom-vs-cymbal, ride-vs-crash, open-vs-closed hat.
- **In → Out:** `drums.stem.wav` → `kick.wav, snare.wav, toms.wav, cymbals.wav` (+ `hh/ride/crash` if 6-stem). Used **only** as per-onset energy features, never as final audio.
- **Tool:** **DrumSep** (inagoy, MIT; kick/snare/toms/cymbals, auto-cascades from a drum stem). Optional: **Jarredou MDX23C 6-stem** to split cymbals into hi-hat/ride/crash.
- **Why:** This is the **tom-vs-cymbal arbiter**. The worst-scoring lane (STRUM blue, high-tom vs ride, **0.19** per-class accuracy) is attacked by cross-checking the classifier against which sub-stem actually carries spectral energy at each onset. **RISK:** cascade compounds errors (stem-of-a-stem) and StemGMD-trained models have a synthetic→real domain gap — treat sub-stems as a **soft vote / tie-breaker, never ground truth**, never let them override a confident classifier alone. **DECIDED:** the 6-stem Jarredou model is what makes ride-vs-crash tractable; keep it optional.
- Details in [Drum Transcription](./05-drum-transcription.md).

### Stage 3 — Beat tracking, downbeat, tempo map + structure
- **Purpose:** Build the SyncTrack — a per-beat tempo map and time-signature changes, plus song structure to modulate difficulty and place fills/star-power. Timing correctness lives or dies here.
- **In → Out:** `work_22k.mono.wav` (drum stem and/or full mix) → `beats[]` + `downbeats[]` times, `tempo_map` (one `(tick, BPM)` per beat interval via `60/(t[i+1]-t[i])`), inferred time-signature changes, `segments[]` (intro/verse/chorus/break/fill).
- **Tool:** **Beat This!** (`beat-this`, pip, MIT, `final0` checkpoint) for beats+downbeats. **allin1** in parallel for functional segments + a `beat_positions` cross-check. **mido/pretty_midi** for tempo-map math.
- **Why:** Beat This! is no-DBN SOTA (beat F1 ~95–97 on pop/rock), handles tempo changes and odd meters, and has **no madmom dependency** (madmom is abandoned, a Python-3.9 trap, with commercial-use caveats). **DECIDED:** the tempo map is non-negotiable — **a single global BPM is the #1 cause of unplayable charts** on any tempo-drifting song; we compute the *map* ourselves from inter-beat intervals (Beat This! and allin1 only give times / a rounded int BPM). **RISK:** downbeat F1 tops out ~78% on hard material → wrong bar-1 / time signature silently shifts every fill and star-power phrase. **OPEN:** the research says expose a manual override for bar-1/meter; a true zero-edit pipeline can't, so we cross-check Beat This! vs allin1 and raise a "verify meter" flag on disagreement.
- Details in [Chart Format Reference](./03-chart-format-reference.md) (SyncTrack/tick math).

### Stage 4 — Onset detection + lane classification + velocity (the ADT core)
- **Purpose:** For each drum onset decide WHEN (precise time) and WHAT (kick, snare/red, hi-hat/yellow, hi-tom, mid-tom, crash, ride) plus a velocity estimate. The transcription heart.
- **In → Out:** `drums.stem.wav` + per-onset energy from Stage-2 sub-stems → `events[] = {time_s, class, isCymbal, velocity 1–127, confidence}`.
- **Tool:** **STRUM** (`opria123/strum`, MIT) drum chain as the reference engine — 2-stage CRNN onset detector (mel, 22.05k, 128 bins) + 6-model lane-classifier ensemble + tom-refinement CNN. Cross-check with **ADTOF** (5-class CRNN, ~0.85–0.89 F) as an independent backbone. Velocity: **Noise-to-Notes** diffusion (E-GMD velocity F 0.80) if code releases, else **Magenta OaF-Drums** (E-GMD), else **per-stem-loudness** (equal-loudness + RMS in ~50ms window on the matching sub-stem).
- **Why:** STRUM is purpose-built for CH drums and reports the best end-to-end drum F1 (**0.838**). **DECIDED:** invest in onset detection *first* — it is a hard recall ceiling (**~89%** of true hits fall within ±100ms of *any* detected onset; onset F1 ~0.94 at ±50ms), and classification is secondary. **DECIDED:** velocity is not optional for Pro Drums — Magenta's listening study showed predicting velocity nearly doubled perceptual-quality wins (919 vs 456); it is what makes ghost/accent feel right. **RISK (the worst one):** ride-vs-crash and high-tom-vs-ride are genuinely song-dependent; even with the Stage-2 arbiter, busy two-cymbal passages will be visibly wrong — bias low-confidence calls toward the SAFE choice (TOM) and emit per-region confidence so those bars are flagged. **CAVEAT:** STRUM has ~6GB model download and no tagged release — verify runnability.
- Details in [Drum Transcription](./05-drum-transcription.md).

### Stage 5 — Tempo-aware quantization
- **Purpose:** Snap raw onset times to a subdivided beat grid so notes are actually hittable, without destroying swing/fills.
- **In → Out:** `events[]` (Stage 4) + `tempo_map`/`beats[]` (Stage 3) → events snapped to ticks at `Resolution=192`, with a per-region grid resolution chosen.
- **Tool:** Custom quantizer over Beat This! `beats[]` (interpolate N subdivisions per beat) + per-segment swing/triplet detector (onset-histogram clustering at 1/3, 2/3).
- **Why:** **DECIDED:** snap to a **subdivided beat grid that follows the tempo curve, never a fixed-BPM grid** — 16ths default, 32nds for fast double-kick, triplet grids only where swing is detected. Two-stage: hard-snap to straight 16ths, then apply a swing template only in detected-swing regions (a global triplet grid mangles straight sections). Snap at **~100% strength** — the opposite of music-production's 80% advice — because off-grid notes are literally unhittable in CH. Beat This! frame resolution is ~20ms, so fine hit timing comes from Stage-4 onsets, *then* gets snapped here. Main residual artifact: over-quantizing genuine fills.
- Details in [Chart Format Reference](./03-chart-format-reference.md) (tick resolution).

### Stage 6 — GM → Clone Hero mapping, Pro-Drums semantics, difficulty reduction
- **Purpose:** Convert 7-class events into the fixed CH lane model (kick + red/yellow/blue/green with per-color cymbal/tom flag and dynamics), resolve illegal collisions, infer 2x kick, and derive Hard/Medium/Easy from the Expert master.
- **In → Out:** quantized `events[]` (class + isCymbal + velocity) → in-memory **DrumNote** model for Expert + derived Hard/Medium/Easy.
- **Tool:** **apvilkko/midi2clonehero** mapping table (configurable, not hardcoded) + windowed crash/ride collision resolver + same-tick tom/cymbal validator + 2x-kick gap heuristic + **eerovil/EasyChartGenerator** `notes_to_diff_drums` reducer logic. Optionally **Fureniku/Drum-MIDI-To-Clone-Hero-Converter** for the MIDI→.chart leg (Pro markers + auto 2x kick, Java).
- **Why:** This is the well-trodden, deterministic, rule-based symbolic path (no production ML mapper exists). Canonical map: kick←35/36; red←snare 37–40; toms high→low into yellow/blue/green TOM; hi-hats 42/44/46→yellow cymbal; crash1/splash/china 49/52/55→blue cymbal; ride/bell/crash2 51/53/57/59→green cymbal. Velocity gate: ghost ≤60, accent ≥120 (configurable). **DECIDED (hard constraint):** a tom and cymbal of the *same color* cannot share a tick — a windowed resolver flips blue↔green or drops. **DECIDED:** 2x kick is **inferred** (~150ms inter-kick gap, Expert only, gap scales with tempo) and **opt-in / collapsed to single kick** on lower difficulties. **RISK:** the gap heuristic over-fires on fast single-foot 16ths and under-fires when the separator smears kick transients — there is no audio feature that cleanly says "two feet"; mark inferred 2x runs for review. The 6 GM tom pitches bucket lossily into 3 CH tom lanes.
- Details in [Chart Format Reference](./03-chart-format-reference.md) (the full mapping table & Pro-Drums semantics).

### Stage 7 — Serialize to `.chart` + `song.ini` + audio
- **Purpose:** Emit the canonical Clone Hero song folder.
- **In → Out:** DrumNote model + tempo_map + tags + segments → song folder: `notes.chart`, `song.ini`, `song.opus` (+ optional `drums_1..4` stems).
- **Tool:** Custom **.chart serializer** (the ONE place the tom/cymbal inversion lives) + `song.ini` writer + **FFmpeg/libopus** for `song.opus` (~80kbps).
- **Why:** **DECIDED — emit `.chart`, not `.mid`.** It is plaintext, tick-based (`Resolution=192`), CH/YARG-native, and **toms-are-default matches Moonscraper** — so cymbals are opt-in flags (66/67/68), the safer authoring direction. `.mid` is drums-as-cymbals-default (tom markers 110/111/112, requires `[ENABLE_CHART_DYNAMICS]`) — only emit it if Rock Band ecosystem interop becomes a hard requirement. Dynamics: accent 34–38 / ghost 40–44; 2x kick as type 32; star-power phrases (`S 2`) and fill/activation phrases (`S 64`, the only phrase including its final tick) from segments. Set `pro_drums=True`, `five_lane_drums=False`, include ≥1 cymbal marker (or the whole chart reads as all-toms), and **bake offset into the chart** (avoid `delay`, which breaks the leaderboard hash). `song.opus` defaults to the original mix so the chart always plays against real audio.
- Details in [Chart Format Reference](./03-chart-format-reference.md) (the authoritative serializer spec).

### Stage 8 — Validation gate against Clone Hero's own parser
- **Purpose:** Guarantee the game accepts the chart and detects 4-lane Pro **before** returning to the user — closing the loop so "does CH accept this" is provable, not hoped.
- **In → Out:** song folder → validation report `{drumType, per-difficulty note counts, NPS, parser-issue list, track hash}` + pass/fail + per-region confidence overlay.
- **Tool:** **Geomitron/scan-chart** (TypeScript, byte-matches CH's parser, validated on 40k charts) run via a Node subprocess. Optional deeper QA: **Moonscraper Song Validator** / **Editor on Fire (EOF)**.
- **Why:** This makes "will the game accept this and detect Pro drums" a **solved, testable gate**. **DECIDED:** treat scan-chart's `drumType` as ground truth — if it reports anything but `'4-lane Pro'`, we mis-emitted the cymbal/tom flags and fail fast. Assert zero blocking parser issues and sane (non-zero, non-over-dense) note counts before publishing. This guarantees acceptance and leaderboard-hash parity. **Requires a Node ≥24 runtime alongside Python** — a deployment dependency, not a quality risk.
- Details in [Tech Stack & Deployment](./08-tech-stack-and-deployment.md) (Node subprocess wiring).

---

## Data-flow diagram

```
                         ┌──────────────────────────────────────────────────────────┐
                         │                    ML FRONT-HALF (Python)                  │
                         │            audio in → symbolic events out                  │
                         └──────────────────────────────────────────────────────────┘

  user.mp3
     │
     ▼
 ┌──────────┐   work.wav (44.1k stereo) ┌──────────────┐ drums.stem.wav  ┌──────────────┐
 │ Stage 0  │   work_22k.mono.wav       │   Stage 1    │  + other stems  │   Stage 2    │ kick/snare/
 │ INGEST   │──────────────────────────▶│ STEM SEP     │────────────────▶│ PER-DRUM     │ toms/cymbals
 │ normalize│   tags{} (JSON)           │ RoFormer     │  drum_stem_RMS  │ SPLIT (arbiter)│ sub-stems
 └──────────┘                           │ (Demucs f/b) │                 │ DrumSep      │ (soft vote)
      │                                 └──────┬───────┘                 └──────┬───────┘
      │                                        │                                │
      │ work_22k.mono.wav                      │ drums.stem.wav                 │ per-onset energy
      ▼                                        ▼                                ▼
 ┌──────────────┐ beats[] downbeats[]   ┌──────────────────────────────────────────────┐
 │   Stage 3    │ tempo_map (per-beat)  │                  Stage 4                       │
 │ BEAT/TEMPO/  │ time_sig segments[]   │   ONSET + LANE CLASSIFY + VELOCITY (ADT core)  │
 │ STRUCTURE    │──────────┐            │   STRUM ⟂ ADTOF cross-check · velocity         │
 │ Beat This! / │          │            │   events[]={time_s,class,isCymbal,velocity,conf}│
 │ allin1       │          │            └───────────────────────┬────────────────────────┘
 └──────────────┘          │                                    │ events[]
                           │ tempo_map / beats[]                ▼
                           └──────────────────────────▶ ┌──────────────┐ ticks @ Res=192
                                                        │   Stage 5    │ per-region grid
                                                        │ QUANTIZE     │ (16th/32nd/triplet)
                                                        │ subdivided   │
                                                        │ beat grid    │
                                                        └──────┬───────┘
  ═══════════════════════════════════════════════════════════ │ ═══════════════════════════
                         ┌────────────────────────────────────▼─────────────────────────┐
                         │            SYMBOLIC BACK-HALF (testable with ZERO ML)          │
                         └────────────────────────────────────┬─────────────────────────┘
                                                               ▼
 ┌──────────────┐  DrumNote[] (Expert      ┌──────────────┐  song folder    ┌──────────────┐
 │   Stage 6    │  + Hard/Medium/Easy)     │   Stage 7    │  notes.chart    │   Stage 8    │
 │ GM→CH MAP    │─────────────────────────▶│ SERIALIZE    │  song.ini       │ VALIDATE     │
 │ collisions   │  {lane,isCymbal,         │ .chart/ini/  │  song.opus      │ scan-chart   │
 │ 2x-kick      │   isKick2x,dynamic,      │ audio        │────────────────▶│ (Node ≥24)   │
 │ difficulty   │   difficulty,tick}       │              │                 │ assert Pro   │
 └──────────────┘                          └──────────────┘                 └──────┬───────┘
                                                                                   │
                                                                  PASS (drumType=='4-lane Pro',
                                                                  note counts OK, 0 issues) +
                                                                  confidence/REVIEW overlay
                                                                                   ▼
                                                                          Clone Hero song folder
                                                                          (+ optional Moonscraper
                                                                           cleanup handoff)
```

The double line (`═══`) marks **the architectural seam** between the ML front-half and the symbolic back-half. See below.

---

## The central intermediate data model: `DrumNote`

`DrumNote` is the **contract every stage agrees on**. Stages 0–5 produce the audio-derived `events[]`; Stage 6 maps those into a list of `DrumNote` objects; Stage 7 serializes *only* `DrumNote`. Every format gotcha (tom/cymbal inversion, BPM×1000, TS-exponent, illegal same-color collisions, opt-in 2x kick) is isolated to the DrumNote → `.chart` serializer — fixed once, traceable to the spec.

| Field        | Type / domain                                   | Meaning & rules |
|--------------|-------------------------------------------------|-----------------|
| `tick`       | int, on the `Resolution=192` grid               | Quantized position from Stage 5. Tick math (BPM×1000, TS-exponent) is the serializer's job, not this model's. |
| `lane`       | enum `{kick, red, yellow, blue, green}`         | The CH pad/foot. Toms map high→low into yellow/blue/green; snare→red; kick is the foot lane. |
| `isCymbal`   | bool                                            | **The inversion lives here, not in the model.** `.chart` defaults toms; serializer emits cymbal flags 66/67/68 only when `isCymbal=true`. Same-color tom + cymbal on one `tick` is **format-illegal** — the Stage-6 collision resolver guarantees this never reaches serialization. |
| `isKick2x`   | bool                                            | Inferred double-kick (~150ms gap, **Expert only**). Serialized as type 32. **Collapsed to single kick on Hard/Medium/Easy.** Opt-in; default single-pedal. |
| `dynamic`    | enum `{ghost, normal, accent}`                  | From Stage-4 velocity. Gate: ghost ≤60, accent ≥120 (configurable). Serialized as accent 34–38 / ghost 40–44. Ghosts kept on lower diffs; accents dropped. |
| `velocity`   | int 1–127 (optional, source of `dynamic`)       | Raw per-note velocity carried through for fidelity; `dynamic` is the bucketed view the serializer uses. |
| `difficulty` | enum `{Expert, Hard, Medium, Easy}`             | Which `[<Diff>Drums]` track this note belongs to. Expert is the master; Hard/Medium/Easy are derived by the EasyChartGenerator-style reducer. |
| `confidence` | float 0–1 (optional, per-region)                | Carried from Stages 1/3/4 (RMS gate, downbeat agreement, classifier confidence) to drive the "needs review" overlay. Not part of the chart; part of the honest UX. |

**ASSUMPTION:** the 7 ADT classes (`kick, snare/red, hi-hat/yellow, hi-tom, mid-tom, crash, ride`) collapse cleanly into the 5 `lane` values via the Stage-6 mapping table; the 6 GM tom pitches bucketing into 3 tom lanes is a known lossy judgment call carried in [Chart Format Reference](./03-chart-format-reference.md).

---

## Key architectural decision: decouple the symbolic back-half from the ML front-half

**DECIDED:** Build and debug the two halves **independently**, with `DrumNote` as the only contract between them.

- **Symbolic back-half (Stages 6–8): MIDI/`events` → DrumNote → `.chart` → scan-chart.** This is **testable with zero ML.** It is deterministic, rule-based, and grounded in published format spec + reusable repos (midi2clonehero table, EasyChartGenerator reducer, scan-chart). **Build this first**, on a hand-made GM drum MIDI (no audio at all): round-trip known fixtures through scan-chart + Moonscraper and assert `drumType == '4-lane Pro'`, hashes, and note counts. This isolates and kills the inversion, collision, and 2x-kick bugs with **zero ML noise**. A green scan-chart on a real song is the true MVP milestone — it proves the format + validation loop end-to-end.
- **ML front-half (Stages 0–5): audio → `events[]`.** Probabilistic, heavy dependencies, the source of all accuracy uncertainty. Wired in *after* the back-half is solid, starting with easy fallbacks (Demucs → ADTOF → Beat This!) and upgraded stage-by-stage (RoFormer, DrumSep arbiter, velocity, allin1 segments), A/B-measured against per-class accuracy in CI before each heavier dependency is committed.

The seam means a format bug can never be confused with a transcription bug, and either half can be replaced without touching the other. The serializer is the single point where every format footgun is contained.

---

## Polyglot deployment note

**DECIDED:** This is a polyglot system. Plan for two mandatory runtimes and deliberately route around a third.

- **Python** — all ML stages (separation, ADT, beat tracking) and the symbolic mapping/serialization. Runs offline on CPU / Apple-Silicon (CoreML) / CUDA, with an opt-in cloud "max quality" tier.
- **Node ≥ 24 (mandatory)** — the Stage-8 scan-chart validation gate is TypeScript and must run as a Node subprocess. The validation gate is non-negotiable, so this dependency is non-negotiable.
- **Java (route around it)** — only Fureniku/Drum-MIDI-To-Clone-Hero-Converter is Java. **DECIDED:** reproduce its behavior via the Python `apvilkko/midi2clonehero` mapping table + our own serializer rather than shipping a JVM. Java stays optional and unused in the default build.

Details, exact versions, install paths, and license notes in [Tech Stack & Deployment](./08-tech-stack-and-deployment.md).

---

## Open questions / TODO

- **OPEN:** Verify **STRUM** (`opria123/strum`) actually runs — ~6GB model download, **no tagged release** — and benchmark it on Apple Silicon vs the ADTOF fallback before committing it as the reference engine.
- **OPEN:** **Noise-to-Notes** diffusion velocity model had **no public code** at research time; the velocity-best path may require reimplementation or the OaF / per-stem-loudness fallback until weights ship.
- **OPEN:** Confirm the RoFormer drum checkpoint via `audio-separator` runs on the CoreML path on Apple Silicon and that its transient preservation (not SDR) actually improves onset F-measure over `htdemucs_ft` on a real song.
- **OPEN:** Bar-1 / time-signature override — downbeat F1 ~78% means meter is the least reliable output; the research recommends manual override, which a zero-edit pipeline can't provide. Decide where the flag-vs-block line sits.
- **OPEN:** Double-kick inference is a heuristic, not a measurement; the ~150ms gap (even tempo-scaled) over-/under-fires. Open whether a kick-stem onset-density model can distinguish one fast foot from two.
- **OPEN:** Confidence model precision/recall — does the "needs review" overlay flag the *right* regions? Track per-class lane accuracy (Kick/Red/Yellow/Blue/Green separately, plus tom-vs-cymbal and ghost recall) in CI from day one.
- **RISK:** Lossy-mp3 transient degradation on cymbals is unquantified in the cited benchmarks (which mostly use clean stems); real-world mp3 input may underperform the published ~0.84 by an unknown margin.
- **RISK:** Commercial licensing — LarsNet weights are CC BY-NC, the best MVSEP ensembles are paid cloud with audio upload (IP/privacy), and madmom (if pulled transitively) has commercial-use caveats. A fully-offline commercial build must accept the `htdemucs_ft` quality floor or retrain per-drum separators on CC-BY StemGMD.
