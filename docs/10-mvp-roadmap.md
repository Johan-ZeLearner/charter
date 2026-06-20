# MVP Roadmap: Weekend Build → Full Version

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** The build order — a decoupled, phased, checklist-driven plan from a weekend MVP (zero ML training, format-validated end-to-end) to the full ambitious transcription pipeline.

## Related docs
- [Pipeline Architecture](./02-pipeline-architecture.md) — the 9-stage pipeline this roadmap sequences.
- [Tech Stack & Deployment](./08-tech-stack-and-deployment.md) — the repos/packages each phase wires together.
- [Quality, Risks & Gates](./09-quality-risks-and-gates.md) — the scan-chart gate, audio gate, and REVIEW.md confidence model referenced throughout.

---

## 0. The organizing principle: DECOUPLE symbolic backend from audio frontend

**DECIDED:** Build the **symbolic half first, with zero ML.** The pipeline has two halves that fail for completely different reasons, and conflating them is the main way a build stalls:

- **Symbolic / format half (Stages 6–8):** GM drum events → `DrumNote` intermediate model → `.chart` serializer → `scan-chart` validation. This is **deterministic, fully testable, and the actual SOTA here is rule-based** (no production ML mapper exists). Every format footgun lives here: the inverted tom/cymbal default (`.chart` = toms-by-default + cymbal flags `66/67/68`; `.mid` = cymbals-default + tom markers `110/111/112`), `Resolution=192`, BPM×1000, the TS-exponent, the illegal same-color tom+cymbal collision, and opt-in 2× kick. These are bugs you can kill **once** with unit tests and known fixtures.
- **Audio / transcription half (Stages 0–5):** separation → onset → lane classification → velocity → beat/tempo. This is **probabilistic, model-dependent, and has hard ceilings** (onset recall ~89% within ±100ms; STRUM blue lane 0.19 per-class accuracy; downbeat F1 ~78%; end-to-end ~0.84 drum F1). You cannot unit-test your way to correctness here; you can only measure and flag.

**Why decouple:** if you build both at once, a wrong gem in Clone Hero could be a serializer inversion bug **or** a classifier miss, and you can't tell which. Building the symbolic half on hand-made GM MIDI first means **every gem you see is exactly what you wrote** — so all format bugs are isolated and killed with **zero ML noise**. Only then do you bolt on the (noisy, approximate) audio frontend, where any new wrongness is provably a transcription error, not a format error.

**The true MVP milestone is a green `scan-chart` on a real song** — it proves the format + validation loop end-to-end. Everything else is quality iteration on top of a guaranteed-valid container.

---

## PART A — WEEKEND MVP (glue, no training)

> Goal: a complete `mp3 → song folder` path that produces an **instantly playable Expert chart** Clone Hero accepts as 4-lane Pro every time, plus an honest REVIEW.md and one real cleanup pass. Quality is allowed to be mediocre — the goal is a measurable, valid, end-to-end loop.

### Phase 1 — Vendor the spec + stand up scan-chart as a day-one passing test

Make "does Clone Hero accept this and detect Pro drums?" a **passing test before any pipeline code exists.**

- [ ] Vendor `TheNathannator/GuitarGame_ChartFormats` into the repo: `Drums.md` (both `.chart` and `.mid`), `Standard-Tags.md`, `Supported-Audio-Files.md`. Every mapping decision must cite the vendored spec, not memory.
- [ ] Stand up `Geomitron/scan-chart` (TypeScript, byte-matches CH's parser, validated on 40k charts) as a Node ≥24 subprocess behind a thin Python wrapper.
- [ ] Write the first test: feed a known-good fixture song folder through scan-chart and assert `drumType == '4-lane Pro'`, non-zero note counts, and zero blocking parser issues.

**Done when:** scan-chart runs from the Python harness and a known-good fixture passes the `drumType == '4-lane Pro'` assertion in CI.

### Phase 2 — Build the symbolic half on hand-made GM MIDI (zero ML)

Skip audio entirely. Prove the format/serialization half with inputs you fully control.

- [ ] Define the single canonical **`DrumNote` intermediate model**: `{tick, lane, isCymbal, isKick2x, dynamic ∈ {ghost, normal, accent}, difficulty}`. This is the **one place** all format inversions live.
- [ ] Build the `.chart` **serializer** (the ONE place the tom/cymbal inversion lives): `Resolution=192`; `[Song]` / `[SyncTrack]` / `[ExpertDrums]`; toms-by-default; cymbal flags `66/67/68`; accent `34–38`; ghost `40–44`; 2× kick as type `32`; `B` + `TS` markers at tick 0; per-beat tempo map.
- [ ] Implement the GM → lane mapping table seeded from `apvilkko/midi2clonehero`: kick ← `35/36`; red ← snare `37–40`; toms high→low into yellow/blue/green TOM; hi-hats `42/44/46` → yellow cymbal; crash1/splash/china `49/52/55` → blue cymbal; ride/bell/crash2 `51/53/57/59` → green cymbal. Velocity gate: ghost ≤ 60, accent ≥ 120.
- [ ] Implement the three correctness traps: **windowed crash/ride collision resolver** (flip blue↔green); **same-color tom+cymbal validator** (a tom and cymbal of the same color CANNOT share a tick — re-color or drop, every tick); **2× kick inference** via ~150 ms inter-kick-gap heuristic (Expert only).
- [ ] Round-trip known hand-made GM MIDI fixtures: MIDI → `DrumNote` → `.chart` → scan-chart **and** open in Moonscraper. Assert hashes/note counts; visually confirm gems land where the fixture put them.

**RISK:** The `.chart`/`.mid` tom/cymbal inversion silently turns cymbals into toms. **Mitigation: it lives in exactly one serializer and is round-trip-tested against scan-chart's `drumType` output.**

**Done when:** hand-made GM MIDI fixtures round-trip through serializer + scan-chart + Moonscraper with correct gem placement, no inversion/collision/2×-kick bugs, and `drumType == '4-lane Pro'`. **No audio touched yet.**

### Phase 3 — Wire the audio front-half with EASY fallbacks (Expert only)

Now connect the noisy half. Use the **trivial-install fallbacks**, not SOTA — the goal is a complete pipeline you can measure, not a good one.

- [ ] Stage 0: FFmpeg decode/normalize (ITU-R BS.1770 loudness) → 44.1 kHz stereo + 22.05 kHz mono; Mutagen for tags.
- [ ] Stage 1: **Demucs v4 `htdemucs_ft`** (pip, MIT, offline, no-GPU) for the drum stem. (RoFormer is a later swap — see Part B.)
- [ ] Stage 4: **ADTOF** (`drumTranscriptor` CLI, 5-class CRNN, ~0.85–0.89 F) for onsets + classes → raw GM MIDI.
- [ ] Stage 3: **Beat This!** (`beat-this`, `final0` checkpoint, CPU) for beats + downbeats → **per-beat tempo map** via `60/(t[i+1]−t[i])`, coalesced within ~0.5 BPM; infer time signature from downbeat spacing. **Never a global BPM.**
- [ ] Stage 5–6: adaptive 16th-grid quantization at ~100% snap → GM → lane mapping (reuse Phase 2 table) → `DrumNote` → serializer. **Expert only.**

**RISK:** A single global BPM is the #1 cause of unplayable charts. **Mitigation: emit one tempo event per beat interval; verify on a deliberately tempo-changing song that notes don't drift.**

**Done when:** an arbitrary mp3 produces a complete song folder that passes scan-chart, and on a deliberately tempo-changing test song the gems track the audio without drift.

### Phase 4 — Audio-quality gate + REVIEW.md

Bake the honest "AI draft" UX in from the start, not bolted on later.

- [ ] Compute drum-stem RMS gate (STRUM screened at RMS ≥ 0.018; only ~63% of songs passed). CLI prints **GO / CAUTION / REFUSE** with a numeric drum-prominence score. **Refuse early, don't fail late.**
- [ ] Generate `REVIEW.md` listing every low-confidence region: low drum-stem RMS regions, **every blue-lane cymbal/tom call**, inferred 2× kick runs, and the bar-1 / meter guess.

**Done when:** the CLI emits a GO/CAUTION/REFUSE verdict and a REVIEW.md whose flagged regions point a human at the known weak spots.

### Phase 5 — Open in CH + Moonscraper, real cleanup, ship v0

- [ ] Encode `song.opus` via FFmpeg/libopus (~80 kbps). Write `song.ini`: `pro_drums=True`, `five_lane_drums=False`, `diff_drums`, `song_length`, preview times, `charter='charter AI'`. **No `delay`** — bake offset into the chart for leaderboard-hash parity.
- [ ] Open the result in **Clone Hero AND Moonscraper**; confirm it loads and detects 4-lane Pro.
- [ ] Do one real 2-minute Moonscraper cleanup pass yourself, guided by REVIEW.md (confirm bar-1/TS, fix blue-lane calls, sanity-check fills, approve/reject inferred 2× kick) — **to feel the loop.**
- [ ] Ship as **v0**.

**Done when (MILESTONE):** a **green scan-chart on a real song**, the chart loads in Clone Hero as 4-lane Pro and is playable, and you have completed one real cleanup pass end-to-end.

---

## PART B — FULL AMBITIOUS VERSION (priority order)

> Each item is an **independent quality lever** on top of the validated v0 container. Order is by playability payoff per unit effort. **Set up evaluation before optimizing** (onset recall + per-class lane accuracy at ±50 ms and ±100 ms on a few hand-charted reference songs) so each swap is A/B-proven, not assumed.

### Phase 6 — RoFormer separation swap (A/B onset F first)

- [ ] Swap Demucs `htdemucs_ft` → **Mel-Band / BS-RoFormer drum checkpoint** via `audio-separator` (pip, MIT, Apple-Silicon CoreML path).
- [ ] **A/B onset F-measure and final note counts on the same song before committing the heavier dependency.** RoFormer beats Demucs on drums by ~0.5–3 dB SDR (~+15 F-measure stem-vs-mix is the underlying lever), **but** transformer separators can smear dense cymbal transients — **score on onset/transient preservation, not SDR.**

**Done when:** A/B on reference songs shows RoFormer improves onset F (or transient preservation) over Demucs, OR the swap is shelved with evidence.

### Phase 7 — DrumSep per-drum arbiter for the blue lane

- [ ] Add **`inagoy/drumsep`** (MIT, kick/snare/toms/cymbals; optional Jarredou MDX23C 6-stem for hi-hat/ride/crash) as Stage 2.
- [ ] Use per-onset **spectral-energy arbitration** to cross-check the classifier on the worst calls (tom-vs-cymbal, ride-vs-crash) — attacks STRUM's blue lane (0.19 accuracy) directly.

**RISK:** Cascading separators compounds error; StemGMD-trained per-drum models have a synthetic→real domain gap. **Mitigation: treat sub-stems as a soft tie-breaker vote, NEVER as ground truth overriding a confident classifier.** Measure per-class accuracy on toms / ride-vs-crash specifically, not aggregate F.

**Done when:** blue-lane / ride-vs-crash per-class accuracy improves measurably on reference songs vs the classifier alone.

### Phase 8 — Velocity / dynamics

- [ ] Add a velocity path: **per-stem loudness** (equal-loudness + RMS in ~50 ms window on the Stage-2 sub-stem) now; **Magenta OaF-Drums** (E-GMD) if the TF1 install is tolerable; **Noise-to-Notes** diffusion (E-GMD velocity F 0.80) when code ships.
- [ ] Drive ghost (≤ 60) / accent (≥ 120) flags from real velocity.

**Why:** Magenta's listening study showed velocity nearly **doubled** perceptual-quality wins (919 vs 456) — it's what makes ghost/accent feel right.

**OPEN:** Best-velocity path (N2N) had no public code at search time; budget reimplementation or wait.

**Done when:** ghost/accent dynamics are present in output and measurably correlate with the reference performance on a hand-charted song.

### Phase 9 — allin1 segments for fills / star-power / difficulty

- [ ] Run **`mir-aidj/all-in-one` (allin1)** in parallel for functional segments (intro/verse/chorus/break/fill) + a downbeat cross-check against Beat This!.
- [ ] Use segments to place a crash on the downbeat entering each chorus, drum fills in break/pre-chorus bars, and star-power phrases (`S 2`) + fill/activation phrases (`S 64`) — the thing that makes auto-charts feel less "empty."
- [ ] Raise a "verify meter" flag where Beat This! downbeats and allin1 `beat_positions` disagree (downbeat F1 tops out ~78%).

**RISK:** allin1 needs NATTEN + Demucs (heavier install). **Mitigation: degrade to Beat-This-only with assumed 4/4 if it fails.**

**Done when:** segments drive fill/SP placement and meter-disagreement regions are flagged in REVIEW.md.

### Phase 10 — Full EasyChartGenerator difficulty reduction

- [ ] Port `eerovil/EasyChartGenerator` `notes_to_diff_drums` logic to derive Hard/Medium/Easy from the Expert master.
- [ ] Rules: collapse all 2× kicks to single kick below Expert; drop cymbal/accent flags on lower diffs but keep ghosts; fold blue/green→yellow for Easy, green→blue for Medium; **never extend a note to fill a removed gap** (C3/RBN rule).

**Done when:** all four difficulties emit, scan-chart reports sane per-difficulty note counts, and Hard/Medium/Easy are playable (mechanical but serviceable is acceptable).

### Phase 11 — Tighten the REVIEW.md confidence model

- [ ] Improve the **precision/recall of "needs review" flags** — the goal is that REVIEW.md flags the *right* regions, so a human's 15–40 min cleanup is spent where the model is actually wrong (not chasing false alarms or missing real errors).
- [ ] Track per-class CI: Kick/Red/Yellow/Blue/Green separately, plus tom-vs-cymbal, ghost recall, and 2×-kick over-fire — the known weak spots, visible in CI from day one.

**Done when:** flagged-region precision/recall is measured on reference songs and demonstrably guides cleanup to real errors.

### Phase 12 — Optional: web editor + MVSEP cloud tier

- [ ] Optional thin web editor to replace the Moonscraper requirement for non-technical users (lowers the technical barrier to the human cleanup step).
- [ ] Optional **MVSEP drum ensemble** (~14.3 dB) cloud "max quality" tier behind a toggle.

**RISK:** MVSEP is paid cloud with audio upload (IP/privacy); LarsNet weights are CC-BY-NC. **A fully-offline commercial build must accept the `htdemucs_ft` quality floor or retrain per-drum separators on CC-BY StemGMD.**

**Done when:** (if pursued) a non-technical user can complete a cleanup without Moonscraper, and/or a cloud quality toggle is wired behind an opt-in.

---

## Build-order summary

| Phase | Half | Deliverable | Done when |
|---|---|---|---|
| 1 | Symbolic | Vendor spec + scan-chart gate | Known-good fixture passes `4-lane Pro` in CI |
| 2 | Symbolic | DrumNote model + `.chart` serializer | Hand-made MIDI round-trips clean (no ML) |
| 3 | Audio | Easy-fallback frontend (Demucs→ADTOF→Beat This!) | Arbitrary mp3 → valid folder, no tempo drift |
| 4 | Both | Audio gate + REVIEW.md | GO/CAUTION/REFUSE + flagged weak spots |
| 5 | Both | song.ini/opus + real cleanup → **v0** | **Green scan-chart on a real song (MILESTONE)** |
| 6 | Audio | RoFormer swap | A/B onset F proves improvement |
| 7 | Audio | DrumSep arbiter | Blue-lane accuracy up |
| 8 | Audio | Velocity / dynamics | Ghost/accent present & correct |
| 9 | Audio | allin1 segments | Fills/SP placed, meter flags raised |
| 10 | Symbolic | EasyChartGenerator reduction | 4 diffs, sane counts |
| 11 | Both | Tighten confidence model | Flag precision/recall measured |
| 12 | Optional | Web editor + MVSEP tier | Non-technical cleanup / cloud toggle |

---

## Open questions / TODO

- **Verify STRUM runs at all.** STRUM (`opria123/strum`) has a ~6 GB model download and **no tagged release** — its runnability on Apple Silicon is unverified. The MVP deliberately routes around it (ADTOF + custom serializer), but if STRUM is adopted as the reference ADT engine, confirm it runs first.
- **Confirm scan-chart on Node ≥ 24** in the target deployment, and that the Python↔Node subprocess bridge is stable. The Node dependency is **mandatory**, not optional.
- **Confirm `audio-separator` RoFormer CoreML path** actually loads the drum checkpoint on Apple Silicon before committing the Phase 6 dependency.
- **Velocity-best path (Noise-to-Notes)** had no public code at search time — decide reimplement vs wait when Phase 8 lands.
- **allin1 / NATTEN install** is heavy; verify it builds in the target environment before relying on Phase 9 (degrade path is Beat-This-only + assumed 4/4).
- **2× kick heuristic tuning** — the ~150 ms gap over-fires on fast single-foot passages; whether the gap should scale with tempo is unresolved (keep Expert-only + opt-in by default regardless).
- **mp3-specific transient degradation** on cymbals is unquantified in the cited benchmarks (which use clean stems) — real-world mp3 input may underperform the published ~0.84 F1 by an unknown margin; measure on real lossy inputs.
- **Commercial licensing** — MVSEP (paid, audio upload), LarsNet (CC-BY-NC), madmom (transitive commercial caveats; avoided via Beat This!) all need a clearance pass before any paid tier ships.
