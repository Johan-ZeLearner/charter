# Tech Stack & Deployment Reality

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** The single consolidated table of every repo/package the pipeline depends on (with license + maturity caveats), plus the honest polyglot deployment story (Python + Node≥24, route around Java), hardware paths, and suggested repo layout.

## Related docs
- [Pipeline Architecture](./02-pipeline-architecture.md)
- [Source Separation](./04-source-separation.md)
- [MVP Roadmap](./10-mvp-roadmap.md)

---

## 1. How to read this doc

This is the **dependency contract** for the build. Every tool below is named in the research synthesis (the final brief tech-stack table) and the three candidate designs. The pipeline turns an uploaded mp3 into a **playable Clone Hero Pro Drums `.chart`**; this doc is where a fresh agent confirms *what to install, what license it carries, and what is likely to break*.

Two framing rules carried from the source material:

- This is a **transcription** problem (reproduce what the drummer played), not creative choreography. That is why off-the-shelf ADT + a symbolic mapper is enough — see [Pipeline Architecture](./02-pipeline-architecture.md).
- The honest deliverable is **"AI draft that is instantly playable + a few minutes of Moonscraper cleanup"**, never hand-charter quality. The one thing guaranteed fully automatically is **format validity** (scan-chart confirms CH loads it as 4-lane Pro every time).

**DECIDED:** This is **research-grounded design, not yet-built code.** Every ML repo below is a *candidate/recommended* with a maturity caveat. Several are explicitly flagged as **not turnkey** — those caveats are load-bearing and must survive into the build.

---

## 2. The consolidated tech-stack table

Each row maps to a pipeline stage (Stage 0–8 in [Pipeline Architecture](./02-pipeline-architecture.md)). The **Notes / caveats** column is where the **RISK:** flags live — read them before you `pip install`.

| Concern (stage) | Repo / package | License | Notes / caveats |
|---|---|---|---|
| **Format spec** (vendor it) | `TheNathannator/GuitarGame_ChartFormats` | docs | **DECIDED: vendor it.** Pull `Drums.md` (.chart + .mid), `Standard-Tags.md`, `Supported-Audio-Files.md` into the repo so every mapping decision is citable to the spec. Not code — it is the ground truth the serializer is verified against. |
| **Stem separation — SOTA** (Stage 1) | `nomadkaraoke/python-audio-separator` (a.k.a. `audio-separator`, loads Mel-Band / BS-RoFormer drum ckpts) | MIT | pip-installable; **Apple-Silicon CoreML path** + CUDA + CPU. Default = a RoFormer drum checkpoint (`mel_band_roformer`, drum-specialized, ~sdr_11.4 / MUSDB drums SDR ~11.6–11.8). **RISK:** RoFormer can **smear/hallucinate cymbal & hi-hat transients even at high SDR** — optimize for *onset/transient preservation*, not the SDR leaderboard number; a high-SDR stem that softens attacks makes the blue/green lane problem worse. See [Source Separation](./04-source-separation.md). |
| **Stem separation — fallback** (Stage 1) | `demucs` (`htdemucs_ft`) | MIT | pip, **offline, no-GPU**. The trivial-install MVP default. Beaten by RoFormer/SCNet on drums (MUSDB drums SDR ~11.1 vs ~11.6–11.8; ~+0.5–3 dB) but kept as the no-GPU floor. Note: STRUM ships with `htdemucs_6s` internally — we deliberately diverge and swap in RoFormer. |
| **Stem separation — cloud max-quality** (Stage 1, optional) | MVSEP drum ensemble (API) | paid cloud | Optional "max quality" tier (~14.3 dB). **RISK:** paid cloud + **audio upload (IP / privacy)** — incompatible with a fully-offline commercial build. Opt-in toggle only. |
| **Per-drum split** (Stage 2) | `inagoy/drumsep` | MIT | Hybrid-Demucs; auto-cascades from the drum stem into 4 sub-stems (kick/snare/toms/cymbals). Sub-stems are used **only** as a per-onset spectral-energy *arbiter*, never as final audio. **RISK:** stem-of-a-stem **cascades error**; StemGMD-trained per-drum models carry a **synthetic→real domain gap** on acoustic kits — treat as a soft vote, never ground truth. |
| **Per-drum split — 6-stem** (Stage 2, optional) | Jarredou MDX23C 6-stem DrumSep | — (verify) | Splits cymbals into hi-hat / ride / crash — the signal that makes **ride-vs-crash (green/blue collision) tractable**. **OPEN:** confirm license + availability. **RISK:** **LarsNet weights are CC BY-NC** (non-commercial); a commercial offline build must retrain per-drum separators on **CC-BY StemGMD** and accept the `htdemucs_ft` quality floor. |
| **Beat / downbeat** (Stage 3) | `CPJKU/beat_this` (`beat-this`) | MIT | `final0` checkpoint. No-DBN SOTA (Beat F1 ~95–97 on pop/rock); handles tempo changes & odd meters. **DECIDED: chosen specifically because it has no `madmom` dependency.** Outputs **times only** — we compute the per-beat tempo map ourselves via `60/(t[i+1]-t[i])`. |
| *(avoid)* | `madmom` | — | **RISK: avoid.** Abandoned, a **Python-3.9 dependency trap**, has **commercial-use caveats**, and can be pulled in *transitively* — audit your dep tree for it. Beat This! exists to route around it. |
| **Structure / segments** (Stage 3) | `mir-aidj/all-in-one` (`allin1`) | MIT | Functional segments (intro/verse/chorus/break/fill) for fill placement, star-power, difficulty modulation + a downbeat cross-check against Beat This!. **RISK:** needs **NATTEN + Demucs** (heavier install); if it fails, degrade to Beat-This-only with assumed 4/4. Its scalar `bpm` is a single rounded int — **do not use it for the SyncTrack**; derive the map from `beats[]`. |
| **ADT engine — CH-tuned** (Stage 4) | `opria123/strum` | MIT | The reference engine: 2-stage CRNN onset detector (mel, 22.05k, 128 bins) + 6-model OnsetClassifier ensemble + tom-refinement CNN. Best reported end-to-end drum F1 (**0.838 @ ±100ms**); purpose-built for CH drums. **RISK:** **~6 GB model download, NO tagged release — verify it actually runs** before depending on it. **RISK:** documented worst lanes (blue 0.19 / snare 0.44 / yellow 0.49 per-class accuracy) — the central playability defect, not a bug we can patch out. |
| **ADT cross-check** (Stage 4) | `MZehren/ADTOF` (or ADTOF-pytorch) | — (verify) | Independent **5-class** CRNN backbone, ~0.85–0.89 F; pip, CLI `drumTranscriptor`, emits MIDI. The easy-fallback ADT for the weekend MVP. **RISK:** collapses crash/ride/splash into one "cymbals" class and **released models emit no velocity** — pushes disambiguation + velocity downstream. **OPEN:** confirm license. |
| **Velocity — best** (Stage 4) | Noise-to-Notes (N2N) diffusion | research | Joint onset+velocity (E-GMD onset 86.3 / velocity F 0.80–80.2). **RISK: NO public code at search time** — reimplement or wait for weights; do not assume drop-in availability. |
| **Velocity — proven** (Stage 4) | Magenta Onsets-and-Frames Drums (OaF, E-GMD) | — (verify) | The proven fallback when N2N is unavailable. **RISK: TF1-era, brittle install.** Magenta's listening study: predicting velocity **nearly doubled** perceptual-quality wins (919 vs 456) — velocity is *not optional* for Pro Drums ghost/accent feel. |
| **Velocity — fallback** (Stage 4) | (none — derive from Stage-2 sub-stems) | — | Per-stem loudness: equal-loudness filter + RMS in a ~50 ms window on the matching sub-stem (QMUL recipe). Always available, **approximate**, and only as good as the per-drum split. |
| **GM→lane map** (Stage 6) | `apvilkko/midi2clonehero` | — (verify) | Reference mapping table (**configurable, not hardcoded**) + collision flipper. Canonical map: kick←35/36; red←snare 37–40; toms high→low into yellow/blue/green TOM; hats 42/44/46→yellow cymbal; crash1/splash/china 49/52/55→blue cymbal; ride/bell/crash2 51/53/57/59→green cymbal; ghost ≤60 / accent ≥120. **OPEN:** confirm license. |
| **MIDI→.chart** (Stage 6/7, optional) | `Fureniku/Drum-MIDI-To-Clone-Hero-Converter` | — (verify) | Pro-Drums markers + auto 2x-kick on the MIDI→.chart leg. **Written in Java.** **DECIDED: route around it** — reimplement the same logic via the Python `midi2clonehero` table so the build stays Python+Node. Keep as a reference oracle, not a runtime dep. |
| **Difficulty reduction** (Stage 6) | `eerovil/EasyChartGenerator` | — (verify) | Port the `notes_to_diff_drums` drum reducer (per-beat thinning) for Hard/Medium/Easy. The drum reducer differs from the guitar one (kick/cymbal semantics). **OPEN:** confirm license. |
| **MIDI / tempo math** (Stages 3–7) | `mido`, `pretty_midi` | MIT | Tempo-map serialization, tick↔seconds math over the SyncTrack. Stable, mature. |
| **Validation gate** (Stage 8) | `Geomitron/scan-chart` | — (verify) | **TypeScript, byte-matches CH's parser, validated on 40k charts.** Run via a **Node≥24 subprocess**. Asserts `drumType == '4-lane Pro'`, note counts, parser-issue list, leaderboard track hash. **DECIDED: this is the day-one gate** — "does CH accept this and detect Pro drums" becomes a passing test. **OPEN:** confirm license / packaging. |
| **Validation — deeper QA** (Stage 8, optional) | Moonscraper Song Validator / Editor on Fire (EOF) | — | Optional legality oracle for round-trip QA. Moonscraper is also the **canonical human-cleanup editor** (opens `.chart` directly). |
| **Audio encode** (Stage 0/7) | FFmpeg + libopus | LGPL/GPL (FFmpeg) | Decode mp3→wav, loudness probe, `song.opus` (~80 kbps), optional `drums_1..4` stems. Plus `pyloudnorm` / `ffmpeg loudnorm` (ITU-R BS.1770-4) and `Mutagen` for ID3 tags at ingest. |

**ASSUMPTION:** rows marked "— (verify)" in the License column are assumed permissively licensed based on their community/open-source origin, but the exact license is **unconfirmed** in the source material. A maintainer must verify each before any commercial use. (Confirmed MIT: audio-separator, demucs, drumsep, beat_this, allin1, strum, mido, pretty_midi.)

---

## 3. RISK roll-up — the five "not turnkey" dependencies

These are the rows most likely to block a fresh agent. Surface them early.

| Tool | The risk in one line | Mitigation |
|---|---|---|
| **STRUM** | ~6 GB model, **no tagged release** — may not run as-is | Verify runnability on day one; ADTOF is the independent fallback backbone |
| **OaF-Drums** | **brittle TF1-era install** | Prefer N2N (when it ships) or per-stem-loudness; isolate OaF in its own venv/container |
| **Noise-to-Notes** | **no public code** at search time | Budget reimplementation or fall back to OaF / loudness — do not assume drop-in |
| **madmom** | abandoned, Py-3.9 trap, commercial caveats — pulled in **transitively** | **Avoid.** Beat This! routes around it; audit the dep tree to confirm it's absent |
| **Fureniku converter / LarsNet / MVSEP** | **Java** dep / **CC BY-NC** weights / **paid cloud upload** | Route around Java via Python `midi2clonehero`; use CC-BY StemGMD for commercial; keep MVSEP opt-in |

---

## 4. Polyglot deployment reality

This pipeline is **polyglot by necessity.** A fresh agent should expect three language runtimes and one isolation boundary.

```
┌──────────────────────────────────────────────────────────────────┐
│  PYTHON (the ML + orchestration body)                              │
│   FFmpeg/Mutagen ingest · audio-separator/demucs · drumsep ·       │
│   beat_this · allin1 · STRUM/ADTOF · OaF/N2N velocity ·            │
│   mido/pretty_midi · midi2clonehero table · EasyChartGenerator     │
│   logic · DrumNote model · .chart serializer · song.ini writer     │
│                                                                    │
│   ── subprocess ──▶  NODE ≥ 24  (scan-chart validation gate)       │
│                       MANDATORY. The only hard non-Python runtime. │
│                                                                    │
│   ── route AROUND ──  JAVA  (Fureniku converter) — NOT a runtime   │
│                       dep; reimplemented in Python.                │
└──────────────────────────────────────────────────────────────────┘
```

- **Python** is the ML body and the orchestrator. All heavy models (separation, ADT, beat) run here and run **offline on CPU / Apple-Silicon**.
- **Node ≥ 24 is mandatory.** The `scan-chart` validation gate is TypeScript that byte-matches Clone Hero's own parser; it runs as a **Node subprocess**. There is no Python equivalent — re-implementing CH's parser would defeat the point (the gate's value *is* that it's the same code path the game uses). This is a **deployment dependency, not a quality risk**. **RISK:** the `node --version` must be ≥ 24 in every environment (CI, container, dev box) or the gate silently can't run.
- **Java is routed around.** Fureniku's converter (Pro markers + 2x kick) is reused only as a *reference oracle*; the actual runtime logic is the Python `midi2clonehero` table. **DECIDED: no Java in the runtime.**

### 4.1 The one isolation boundary: DrumNote + .chart serializer

**DECIDED:** every format gotcha is isolated to **one in-memory `DrumNote` model + one `.chart` serializer.** This is the single most important architectural decision in the build, and it is where a fresh agent should expect the bugs to concentrate. The serializer is the **only** place the following live:

- **The tom/cymbal inversion** — `.chart` defaults to **tom** (cymbals are opt-in via flags `66/67/68`); `.mid` defaults to **cymbal** (toms opt-in via `110/111/112`). Getting this backwards silently corrupts *every* Pro chart. **DECIDED: emit `.chart`, not `.mid`** — simpler plaintext, CH/YARG-native, and toms-by-default matches Moonscraper, so cymbals are the opt-in flag (the safer authoring direction). Only emit `.mid` (with `[ENABLE_CHART_DYNAMICS]`) if Rock Band interop is a hard requirement.
- **TS-exponent and BPM×1000** SyncTrack encoding.
- **Illegal same-color collisions** — a tom and a cymbal of the same color **cannot share a tick**; a windowed resolver flips blue↔green or drops, every tick.
- **Opt-in 2x kick** (type 32), inferred via a ~150 ms inter-kick gap, **Expert only**, collapsed to single kick on lower difficulties.
- Constants: `Resolution=192`, `B` + `TS` markers at tick 0, accent `34–38`, ghost `40–44`, star-power phrases (`S 2`), fill/activation phrases (`S 64`).
- `song.ini`: `pro_drums=True`, `five_lane_drums=False`, real `diff_drums`, **no `delay`** (bake offset into the chart — `delay` breaks the leaderboard hash).

**DECIDED:** build and unit-test the `DrumNote` model + serializer **first and in isolation**, round-tripping hand-made GM MIDI fixtures through scan-chart + Moonscraper, *before* wiring any ML. This kills the inversion/collision/2x-kick bugs with zero ML noise. See [MVP Roadmap](./10-mvp-roadmap.md).

---

## 5. Hardware paths & rough runtime expectations

**Target dev/deploy hardware is Apple Silicon (M-series)**, with CPU fallbacks for everything so a no-GPU box still produces a chart.

| Stage | Apple Silicon path | CPU fallback | Notes |
|---|---|---|---|
| Separation (Stage 1) | **RoFormer via audio-separator → CoreML** | `htdemucs_ft` (Demucs v4, pip, no-GPU) | CoreML is the reason audio-separator is the chosen front-end; the fallback is the *trivial-install* path, not just the slow one. |
| Per-drum split (Stage 2) | drumsep (Hybrid-Demucs) on CoreML/MPS | drumsep on CPU | Cascades from the drum stem; cost is roughly a second separation pass. |
| Beat/structure (Stage 3) | beat_this `final0` on CPU/MPS; allin1 needs NATTEN | beat_this CPU; degrade to Beat-This-only 4/4 if allin1 fails | Beat This! runs fine **CPU on the M1**. |
| ADT (Stage 4) | STRUM / ADTOF on MPS/CPU | STRUM / ADTOF on CPU | STRUM is a ~6 GB download regardless of accelerator. |
| Velocity (Stage 4) | OaF (TF1, isolate) / per-stem loudness | per-stem loudness (numpy) | The loudness fallback is pure-CPU and always available. |
| Symbolic + serialize (Stages 6–7) | pure Python — negligible | pure Python — negligible | Deterministic, sub-second. |
| Validation (Stage 8) | Node ≥ 24 subprocess — negligible | same | CPU-bound parse of a small text file. |

**ASSUMPTION:** no exact wall-clock numbers are given in the source material — runtime is **dominated by the two separation passes (Stage 1 + Stage 2) and the ADT model load (STRUM ~6 GB)**, all of which are offline. Expect *minutes per song* on Apple Silicon, slower on pure CPU. **OPEN:** benchmark end-to-end per-song latency on the reference M-series box once the spine runs.

**DECIDED:** the heavy ML (separation, ADT, beat) all runs **offline** on CPU / Apple-Silicon; the only opt-in cloud is the MVSEP "max quality" tier.

---

## 6. Suggested repo layout & service boundaries

A monorepo with a clear Python/Node split and the serializer firewalled off. This is a **suggestion** for the build, grounded in the isolation decisions above — not a mandate.

```
charter/
├── docs/                      # these design docs (source of truth)
├── vendor/
│   └── GuitarGame_ChartFormats/   # vendored spec: Drums.md, Standard-Tags.md,
│                                  #   Supported-Audio-Files.md (citable)
├── charter/                   # the Python package (pipeline body)
│   ├── ingest/                # Stage 0: FFmpeg, pyloudnorm, Mutagen
│   ├── separation/            # Stage 1: audio-separator / demucs wrappers
│   ├── drumsplit/             # Stage 2: drumsep + spectral-energy arbiter
│   ├── timing/                # Stage 3: beat_this, allin1, tempo-map math
│   ├── adt/                   # Stage 4: STRUM / ADTOF + velocity (OaF/N2N/loudness)
│   ├── quantize/              # Stage 5: subdivided-grid + swing/triplet snap
│   ├── mapping/               # Stage 6: midi2clonehero table, collision resolver,
│   │                          #   2x-kick inference, EasyChartGenerator reducer
│   ├── drumnote/              # ◀ THE FIREWALL: DrumNote model + .chart serializer
│   │                          #   + song.ini writer (every format gotcha lives here)
│   ├── confidence/            # RMS gate, downbeat-agreement, per-region flags → REVIEW.md
│   └── cli.py                 # orchestration: mp3 → song folder
├── validation/                # Node ≥ 24 — scan-chart subprocess wrapper
│   ├── package.json           #   "engines": { "node": ">=24" }
│   └── validate.ts            #   asserts drumType=='4-lane Pro', counts, no issues
└── tests/
    └── fixtures/              # hand-made GM MIDI + golden .chart for serializer round-trips
```

**Service boundaries that matter:**

1. **`drumnote/` is a firewall.** Nothing else writes chart bytes. The tom/cymbal inversion, collisions, 2x-kick, and song.ini quirks exist *only* here, verified against `vendor/GuitarGame_ChartFormats`.
2. **`validation/` is the only Node process.** It is invoked as a subprocess from `charter/cli.py`; the Python side never parses charts itself.
3. **`adt/` velocity is swappable.** N2N / OaF / per-stem-loudness sit behind one interface so the brittle TF1 install can be dropped in or out without touching the rest.
4. **`separation/` is swappable from day one.** RoFormer ↔ Demucs ↔ MVSEP behind one wrapper, scored on *onset preservation* not SDR. See [Source Separation](./04-source-separation.md).
5. **OaF / STRUM should run in their own environments** (separate venv or container) to contain dependency conflicts (TF1 for OaF, the ~6 GB STRUM bundle).

---

## Open questions / TODO

- **Verify STRUM runs on Apple Silicon** — ~6 GB download, **no tagged release**; confirm it executes end-to-end before depending on it (Stage 4).
- **Confirm `Geomitron/scan-chart` has a usable Node≥24 entry point** and packaging for subprocess invocation; verify its license.
- **Verify licenses** for every "— (verify)" row: ADTOF, midi2clonehero, Fureniku, EasyChartGenerator, scan-chart, Jarredou MDX23C 6-stem. Confirm which are safe for a commercial build.
- **N2N velocity has no public code** — decide reimplement-vs-wait; ship OaF or per-stem-loudness in the interim.
- **OaF TF1 install** — confirm it can be isolated (venv/container) on the target hardware without breaking the rest of the Python env.
- **Confirm `madmom` is absent from the resolved dependency tree** (it can arrive transitively) — `pip`/`uv` audit after wiring beat_this + allin1.
- **allin1 NATTEN + Demucs install** — verify it builds on Apple Silicon; confirm the Beat-This-only 4/4 degrade path works when it doesn't.
- **Benchmark end-to-end per-song runtime** on the reference M-series box — no figures exist in the source material yet.
- **LarsNet CC BY-NC / MVSEP cloud upload** — for any commercial path, confirm the offline CC-BY-StemGMD retraining route and the `htdemucs_ft` quality floor are acceptable.
- **Decide whether to ever emit `.mid`** (Rock Band interop) — currently out of scope; `.chart` is canonical.
