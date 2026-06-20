# Charter — `mp3 → playable Clone Hero drums`

> **Status:** Living documentation set · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Single entry point and source of truth for the project. Read this first, then jump to the doc for your task.

Charter turns an uploaded **mp3** into a **playable Clone Hero 4-lane Pro Drums chart** (`notes.chart` + `song.ini` + `song.opus`), so a drummer who plays along to Clone Hero no longer spends multi-hour manual charting sessions.

**The thesis (read this before anything else):** Drums in Clone Hero are a **transcription** problem — reproduce what the drummer actually played — *not* a creative-choreography problem like Beat Saber or osu!. That single framing collapses the task into **ADT (automatic drum transcription) + format mapping**, both of which have strong off-the-shelf components. It is why this is tractable where generative auto-charters "feel empty."

**Honest verdict:** A fully automatic pipeline is buildable **today** from existing open-source parts, no model training required. The realistic ceiling is **"AI draft that is instantly playable + a few minutes of Moonscraper cleanup"** (~0.84 end-to-end drum F1 at ±100 ms ≈ 1-in-6 events off, concentrated in fills, two-cymbal sections, and ghost notes). It is **not** hand-charter quality and **not** leaderboard-legitimate on any input. The one thing guaranteed fully automatically is **format validity** — we gate on Clone Hero's own parser.

---

## How this documentation is organized

Each doc grounds one technical or product aspect. They are cross-linked; numbers (F-scores, MIDI note numbers, tick resolutions) are preserved verbatim from the research. Decisions are tagged **DECIDED / OPEN / ASSUMPTION / RISK** throughout.

| # | Doc | What it grounds |
|---|-----|-----------------|
| — | **[README.md](./README.md)** | This index — vision, glossary, decisions-at-a-glance, handoff. **Start here.** |
| — | 🔴 **[HANDOFF.md](./HANDOFF.md)** | **Current state, the BLOCKING "No Part" bug, what was tried, and remaining work. Read this before building.** |
| 01 | [Product Vision](./01-product-vision.md) | Problem, user, the transcription thesis, "AI draft + cleanup" positioning, non-goals, prior-art landscape (STRUM, Beat Sage, DDC, osumapper…), community sentiment, v0 definition-of-done. |
| 02 | [Pipeline Architecture](./02-pipeline-architecture.md) | **The spine.** The 8 stages, ASCII data-flow diagram, the `DrumNote` intermediate model, the ML-front/symbolic-back **decoupling decision**, polyglot deployment. |
| 03 | [Chart Format Reference](./03-chart-format-reference.md) | **The format bible.** `.chart`/`.mid` grammar, drum note numbers, `song.ini`, audio stems, the **tom/cymbal inversion**, detection order, scan-chart validation. Every byte is load-bearing. |
| 04 | [Source Separation](./04-source-separation.md) | Stage 1–2: drum-stem isolation (RoFormer / Demucs) and per-drum splitting (DrumSep) — the biggest cheap quality lever and the tom-vs-cymbal arbiter. |
| 05 | [Drum Transcription](./05-drum-transcription.md) | Stage 4 ADT core: onset detection + lane classification + velocity. STRUM / ADTOF, the class-count cliff, the ~89% onset recall ceiling, datasets. |
| 06 | [Beat, Tempo & Quantization](./06-beat-tempo-quantization.md) | Stage 3 + 5: beat/downbeat/tempo-map (Beat This!, allin1) and subdivided-grid quantization. Why a single global BPM is the #1 cause of unplayable charts. |
| 07 | [Lane Mapping & Difficulty](./07-lane-mapping-and-difficulty.md) | Stage 6: GM-drum MIDI → CH Pro-Drums lanes, the canonical mapping table, same-color collision rule, 2x-kick inference, Expert→Hard/Medium/Easy reduction. |
| 08 | [Tech Stack & Deployment](./08-tech-stack-and-deployment.md) | The consolidated repo/package/license table, not-turnkey RISK roll-up, polyglot runtime (Python + mandatory Node ≥24), hardware paths, suggested repo layout. |
| 09 | [Quality, Risks & Gates](./09-quality-risks-and-gates.md) | The 6 failure modes ranked by playability damage, the GO/CAUTION/REFUSE audio gate, the scan-chart validation gate, the REVIEW.md confidence surface, per-input-class quality verdict. |
| 10 | [MVP Roadmap](./10-mvp-roadmap.md) | The build order: decoupling-first, 5-phase weekend MVP (milestone = green scan-chart on a real song), then the 7-phase full version in priority order. |

### Suggested reading order
- **New to the project:** README → [01 Vision](./01-product-vision.md) → [02 Architecture](./02-pipeline-architecture.md) → [10 Roadmap](./10-mvp-roadmap.md).
- **Implementing a stage:** [02 Architecture](./02-pipeline-architecture.md) (find your stage) → that stage's deep-dive doc → [03 Format Reference](./03-chart-format-reference.md) if you touch serialization.
- **Wiring dependencies/CI:** [08 Tech Stack](./08-tech-stack-and-deployment.md) → [09 Quality & Gates](./09-quality-risks-and-gates.md).

---

## For a fresh agent picking this up cold (handoff)

1. **Current state (2026-06-20):** The pipeline runs **end-to-end** — `charter/` turns an **audio file into a song folder** (`notes.chart` + `song.ini` + `song.opus`) that scan-chart reports as `fourLanePro` / `playable=True`; **37 tests pass.** Roadmap **Phases 1–3 + the Phase-4 gate are built** on a dependency-light baseline (numpy/scipy + FFmpeg). 🔴 **BUT there is a BLOCKING bug: the user's real Clone Hero shows "No Part" for the generated charts even though scan-chart accepts them — see [HANDOFF.md](./HANDOFF.md) before doing anything else.** Beyond that it is **baseline-grade**: kick/snare/hi-hat only (no toms / ride-vs-crash), tested on synthetic drums — real-music quality unmeasured. SOTA tools (Demucs/Beat This!/ADTOF) are wired as **optional adapters** used if installed.
2. **Where to start building:** [10 MVP Roadmap](./10-mvp-roadmap.md) — Phases 1–3 done. **Next quality levers (Part B):** swap the HPSS baseline for **Demucs/RoFormer**, the band-energy ADT for **ADTOF** (toms + ride-vs-crash), wire **Beat This!**, add velocity dynamics, and write the **REVIEW.md** confidence surface. The organizing principle remains **decoupling** — the symbolic back-half is format-correct and frozen; all remaining work is measurable transcription quality on the audio front-half. **First real-world milestone: run an actual mp3 of a real song and judge/measure the result** (the baseline is only validated on synthetic drums so far).
3. **Ground your work in these docs.** Do not invent tool names, repo URLs, MIDI note numbers, or accuracy figures. If a fact is not here, mark it **OPEN** and verify before relying on it. Preserve specific numbers verbatim.
4. **Respect the decision tags.** **DECIDED** = adopt it. **OPEN** = unresolved, needs a spike or a human. **ASSUMPTION** = taken as true but unverified. **RISK** = known failure mode to design around.
5. **Keep docs in sync.** When you make or change a decision, update the relevant doc's body *and* its "Open questions / TODO" section, and the decisions table below. These docs are the contract between agents across context windows.

---

## Decisions at a glance

**DECIDED (settled, adopt these):**
- Output **`.chart`** (text, `Resolution=192`, drums-as-toms-by-default), not `.mid`. `.mid` only for Rock Band interop. The tom/cymbal default is **inverted** between the two — this is the #1 serializer bug. → [03](./03-chart-format-reference.md)
- One shared **`DrumNote`** intermediate model is the contract between all stages; the format inversion is isolated to the single `.chart` serializer. → [02](./02-pipeline-architecture.md)
- **Decouple** the symbolic back-half (testable with zero ML) from the ML front-half; build the back-half first. → [02](./02-pipeline-architecture.md), [10](./10-mvp-roadmap.md)
- Compute a real **per-beat tempo map**, never a single global BPM (the #1 cause of unplayable charts). → [06](./06-beat-tempo-quantization.md)
- **Quantize** to a subdivided beat grid that follows the tempo curve, at ~100% snap strength (opposite of music-production advice). → [06](./06-beat-tempo-quantization.md)
- Stage-2 per-drum stems are a **soft arbiter / tie-breaker** for tom-vs-cymbal, never ground truth. → [04](./04-source-separation.md)
- **scan-chart** is the canonical acceptance gate; assert `drumType == '4-lane Pro'` before publishing. Requires **Node ≥24** alongside Python. → [03](./03-chart-format-reference.md), [09](./09-quality-risks-and-gates.md)
- **"Refuse early, don't fail late"** — a GO/CAUTION/REFUSE audio-quality gate on drum-stem RMS (≥0.018 reference threshold). → [09](./09-quality-risks-and-gates.md)
- Ship a **REVIEW.md confidence surface** flagging blue-lane calls, inferred 2x runs, low-RMS regions, and bar-1/meter guesses, so cleanup goes straight to the suspects. → [09](./09-quality-risks-and-gates.md)

**Biggest OPEN / RISK items (need a spike or a human):**
- Tom/cymbal & ride-vs-crash confusion — **the worst, unsolved** (STRUM blue lane 0.19 accuracy). Mitigation: Stage-2 arbiter + bias to the safe choice (tom) + flag. → [09](./09-quality-risks-and-gates.md)
- Verify **STRUM** (`opria123/strum`) actually runs (~6GB download, no tagged release) before committing it as the reference ADT engine. → [05](./05-drum-transcription.md), [08](./08-tech-stack-and-deployment.md)
- **Noise-to-Notes** velocity model had no public code at research time — may need reimplementation or the OaF / per-stem-loudness fallback. → [05](./05-drum-transcription.md)
- Bar-1 / time-signature override — downbeat F1 ~78%, meter is the least reliable output; a zero-edit pipeline can't offer the manual override the research recommends. → [06](./06-beat-tempo-quantization.md)
- Commercial licensing (LarsNet CC BY-NC, MVSEP paid+upload, madmom caveats) constrains a fully-offline commercial build. → [08](./08-tech-stack-and-deployment.md)

---

## Glossary

| Term | Meaning |
|------|---------|
| **Clone Hero (CH)** | Free clone of Guitar Hero / Rock Band; plays community charts. Target platform. |
| **Chart** | The note data for a song. CH reads `notes.chart` (text) or `notes.mid` (MIDI). |
| **Pro Drums (4-lane Pro)** | CH drum mode distinguishing cymbals from toms on the yellow/blue/green lanes. Our output target. |
| **`.chart`** | Plaintext, tick-based chart format (Moonscraper-native). Drums default to **toms**; cymbals are opt-in flags 66/67/68. Our chosen output. |
| **`.mid`** | Rock-Band-lineage MIDI chart. Drums default to **cymbals**; toms are opt-in markers 110/111/112. The inverted default vs `.chart`. |
| **`song.ini`** | Metadata + flags. `pro_drums=True` forces the drums track to parse as 4-lane Pro. |
| **SyncTrack** | The `.chart` section holding tempo (`B = BPM×1000`) and time-signature events. Our tempo map lives here. |
| **Resolution** | Ticks per quarter note in `.chart`. Universally **192**. |
| **`DrumNote`** | Our internal per-note model (`lane, isCymbal, isKick2x, dynamic, velocity, difficulty, tick`). The contract between pipeline stages. → [02](./02-pipeline-architecture.md) |
| **ADT** | Automatic Drum Transcription — audio → symbolic drum events (which drum, when, how hard). Stage 4. |
| **Onset** | The precise time a drum is struck. Onset detection caps achievable recall (~89% within ±100 ms). |
| **Source separation / stem** | Splitting a mix into parts (drums, bass, vocals…). A clean drum **stem** gives ADT ~+15 F-measure. |
| **F-measure / F1** | Accuracy metric (harmonic mean of precision & recall). End-to-end drum target ≈ 0.84 at ±100 ms. |
| **SDR** | Signal-to-Distortion Ratio (dB) — source-separation quality metric. |
| **STRUM** | `opria123/strum` — the SOTA transcription-first auto-charter tuned for CH drums. Candidate ADT engine. |
| **ADTOF** | 5-class CRNN drum transcriber (~0.85–0.89 F). Independent cross-check / fallback engine. |
| **RoFormer (Mel-Band/BS)** | SOTA source-separation models; best drum stem today (via `audio-separator`). |
| **Demucs** | `htdemucs_ft` — popular, no-GPU separation; our trivial-install fallback. |
| **DrumSep** | Splits a drum stem into kick/snare/toms/cymbals — the tom-vs-cymbal arbiter. |
| **Beat This!** | 2024 SOTA beat/downbeat tracker (no madmom dependency). Stage 3. |
| **allin1 / All-In-One** | Joint beat + downbeat + tempo + structure segmentation. Used for fills/SP/difficulty + cross-check. |
| **scan-chart** | `Geomitron/scan-chart` (TS) — byte-matches CH's own parser; the validation gate. |
| **Moonscraper** | Community chart editor; writes `.chart`. The human-cleanup tool in the loop. |
| **2x kick** | Double-bass notes (`.chart` type 32). Inferred (~150 ms gap), Expert-only, collapsed on lower difficulties. |
| **Ghost / accent** | Quiet / loud hits, derived from velocity (gate: ghost ≤60, accent ≥120). |

---

## Provenance

This documentation set was produced on **2026-06-20** from a multi-agent research + design sweep covering: the CH chart format, prior-art auto-charters, source separation, drum transcription, beat/tempo detection, and lane mapping — synthesized through three design perspectives (full-auto, human-in-loop, feasibility-skeptic). All factual claims trace to that research; unverified items are marked **OPEN**. When code lands and reality diverges from a doc, update the doc — it is the contract.
