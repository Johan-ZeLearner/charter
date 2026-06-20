# Quality, Risks, and Gates

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** State honest quality expectations by input class, rank the failure modes by how badly they hurt playability, and define the gating/QA strategy that catches the worst inputs early and hands the rest off cleanly to a human.

## Related docs
- [Drum Transcription](./05-drum-transcription.md) — the ADT core whose per-class accuracy figures drive the failure ranking below.
- [Beat, Tempo & Quantization](./06-beat-tempo-quantization.md) — where meter/bar-1 errors and robotic-vs-musical quantization are won or lost.
- [MVP Roadmap](./10-mvp-roadmap.md) — when each gate and the REVIEW.md confidence surface get built.

---

## 1. The one-paragraph honest verdict

We can build a fully automatic `mp3 → playable Expert Pro Drums .chart` pipeline today from existing open-source tools with **no model training**. The realistic ceiling is an **"AI draft that is instantly playable + a few minutes of Moonscraper cleanup"**, NOT flawless hand-charter quality and NOT leaderboard-legitimate timing on any input. This works because **drums are a transcription problem (reproduce what the drummer played), not a creative-choreography problem** like Beat Saber — that collapses the task to ADT + format mapping, both of which have strong off-the-shelf components. End-to-end drum accuracy lands around **STRUM's ~0.84 F1 at ±100ms**, i.e. **roughly 1 in 6 events is missing or mis-placed**, concentrated in three predictable places: busy fills, two-cymbal (ride+crash) sections, and quiet ghost notes. The one thing we **can** guarantee fully automatically is **format validity** — scan-chart confirms Clone Hero loads and parses the output as 4-lane Pro every time, because we gate on the game's own parser logic.

**DECIDED:** Ship and market this as an **assistive first-pass with an explicit editor handoff** ("AI draft → editor cleanup"), never as finished/competitive charts. Every comparable tool that claimed "finished charts" (Beat Sage, osumapper) earned a "feels empty/soulless" reputation. Positioning is a product-credibility decision, not a cosmetic one.

---

## 2. Hard problems ranked by playability damage

Ranked by how much each failure mode degrades a *playable* chart, worst first. Figures are verbatim from the research (STRUM benchmarks, ADT literature). Each carries an explicit mitigation and an honest note on whether a full fix exists.

### Rank 1 — Tom/cymbal & ride-vs-crash lane confusion (worst, unsolved)
The quantified bottleneck. STRUM ensemble lane F1 = **0.852** *masks* terrible per-class accuracy: **Kick 0.61 / Red (snare) 0.44 / Yellow 0.49 / Blue 0.19 / Green 0.57**. The **blue lane (high-tom vs ride) at 0.19** is the documented worst case. STAR Drums quantifies the cliff: F drops **0.81 (3-class) → 0.67 (18-class)** — KD/SD/HH is solved, full-kit is not. Busy two-cymbal (ride+crash) and tom-fill passages get mis-colored. lossy mp3 makes this *worse* by smearing cymbal transients (the exact thing the blue lane already fails on).

- **Mitigation:** make tom/cymbal a first-class disambiguation stage, not a flat lookup: CQT features + a per-drum-stem **spectral-energy arbiter** (cross-check the classifier against which sub-stem actually carries energy at each onset). Use a windowed crash↔ride resolver (if a ride already holds green in the window, a colliding crash goes blue) rather than a static GM table. **Bias low-confidence calls toward the SAFE choice (TOM)** — a tom mischarted as cymbal is jarring and color-wrong, whereas tom-default matches `.chart` semantics and is the safer error. **Flag every blue-lane call for review.**
- **RISK:** No full automatic fix exists in 2026. Even with stem arbitration, busy two-cymbal passages WILL be visibly wrong often enough that **this is the #1 thing an editor fixes**. This is the systematic *visible* defect of the whole product.

### Rank 2 — Onset recall ceiling (~89%)
Recall is capped *before classification even runs*. STRUM onset F1 = **0.939 at ±50ms**, but only **89.0% of ground-truth drum events lie within ±100ms of ANY detected onset**. You cannot classify a note you never detected — the missing **~11%** is gone by construction.

- **Mitigation:** invest in the best onset detector + cleanest stem **first**; classification is secondary. Drum-stem separation before ADT buys **~+15 F-measure** (full mix ~0.65 → drum stem ~0.80) and directly raises this ceiling. Surface as a missing-note risk in the review map.
- **RISK:** Structural. The ~11% concentrates in **ghost-note flurries, buzz rolls, and dense double-kick** — exactly the passages players scrutinize as "missing." Tightening onset sensitivity trades recall for false positives — **no free lunch**.

### Rank 3 — Meter / bar-1 / time-signature errors
The other silent corrupter. Beat F1 is high (**~89–97%**), but **downbeat F1 tops out ~78% on hard material**. A wrong bar-1 or a missed odd meter (7/8, pickup bars, half-time choruses) silently shifts every fill, every star-power phrase, and every TS event.

- **Mitigation:** build a per-beat **tempo MAP**, never a global BPM (a single global BPM is the **#1 cause of unplayable charts** on any tempo-drifting song). Cross-check Beat This! downbeats against allin1 `beat_positions` and pick the agreeing meter; **disagreement raises a "verify meter" flag**. Take fine hit timing from onsets (Stage 4), not the ~20ms beat grid, then snap.
- **RISK:** The literature explicitly recommends **manual override** for bar-1 and time signature here — a true zero-edit pipeline cannot provide that, so **flagging the low-agreement region is the honest compromise**. Never auto-publish meter as if it were certain.

### Rank 4 — Double-kick is inferred, not measured
2x kick is never in the transcription data; it is **inferred** from a **~150ms inter-kick-gap heuristic**. There is no audio feature that cleanly says "two feet."

- **Mitigation:** Expert-only; gap should scale with tempo; **default to single kick (opt-in 2x)**; collapse to single kick on all lower difficulties; **mark inferred 2x runs in the review map** so the human approves/rejects.
- **RISK:** Over-fires on fast single-foot 16ths (turns a hard-but-single-pedal groove into unplayable double-bass) and under-fires when the separator smears kick transients. A structural guess, not a measurement.

### Rank 5 — Input-dependent quality (the audio gate)
Quality is gated by separation. **STRUM passed only ~63% of candidate songs at its drum-RMS gate** (RMS ≥ 0.018). The other **~37%** — buried drums (dense metal guitar walls, heavily-compressed/sidechained pop), lo-fi, live bootlegs, heavy lossy compression — produce sparse or wrong charts no matter the model. mp3 specifically adds transient smearing that hurts the already-weak cymbal classes.

- **Mitigation:** **refuse early, don't fail late** — a drum-stem RMS gate that emits **GO / CAUTION / REFUSE** plus a numeric drum-prominence score, so bad inputs are *flagged, not silently corrupted*. See §3.
- **RISK:** We can only flag, not repair, buried-drum inputs. Honest UX ("drums are buried, expect a rough draft") is free goodwill; silent emission of noise is the trap.

### Rank 6 — Robotic vs musical quantization
The "feels wrong" axis the community judges hardest. Raw onsets feel sloppy; naive global-grid snapping feels robotic and destroys fills/swing.

- **Mitigation:** snap to a **subdivided beat grid that follows the tempo curve**, never a fixed-BPM grid — 16ths default, 32nds for fast double-kick, triplet grids **only where swing is detected** (per-region onset-histogram clustering at 1/3, 2/3). Snap at **~100% strength** (game charts need notes on hittable grid lines — the *opposite* of music-production's ~80% advice). Two-stage: hard-snap to straight 16ths, then apply a swing template only in detected-swing regions so straight sections aren't mangled.
- **RISK:** Over-quantize → fills flatten; under-quantize → unhittable. This is fundamentally a **charting-judgment problem**, not fully solvable by transcription. The residual artifact is over-quantizing genuine fills.

**ASSUMPTION:** the published figures (STRUM's 0.838 end-to-end on a curated 29-song benchmark at the loose ±100ms tolerance) are **optimistic for arbitrary real-world mp3**. Benchmarks mostly use clean stems; lossy-mp3-specific cymbal degradation is unquantified in the cited numbers and may underperform by an unknown margin.

---

## 3. Gating philosophy: "refuse early, don't fail late"

The dominant cause of "it feels wrong" complaints is **garbage-in**. The cheapest quality lever is to kill hopeless inputs before producing a confidently-wrong chart and wasting the user's cleanup time.

**DECIDED:** A three-state drum-quality gate driven by **drum-stem RMS**, surfaced to the user.

| Verdict | Trigger (drum-stem RMS, threshold from source) | Behaviour |
|---|---|---|
| **GO** | RMS ≥ 0.018, drums prominent | Proceed normally; expect instantly-playable draft. |
| **CAUTION** | Near/marginally below threshold, or detectably buried | Proceed but propagate a low-confidence flag and tell the user "drums are buried, expect a rough draft." |
| **REFUSE / WARN** | Well below threshold; sparse or no recoverable drum energy | Warn rather than emit, or emit with a loud "this is unreliable" banner. |

- The **0.018 RMS threshold** is taken verbatim from STRUM's own screening (where only ~63% of candidates passed). It is the gate's primary signal.
- **DECIDED:** gate is a *soft* gate computed **after Stage 1 separation** on the separated drum stem's RMS (with an optional cheap pre-check at ingest on the full mix). We **do not hard-block** in the MVP — we proceed and propagate the flag — but the verdict is always surfaced.
- **OPEN:** exact CAUTION-band cutoffs and whether REFUSE ever fully blocks emission (vs always emitting with a warning) are unresolved — needs a human product call.

---

## 4. The scan-chart validation gate (the one fully-automatic guarantee)

This is the single thing we **can** guarantee fully automatically. Everything in the acoustic-ML half is probabilistic; the symbolic/serialization half can be made correct with high confidence because the format is fully specified (TheNathannator/GuitarGame_ChartFormats) and there is a parser that **byte-matches Clone Hero**.

**DECIDED:** Round-trip every generated song folder through **Geomitron/scan-chart** (TypeScript, byte-matches CH's parser, validated on 40k charts) via a Node subprocess, **before** returning to the user.

The gate asserts, treating scan-chart's output as ground truth:

```
assert report.drumType == '4-lane Pro'      # anything else => we mis-emitted cymbal/tom flags; FAIL FAST
assert note_counts_per_difficulty > 0       # catches an empty chart
assert note_counts not absurdly dense       # catches an over-dense / runaway chart
assert parser_issues == []                  # zero blocking parser issues
# also captured: NPS, track hash (leaderboard-hash parity)
```

- If `drumType` is **anything but `4-lane Pro`**, we got the cymbal/tom flags backwards — almost always the **`.chart`-vs-`.mid` inversion** (`.chart` defaults to TOM, add `66/67/68` for cymbals; `.mid` defaults to CYMBAL, add `110/111/112` for toms). Isolate that inversion to **one serializer** so this gate catches it deterministically. Set `pro_drums=True` and include ≥1 cymbal marker, or the whole chart reads as all-toms.
- Avoid the song.ini `delay` field (breaks leaderboard-hash parity); **bake offset into the chart**.
- **DECIDED:** make a green scan-chart on a real song the **true MVP milestone** — it proves the format + validation loop end-to-end. Stand scan-chart up as a passing test on **day one**, before writing pipeline code.
- **RISK (deployment, not quality):** this requires a **Node ≥ 24 runtime alongside Python** (polyglot deployment). Mandatory dependency for the gate. Optional deeper QA oracles: Moonscraper Song Validator / Editor on Fire (EOF).

---

## 5. The REVIEW.md / confidence surface

Errors are inevitable and **not evenly distributed** — they concentrate in the four ranked spots above. The product's whole credibility is turning those inevitable errors into a **graceful, honest handoff** instead of silent corruption. This mirrors how real charters already work (AI draft → editor cleanup) and is what separates this from the "soulless auto-chart" reputation trap.

**DECIDED:** Emit a machine-generated **REVIEW.md** sidecar (and optionally in-chart "needs review" text events) that sends the human's cleanup pass **straight to the suspects**. It flags, at minimum:

| Flag | Source signal | Why it's here |
|---|---|---|
| **Every blue-lane cymbal/tom call** | Per-region classifier confidence (Rank 1) | The 0.19-accuracy lane; the #1 thing an editor fixes. |
| **Inferred 2x-kick runs** | 150ms-gap heuristic fired (Rank 4) | Approve/reject double-bass; default single. |
| **Low-RMS regions** | Drum-stem RMS gate (Rank 5) | Where notes may be sparse/missing. |
| **Bar-1 / meter guess** | Beat This! vs allin1 downbeat disagreement (Rank 3) | The least-reliable timing call; the *first* thing the human checks. |
| **Dense-cymbal / busy-fill sections** | Low onset/lane confidence (Ranks 1–2) | Where mis-color and missing-ghost risk peak. |

Scope the resulting human pass tightly: (a) confirm bar-1/time-signature, (b) fix blue-lane cymbal-vs-tom calls, (c) sanity-check fills and the crash-into-chorus, (d) approve/reject inferred double-kick. **Everything else should already be right.**

- **DECIDED:** add the confidence layer **last** in the build (after the spine works), but design the DrumNote model to carry per-note `confidence` from day one so it's not bolted on.
- **OPEN:** the **precision/recall of the "needs review" flags themselves** is unverified — a confidence model that flags the *wrong* regions is worse than none. This needs measurement against hand-charted references (track per-class accuracy, ghost-recall, and 2x-kick over-fire in CI, NOT just aggregate F).

---

## 6. Honest quality verdict by input class

Input-conditioned, because a single headline number is dishonest. All figures verbatim from source.

| Input class | Share | Raw-draft quality | Human cleanup | Verdict |
|---|---|---|---|---|
| **Clean studio, prominent drums** (passes RMS gate, click-tight tempo, mostly straight 16ths) | **~63%** (pass the drum-RMS gate) | **Instantly playable Expert chart.** Kick/snare/hi-hat backbone near-solved (**~0.85–0.89 F** on those classes); timing tight (snapped to real tempo map); ghost/accent dynamics present. End-to-end **~0.84 F1 at ±100ms → ~1 in 6 events off**, concentrated in busy fills, ride+crash sections, quiet ghosts. Visible defect: mis-colored cymbals/toms on dense passages (blue worst). | **~15–40 min** Moonscraper pass to be sharable. | "Good enough to play immediately and have fun." |
| **Typical arbitrary mp3** (dense mix, some tempo drift, lossy compression) | the rest of the playable range | **Clearly a draft.** Noticeable mis-quantization in fast fills, frequent tom/cymbal mistakes, meter/bar-1 errors on intros & odd sections, missing notes in the ~11% recall gap. | Longer than clean studio. | Playable but visibly machine-made; **NOT leaderboard-legitimate** (timing won't match a hand-chart). |
| **Buried / dense / live drums** | **~37%** (fail the RMS gate) | Sparse to genuinely wrong; confidence flags say so. | N/A | **Refuse or warn — should not emit** silently. |

**It will NOT match hand-charting on any input.** Even a perfect transcription lacks the deliberate musical phrasing humans add — that's the "feels empty" complaint, and it is a **charting-judgment gap, not a transcription one**. Auto-derived Hard/Medium/Easy are serviceable but mechanical (rule-based thinning, not authored). Velocity/dynamics are the least reliable dimension in the weekend MVP and the most defensible thing to defer.

**The strongest honest claim:** *"best available automatic first-pass — transcription-grade on clean drums, draft-grade otherwise, always with an editor handoff."* The only fully-automatic guarantee: scan-chart confirms Clone Hero loads and parses it as 4-lane Pro every time. For a drummer tired of multi-hour manual charting, this turns **hours into minutes of cleanup on a chart that's already playable** — the realistic win today.

**RISK (perception):** consistent cross-game sentiment (Clone Hero, Beat Saber, StepMania) is that auto-charts feel empty/soulless and are a starting point, not a replacement. No amount of engineering changes that perception **if marketed as "finished charts."** Anyone promising finished, leaderboard-quality charts from arbitrary audio is contradicting the published numbers.

---

## Open questions / TODO

- **Verify STRUM is runnable on Apple Silicon** — ~6GB model download, **no tagged release**; confirm the drum chain actually runs before depending on it as the reference engine.
- **Confirm scan-chart's `drumType` output** is exactly `'4-lane Pro'` (string match) and that the Node ≥ 24 subprocess integrates cleanly with the Python pipeline.
- **Measure the REVIEW.md flag precision/recall** against hand-charted reference songs — does the confidence model flag the *right* regions? Track blue-lane / ghost-recall / 2x-kick over-fire **separately** in CI, not aggregate F.
- **Quantify lossy-mp3 cymbal degradation** vs the clean-stem benchmarks — real-world mp3 input may underperform STRUM's published ~0.84 by an unknown margin.
- **Tune the RMS-gate band cutoffs** (GO/CAUTION/REFUSE) on real candidate songs; decide whether REFUSE ever hard-blocks emission.
- **Validate the per-drum-stem energy arbiter actually moves the blue lane** — DrumSep/StemGMD-trained sub-stems carry a synthetic→real domain gap; confirm they help and never *override* a confident classifier alone.
- **Confirm double-kick gap heuristic** (~150ms, tempo-scaled) over-fire/under-fire rates across genres before defaulting it on at all (it must stay opt-in).
- **Decide whether to ship a thin web editor** to replace the Moonscraper requirement for non-technical users (the technical barrier to the human cleanup step).
- **Licensing check:** LarsNet weights are CC BY-NC (non-commercial); best MVSEP ensembles are paid cloud with audio upload (IP/privacy); madmom may be pulled in transitively with commercial-use caveats — verify before any commercial build.
