# Product Vision

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Establish *why* charter exists, the central thesis (drums = transcription, not generation), how we position it against every prior auto-charter, and what a shippable v0 actually means.

## Related docs
- [Pipeline Architecture](./02-pipeline-architecture.md)
- [Quality, Risks & Gates](./09-quality-risks-and-gates.md)
- [MVP Roadmap](./10-mvp-roadmap.md)

---

## 1. The problem & the user

**The user is a drummer who plays Clone Hero** and wants charts for songs that nobody has hand-charted. Today their only option is to chart it themselves in Moonscraper (or Editor on Fire), which is a **multi-hour manual transcription session per song** — listening, placing every kick/snare/hi-hat/tom/cymbal note onto the grid by hand, fixing timing, marking Pro-Drums tom vs cymbal flags, then reducing to lower difficulties. This is the pain we remove.

**What charter does:** takes an uploaded mp3 and produces a **playable Clone Hero Pro Drums chart** (4-lane Pro) that loads in the game on the first try, so the drummer can start playing in minutes instead of spending an afternoon charting.

**What charter is honestly NOT:** a hand-charter replacement. The realistic deliverable is an **"AI draft that is instantly playable + a few minutes of Moonscraper cleanup"** — not flawless hand-charter quality. This honest framing is baked into every downstream decision; see [§4 Product positioning](#4-product-positioning).

The concrete win for the user: a clean studio recording with prominent drums comes out **instantly playable on Expert**, turning *hours of manual charting* into **~15–40 minutes of Moonscraper cleanup on a chart that is already fun to play**.

---

## 2. The thesis: drums are transcription, not generation

This is the **central thesis of the entire project**, and it is what makes charter tractable where generative auto-charters disappoint.

**Drums in Clone Hero are a TRANSCRIPTION problem** — reproduce what the drummer actually played on the recording. They are *not* a creative-choreography problem like Beat Saber or DDR/StepMania, where the chart is an invented arrangement of blocks/arrows that has no single "correct" answer and must *feel* musical to feel good.

Why this distinction is the whole ballgame:

- For a **choreography** game, a model has to *invent* phrasing and flow. When it gets the statistics right but the musical intent wrong, the result "feels empty/soulless." There is no ground truth to converge on.
- For **drums**, there *is* a ground truth: the real performance in the audio. The task collapses to **Automatic Drum Transcription (ADT) + format mapping**, and both halves have strong off-the-shelf components. This is why a transcription-first pipeline beats a generative one for this specific use case.

**DECIDED:** charter is a **transcription-first** pipeline (source-separate → onset-detect → classify lanes → disambiguate tom/cymbal → emit Pro-Drums chart). We do **not** borrow generative choreography models for the drum path. The documented failure mode of generative approaches on drums is wrong note-type assignment.

This thesis is consistent across the research: drums need transcription (reproduce the real performance), not generation. See [Pipeline Architecture](./02-pipeline-architecture.md) for how each stage realizes this thesis.

---

## 3. Prior art landscape

The field splits cleanly into two paradigms, and our verdict on each tool is **"borrow"** vs **"ignore (cite as lineage only)."**

### 3.1 The two paradigms

| Paradigm | Lineage | Description | Relevance to charter |
|---|---|---|---|
| **Two-step (placement → selection)** | Dance Dance Convolution (DDC, 2017) | Step 1: onset/placement model (CNN over spectrogram + LSTM, framed as onset detection). Step 2: symbolic note-selection model (conditional LSTM), conditioned on difficulty. | **Borrow the shape** (onset → classify), but the 2017 CNN-LSTM itself is dated. Cite as paradigm prior art. |
| **End-to-end transformer / diffusion** | Mapperatorinator, Mug-Diffusion (2023–2026) | A single model maps audio → chart events directly. Whisper-style transformer-encoder + token-decoder (+ optional diffusion coordinate refinement), or audio-conditioned diffusion. | Modern SOTA *architecture* for the broader field, but built for **generation** (osu!, mania), not drum transcription. Borrow only if/when we add a generative side-path. |

### 3.2 Tool-by-tool verdict

| Tool | Game / part | What it is | Maturity caveat | Verdict |
|---|---|---|---|---|
| **STRUM** (Octave) | Clone Hero / YARG **drums** (+ gtr/bass/keys/vox) | **The SOTA for THIS exact use case.** Transcription-first, NOT generative. Pipeline: Demucs v4 `htdemucs_6s` stems → 2-stage CRNN onset detector (mel, 22050 Hz, 128 mel bins) → 6-model `OnsetClassifier` ensemble (V2/V4/V6/V12c/V15/V16, mel+CQT, averaged in log-prob space) → tom-refinement CNN + Phase-3 corrector + drum-stem energy arbiter + heuristics. MIT; `github.com/opria123/strum`. | Active, **no tagged releases**; requires **~6GB manual model download**. Verify runnability before committing. | **BORROW (reference blueprint).** Reuse directly or reimplement its stages. |
| **Audio2Hero** | Clone Hero **guitar** | Encoder-decoder T5 transformer fine-tuned from `sweetcocoa/pop2piano`. Generates medium-difficulty guitar charts end-to-end (MIDI + ogg + ini zip), ~45s/song. **Generative, guitar only, no drums.** | HuggingFace Space currently hits runtime errors. | **IGNORE for drums.** Keep as the recipe reference *if* we ever add a guitar path (T5/pop2piano fine-tune). |
| **Dance Dance Convolution (DDC)** | StepMania/DDR | Canonical two-step prior art (ICML 2017). 3-min chart in ~5s on a Tesla K40c. DDCL (2025) adds variable-BPM handling (original DDC was effectively fixed at 120 BPM internally). | Reference implementation, not maintained. | **CITE as lineage only** (defines the two-step paradigm; flag as dated). |
| **Beat Sage** | Beat Saber | Most famous automapper (by DDC authors). Two networks: onset-placement + block-type/position, trained on curated community maps. V2-Flow variant trades creativity for playability. | Closed/proprietary hosted service; not SOTA quality. | **IGNORE (different problem).** Useful only as the cautionary tale: generative choreography → "feels empty." |
| **osumapper** | osu! | Older known automapper (v7.0, 2020, TensorFlow). Requires a user-supplied timed `.osu`. | Abandoned/dated; superseded by Mapperatorinator. | **CITE as historical reference only.** |
| **Mapperatorinator** | osu! / Taiko / Catch / Mania | Most advanced general charting model (v32, May 2026). Whisper-derived transformer (~219M params) over mel-spectrogram → token decoder → diffusion refines coordinates below 32px quantization. ~5700 GPU-hours trained. | Very active (500+ stars); built for osu!-family generation. | **IGNORE for drums; note the architecture.** This is the architecture to follow *if* we ever generate (not transcribe) a part. |
| **Mug-Diffusion** | osu!mania / Malody (4K VSRG) | Stable-Diffusion-derived audio-conditioned diffusion chart generator. End-to-end, controllable by difficulty / LN ratio / pattern type. ~30s for four 3-min charts on a 3050Ti. | Active research/community. | **IGNORE for drums; note the architecture.** Proof diffusion is a viable alternative to two-step *for generation*. |
| **DDC (lineage), GenerationMania, TaikoNation** | Various | Academic two-step / pattern-focused prior art (e.g. GenerationMania, AIIDE 2019: feed-forward net on sound-sequence summary stats → playable-vs-BGM classification → key assignment). | Dated academic references. | **CITE as paradigm lineage only.** |
| **InfernoSaber** | Beat Saber | Modern automapper (v1.7.1, Jan 2025): 4 sequential models (conv autoencoder → TCN → DNN note/bomb → DNN lighting), adjustable difficulty easy(<1)→Expert+++(10+). | Active; CNN/TCN not transformer. | **IGNORE (choreography).** Note only as a difficulty-conditioning reference. |

### 3.3 Symbolic backends (the "back half")

These are non-ML MIDI→chart converters that matter once our transcription stage emits drum MIDI. **DECIDED:** reuse, don't rebuild, the symbolic back half initially.

| Tool | Role |
|---|---|
| **Fureniku/Drum-MIDI-To-Clone-Hero-Converter** | MIDI→`.chart`, handles Pro Drums tom/cymbal markers + automatic 2x kick. (Java; route around it via the Python `apvilkko/midi2clonehero` mapping table if we want to stay polyglot-light.) |
| **Dirtmigurt/ConvertHero** | MIDI→`.chart` + automatic tempo-marker placement. |

**RISK:** several promising repos are not turnkey: `axlprz/clone-hero-chart-ml` ships *without* its trained `.pkl`; Audio2Hero's HF Space errors; STRUM has no tagged release and needs a ~6GB download. Verify runnability before committing to any as a dependency. (Carried into [Quality, Risks & Gates](./09-quality-risks-and-gates.md).)

### 3.4 What to borrow vs ignore — one-line verdict

- **BORROW:** STRUM's full architecture as the **reference blueprint** for the drum ADT core; symbolic MIDI→.chart converters (Fureniku / ConvertHero / midi2clonehero table) for the back half; DDC's *two-step shape* (onset → classify) as the conceptual frame.
- **IGNORE for the drum path:** all generative choreography models (Beat Sage, osumapper, InfernoSaber) and all end-to-end generation models (Mapperatorinator, Mug-Diffusion, Audio2Hero) — note their architectures for a *future, optional* generative side-path only.
- **CITE as lineage, treat as dated:** DDC (2017), GenerationMania (2019), osumapper (2020). The 2024–2026 SOTA is transformer/diffusion *for generation* and transcription-ensemble (STRUM) *for drums*.

---

## 4. Product positioning

**charter is an assistive first-pass charter with an editor handoff.** The product is **"AI draft + editor cleanup,"** never "finished charts."

### Explicit non-goals
- **NOT leaderboard-legitimate.** Auto-generated timing will not match a hand-chart, so it is not a substitute on the leaderboards. (We do, however, preserve leaderboard-hash *validity* by baking offset into the chart rather than using `delay` — a correctness detail, not a quality claim. See [Pipeline Architecture](./02-pipeline-architecture.md).)
- **NOT a replacement for hand-charters.** Even a *perfect* transcription lacks the deliberate musical phrasing humans add — that "feels empty" gap is a charting-judgment problem, not a transcription one, and we do not claim to close it.
- **NOT flawless.** End-to-end drum accuracy lands around STRUM's **~0.84 F1 at ±100ms**, meaning roughly **1 in 6 events is missing or mis-placed**, concentrated in busy fills, two-cymbal (ride+crash) sections, and quiet ghost notes.
- **NOT a universal mp3→chart magic box.** On ~37% of inputs (buried/dense/live drums) it should **refuse or warn**, not silently emit a bad chart.

### The honest claim we *can* make
> **"Best available automatic first-pass — transcription-grade on clean drums, draft-grade otherwise, always with an editor handoff."**

The one thing we **can** guarantee fully automatically is **format validity**: Clone Hero will load and parse the output as 4-lane Pro every time, because we gate on the game's own parser logic before publishing (see [§6 Success criteria](#6-success-criteria--definition-of-done-v0)).

---

## 5. Community sentiment & what it implies

Community sentiment is **consistent across every comparable game** (Clone Hero, Beat Saber, StepMania/osu!): auto-charts are viewed as a **useful starting point / gap-filler, NOT competitive with hand-charting.** They are described as "feeling empty," "sparse," "soulless," "you won't get good levels from a generator." Every tool that claimed to produce *finished* charts (Beat Sage, osumapper) earned exactly this "needs cleanup" reputation.

**Implications for the product (these are not optional):**

1. **Framing is a product feature, not marketing.** We ship and describe charter as **"AI draft → editor cleanup,"** matching the workflow these tools are *actually* used in. Over-claiming is the fastest way to earn the "soulless" reputation.
2. **Surface confidence, don't hide it.** Emit a per-region **"needs manual review"** signal (low-RMS audio regions, every uncertain blue-lane cymbal/tom call, inferred 2x-kick runs, the bar-1/meter guess). This sets correct expectations and matches the community's AI-draft→cleanup mental model.
3. **Refuse early, don't fail late.** Gate inputs (drum-stem RMS) into GO / CAUTION / REFUSE so bad audio is flagged, not silently turned into a broken chart. (STRUM passed only ~63% of candidate songs at its drum-RMS gate.)
4. **Embrace the editor handoff.** Moonscraper/EOF cleanup is part of the intended flow, not an admission of failure.

**RISK:** the community *will* judge harshly. Mitigation is honest framing + visible confidence signals, carried through into [Quality, Risks & Gates](./09-quality-risks-and-gates.md).

---

## 6. Success criteria / definition of done (v0)

**The single true milestone for v0 is: a green `scan-chart` on a real song.**

`Geomitron/scan-chart` (TypeScript) byte-matches Clone Hero's own parser logic (validated on 40k charts). A green scan-chart proves the **format + validation loop works end-to-end** — that the game will accept the output and detect it correctly.

**v0 is done when, for a clean real-world song:**
1. The pipeline runs mp3 → Clone Hero song folder with **no manual intervention**.
2. `scan-chart` passes and reports **`drumType == '4-lane Pro'`** with **non-zero note counts**.
3. The chart **loads in Clone Hero** and is **playable on Expert** (kick/snare/hi-hat backbone present and on a real per-beat tempo map, not a single global BPM).
4. It also **opens in Moonscraper** for the cleanup pass.
5. A **REVIEW signal** is emitted: low-RMS regions, every blue-lane cymbal/tom call, inferred 2x-kick runs, and the bar-1/meter guess are flagged for the user.

**Explicitly out of scope for v0** (deferred — see [MVP Roadmap](./10-mvp-roadmap.md)): SOTA stem separation (RoFormer), per-drum spectral-energy arbiter, learned velocity/dynamics, structure-aware fill/star-power placement, full Hard/Medium/Easy reduction, and any web editor. v0 uses the easy fallbacks (Demucs `htdemucs_ft` → ADTOF → Beat This! → GM mapping → **Expert only**).

**What "good" looks like on the target input** (clean studio recording, prominent drums — the ~63% that pass the audio gate): an **instantly playable Expert Pro Drums chart**, tight timing, ghost/accent present, **~0.84 drum F1**, requiring **~15–40 min of Moonscraper cleanup to be sharable.** That is the realistic, honest win — and it is achievable today.

---

## Open questions / TODO

- **Verify STRUM is runnable** (no tagged release; ~6GB model download) and confirm it runs on **Apple Silicon** before adopting it as the reference engine. *(Carry into [Pipeline Architecture](./02-pipeline-architecture.md).)*
- **Confirm `scan-chart` runs as a Node ≥24 subprocess** in our environment and reliably reports `drumType`/note counts (it is the v0 definition-of-done gate).
- **Verify the symbolic back-half choice:** Fureniku converter (Java) vs the pure-Python `apvilkko/midi2clonehero` mapping table — decide whether to take the Java dependency or stay Python-only.
- **Confirm a usable, license-clear release** exists for ADTOF (cross-check ADT backbone) and Beat This! (`final0` checkpoint) on our platform.
- **OPEN:** exact thresholds for the GO / CAUTION / REFUSE audio gate (STRUM used drum-stem RMS ≥ 0.018 → ~63% pass; verify this transfers to mp3 inputs).
- **OPEN:** whether v0 should expose any manual-override hooks (e.g. bar-1/meter), or strictly flag-only — a true zero-edit pipeline cannot override, so "flag for review" is the current honest compromise.
- **ASSUMPTION:** the target user is comfortable doing a short Moonscraper/EOF cleanup pass. If we later target non-technical users, a thin web editor moves from "optional" to "required" (deferred to [MVP Roadmap](./10-mvp-roadmap.md)).
