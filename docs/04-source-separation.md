# Source Separation (Stage 1 + Stage 2)
> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Specify how charter isolates a clean drum stem from a full mix (Stage 1) and optionally splits it into per-drum stems (Stage 2), and why this is the cheapest large lever on final chart quality.

## Related docs
- [Pipeline Architecture](./02-pipeline-architecture.md)
- [Drum Transcription](./05-drum-transcription.md)
- [Tech Stack and Deployment](./08-tech-stack-and-deployment.md)

---

## Why this stage is the biggest cheap quality lever

charter turns an mp3 into a playable Pro Drums chart. The single largest quality gain you can buy before touching the transcription model is **giving the drum transcriber a clean drum stem instead of the full mix.**

The QMUL study *"Enhanced Automatic Drum Transcription via Drum Stem Source Separation"* (arXiv:2509.24853) quantifies this directly. It isolates drums with Demucs v4 + ReplayGain normalization, then runs automatic drum transcription (ADT):

- **Drum-stem input: ~0.80 F-measure.** Full-mix input: **~0.65 F-measure.** That is a **~15-point F-measure improvement** purely from running source separation first.
- Reported per-test-set F-measures with the drum-stem front end: **0.89 (MDB), 0.63 (RBMA), 0.85 (ENST).**
- The same drum-stem front end also let them expand transcription from **5 to 7 classes** and add **MIDI velocity** — both directly relevant to Pro Drums charts (more lanes, dynamics).

**DECIDED:** Stage 1 (drum-stem isolation) always runs before transcription. This is non-negotiable in the pipeline; the cost is one separation pass, the payoff is ~15 F-measure points. See [Drum Transcription](./05-drum-transcription.md) for how the stem feeds the ADT model.

**Why it works:** vocals, bass, guitars, and synths share frequency bands and transient structure with drums and confuse onset/class detection. Removing them turns a polyphonic-mix problem into a near-solo-drum-kit problem, which is what every ADT model was trained to handle best.

---

## Stage 1 — Drum-stem isolation from the full mix

### SOTA landscape (2024-2026)

As of 2024-2026 the cleanest drum stem from a full mix comes from **RoFormer-family transformer models (BS-RoFormer / Mel-Band RoFormer) and SCNet-XL, NOT from Demucs.** Demucs remains popular only because it is trivially installable and offline — it is no longer SOTA for drums.

Drum SDR ranking on **MUSDB18HQ-only** training (source: ZFTurbo `pretrained_models.md`):

| Rank | Model | Drums SDR (MUSDB18HQ-only) |
|---|---|---|
| 1 | SCNet-XL IHF | ~11.81 dB |
| 2 | BS-RoFormer | ~11.61 dB |
| 3 | SCNet-Large | ~11.15 dB |
| 4 | htdemucs_ft (drums) | ~11.13 dB |
| 5 | htdemucs 4-stem | ~10.88 dB |
| 6 | Demucs3 mmi | ~10.70 dB |

With **extra training data**, drum-specialized ensembles pull far ahead (these are the cleanest drum stems publicly available, all on MVSEP):

- `MelBand + SCNet-XL + BS-RoFormer SW` ensemble = **14.35 dB** drums SDR
- `BS-RoFormer SW` single = **14.11 dB** drums SDR
- 4-stem ensemble (2nd place SDX Music Demixing) = **14.85 dB** drums SDR

> **RISK / Gotcha — SDR numbers are not cross-comparable.** MUSDB18HQ-only test (~11 dB) vs extra-data/specialized test sets (~14 dB) vs the aistemsplitter blog's standard test (~8-9.5 dB) all differ. Always record training data + test set with any SDR figure. Do not compare a ~14 dB ensemble number against a ~11 dB MUSDB-only number as if they ranked on the same scale.

### Tool comparison (Stage 1 candidates)

| Tool | Drums SDR | Runtime / HW | License | pip package |
|---|---|---|---|---|
| **Mel-Band RoFormer** *(recommended)* | ~11.4-11.6 dB (MUSDB-only ckpt), higher w/ extra-data ckpts | Heavy; GPU strongly preferred, CPU slow | model-dependent (code MIT via wrappers) | via `audio-separator` (default ckpt `mel_band_roformer_ep_3005_sdr_11.4360.ckpt`) |
| **BS-RoFormer** *(recommended alt)* | ~11.6 dB (MUSDB-only) → ~14.1 dB (specialized, extra data) | Heavy; GPU preferred | MIT (lucidrains impl); ckpts vary | via `audio-separator` (can load `bs_roformer_ep_317_sdr_12.9755.ckpt`) |
| **SCNet / SCNet-XL** | SCNet-XL IHF ~11.81 dB (best MUSDB-only) | GPU preferred | varies (starrytong / ZFTurbo ckpts) | via ZFTurbo MSS-Training repo |
| **Demucs v4 `htdemucs_ft`** *(fallback, no-GPU)* | ~9-11 dB | `_ft` runs 4 models, ~4x slower than `htdemucs`; ~real-time-to-2x on GPU, slow on CPU; **fully offline** | **MIT** | `pip install demucs` |
| **MDX23C / TFC-TDF-UNet v3 (MDX-Net family)** | ~11 dB region | GPU preferred | MIT | via ZFTurbo repo / kuielab sdx23 |
| **Open-Unmix (umx/umxhq)** | ~6-7 dB | fast, CPU-ok | MIT | `pip install openunmix` |
| **Spleeter** *(dated — avoid)* | ~5.9 dB | very fast (~40-90x realtime GPU) | MIT | `pip install spleeter` (TensorFlow, 2019) |
| **MVSEP ensemble** *(cloud, max-quality)* | up to ~14.35 dB (drum ensemble) / ~14.85 dB (4-stem) | Cloud, no local GPU needed | proprietary service (paid credits) | web + API only |

Notes on the dated tier: **Spleeter (Deezer, 2019, TensorFlow)** is fast but ~5.9 dB drums with audible artifacts — use only as a fast baseline, never for quality. **Open-Unmix** is a clean, documented BLSTM reference baseline (~6-7 dB) — valuable for reproducibility, not competitive for production stems.

### DECIDED stack (Stage 1)

**DECIDED:** Default self-hosted drum-stem extractor = a **Mel-Band RoFormer or BS-RoFormer drum checkpoint run via `audio-separator`** (pip, MIT — wraps MDX-Net/VR/Demucs/MDXC + RoFormer ckpts, auto-downloads models, CLI + Python API). This beats Demucs on the drum stem and is the easiest way to run RoFormer ckpts programmatically.

**DECIDED:** Fallback / no-GPU / commercial-safe path = **`htdemucs_ft` (`pip install demucs`, MIT, fully offline)**. Good enough quality (~9-11 dB drums), trivial dependency, commercially usable. Expose a runtime toggle: **fast baseline (htdemucs) ↔ best-quality (RoFormer)**.

**DECIDED:** Optional "high-quality" cloud tier = **MVSEP drum ensemble** (`MelBand + SCNet-XL + BS-RoFormer`, ~14.35 dB) via its web/API. Only when cloud upload is acceptable.

**ASSUMPTION:** `audio-separator` runs acceptably on Apple Silicon via its onnxruntime/torch backends. The CoreML / Apple-Silicon acceleration path is **not yet verified end-to-end** — see Open questions. On Apple Silicon without a working GPU/CoreML path, RoFormer CPU inference is slow; the htdemucs_ft fallback is the safe default there.

### Apple Silicon, runtime, and licensing notes (Stage 1)

- **RoFormer/transformer models are heavier than Demucs and benefit strongly from GPU; CPU inference is slow.** On a Mac the realistic options are: (a) CoreML/MPS acceleration if the wrapper supports it, or (b) accept slow CPU inference, or (c) fall back to htdemucs_ft. **OPEN:** confirm Mel-Band/BS-RoFormer via `audio-separator` actually uses a CoreML/MPS path on Apple Silicon rather than silently running CPU-only.
- **htdemucs_ft runs 4 separate models** → ~4x slower than htdemucs (~real-time-to-2x on GPU, slow on CPU). Budget runtime accordingly.
- **Config/ckpt pinning is mandatory.** Many community RoFormer ckpts need specific ZFTurbo YAML configs; a **mismatched config/ckpt silently degrades quality** without erroring. Pin model+config pairs and record SDR/test-set provenance in the pipeline config so regressions are detectable. See [Tech Stack and Deployment](./08-tech-stack-and-deployment.md).
- **Licensing:** Demucs (MIT), `audio-separator` (MIT), MDX-Net family (MIT), lucidrains BS-RoFormer impl (MIT) are commercially clean. **Individual RoFormer ckpt licenses vary** — verify the specific checkpoint weights before shipping commercially. MVSEP is a paid proprietary service with audio upload (privacy/IP concern).

> **RISK — transient smearing on cymbals.** RoFormer/transformer models can produce smearing or "phantom" artifacts on dense cymbal/hi-hat content **even when overall SDR is high.** Because charter's downstream task is onset detection + classification, evaluate **onset preservation, not just SDR**. A high-SDR stem that smears a fast hi-hat pattern can hurt transcription more than a lower-SDR stem that keeps transients crisp.

> **RISK — mp3 already smears cymbal transients.** charter's input is an uploaded mp3. Lossy compression preferentially damages high-frequency, high-entropy content — exactly cymbal/hi-hat transients — *before* separation ever runs. The separator cannot recover information the mp3 codec discarded. **ASSUMPTION:** typical user mp3s are 128-320 kbps; cymbal/hi-hat timing is the lane most at risk from the combined mp3+separator transient smear. Flag low-bitrate uploads (see Open questions).

---

## Stage 2 — Per-drum splitting (kick / snare / toms / hi-hat / cymbals)

### Why this matters for charting

Pro Drums needs more than "a drum hit happened here" — it needs the **right lane**: kick vs snare vs the three tom lanes vs the cymbal lanes (hi-hat / ride / crash). The hardest, worst-performing part of ADT is exactly **tom-vs-cymbal and cymbal-subtype classification**. Per-drum separation is the **tom-vs-cymbal arbiter**: if Stage 2 cleanly splits cymbals away from toms, lane classification becomes much more reliable than asking a single ADT model to disambiguate them from one mixed drum stem.

The QMUL recipe explicitly used drum-stem separation to expand from **5 to 7 classes** and recover **MIDI velocity** — both depend on cleaner per-component signals. See [Drum Transcription](./05-drum-transcription.md) for how Stage 2 stems feed (or back-check) the classifier.

**DECIDED:** Stage 2 is **optional / quality-tier**, not mandatory. It cascades after Stage 1 and is primarily used to arbitrate the tom-vs-cymbal lane and to recover hi-hat/ride/crash distinctions. The base pipeline can ship with Stage 1 + a multi-class ADT and add Stage 2 as a refinement.

### Tool comparison (Stage 2 candidates)

| Tool | Stems produced | Approach | Quality note | License |
|---|---|---|---|---|
| **DrumSep (inagoy/drumsep)** *(off-the-shelf pick)* | 4 (kick, snare, toms, cymbals); 5 adds hi-hat; 6 splits cymbals → hi-hat/ride/crash | Hybrid Demucs; pipeline auto-runs Demucs4 HT to isolate drums first, then DrumSep | MVSEP MelBand DrumSep reports per-stem SDR kick ~22.2, snare ~17.1 | see repo / HF `splitzo/drumsep` |
| **LarsNet (polimi-ispl/larsnet)** | 5 (kick, snare, toms, hi-hat, cymbals) | Bank of dedicated U-Nets; faster than real-time; optional alpha-Wiener filtering | **Beaten** by retrained MDX23C/BS-RoFormer per Mezza et al. 2024 | models **CC BY-NC 4.0 (non-commercial)**; StemGMD CC-BY 4.0 |
| **MDX23C / BS-RoFormer retrained on StemGMD** *(best-quality, commercial-safe)* | per-drum (configurable) | General music-demixing arch adapted to per-drum | **Outperforms LarsNet** at per-drum separation (Mezza et al. 2024) | MIT code; train on StemGMD (CC-BY 4.0) |
| **MVSEP DrumSep / LarsNet (cloud)** | as above | Hosted | Highest quality without local GPU | proprietary (paid) |

### The key benchmark and what it means

**Mezza et al. 2024** (IEEE Internet of Sounds, *"Benchmarking Music Demixing Models for Deep Drum Source Separation"*): general music-demixing architectures (**MDX23C/MDX32C, Band-Split HT-Demucs, BS-RoFormer**) retrained on the StemGMD dataset **OUTPERFORM the dedicated LarsNet U-Net bank** at per-drum separation.

Takeaway: **do NOT default to LarsNet.** For individual-drum stems, adapt a RoFormer/MDX23C model rather than use LarsNet off-the-shelf.

### StemGMD context

**StemGMD** is the training data behind LarsNet and the Mezza et al. retrained models: **1224 hours, 103,500 clips, a 9-piece kit, synthesized from Magenta Groove MIDI** rendered through sampled drum kits. License **CC-BY 4.0** (commercially usable, unlike LarsNet's NC weights).

> **RISK — synthetic domain gap.** StemGMD is **synthesized from MIDI, not real multitrack recordings.** Per-drum models trained on it can show a domain gap on real acoustic drums. Validate Stage 2 on **real acoustic drums** — e.g. jarredou's **150-track DrumSep validation set** — not just on StemGMD synthetic data.

### MDX23C 6-stem cymbal split

DrumSep's **6-stem mode splits the cymbals lane into hi-hat / ride / crash.** This is the finest-grained arbiter charter has for cymbal-subtype lanes in Pro Drums. It is also the most fragile (cymbals are the most transient-heavy, most mp3-damaged, most smear-prone content). Treat the 6-stem cymbal split as a best-effort refinement, not a reliable ground truth — back-check its output against the ADT classifier rather than trusting it blindly.

### DECIDED stack (Stage 2)

**DECIDED:** Off-the-shelf per-drum splitter = **DrumSep** (auto-cascades Demucs4 HT → DrumSep). Use 4/5/6-stem mode depending on how many cymbal lanes the chart needs.

**DECIDED:** For best quality **and** commercial licensing, the target is to **retrain an MDX23C or BS-RoFormer on StemGMD (CC-BY 4.0)** per Mezza et al. 2024, rather than ship LarsNet's NC-licensed weights. This is a later spike, not the v1 path.

**RISK — LarsNet licensing blocker:** LarsNet model weights are **CC BY-NC 4.0 (NON-COMMERCIAL)**. If charter is ever commercial, LarsNet weights cannot ship — retrain on StemGMD (CC-BY) instead. StemGMD the dataset is fine; LarsNet the trained weights are not.

### Cascade hygiene (Stage 1 → Stage 2)

- **Per-drum separators expect a DRUM stem as input, not a full mix.** Always run Stage 1 first (DrumSep does this automatically via Demucs4 HT). **Errors compound across the two stages** — a flawed Stage 1 stem poisons Stage 2.
- **RISK — Wiener/alpha filtering artifacts.** Alpha-Wiener filtering (used by LarsNet to reduce inter-stem crosstalk) can introduce **"ducking"/compression-like artifacts.** That is a direct problem when downstream onset/transcription depends on **transient integrity.** Prefer to preserve transients over minimizing crosstalk for charter's purpose.

---

## End-to-end recommendation (both stages)

1. **Stage 1 (always):** full mix → Mel-Band/BS-RoFormer drum stem via `audio-separator` (htdemucs_ft fallback on no-GPU / Apple Silicon CPU). Then **ReplayGain loudness normalization** (QMUL recipe) → feed ADT. This alone buys the ~15 F-measure points.
2. **Stage 2 (quality tier):** drum stem → DrumSep (4/5/6-stem) to arbitrate tom-vs-cymbal and recover hi-hat/ride/crash lanes + velocity. Optionally a StemGMD-retrained MDX23C/BS-RoFormer for best quality + clean licensing.
3. **Eval on the right metric:** for both stages, score **onset F-measure / transient preservation**, not just SDR — high-SDR RoFormer outputs can still smear cymbal transients. Validate on a real-acoustic-drum set (jarredou's 150-track set), not synthetic StemGMD.
4. **Pin everything:** model + ZFTurbo YAML config pairs, record SDR/test-set provenance in pipeline config, expose GPU/CPU and fast-vs-best toggles. See [Tech Stack and Deployment](./08-tech-stack-and-deployment.md).

---

## Open questions / TODO

- **OPEN:** Verify `audio-separator` actually uses a **CoreML/MPS Apple-Silicon acceleration path** for Mel-Band/BS-RoFormer ckpts, vs silently running CPU-only. If CPU-only, benchmark real wall-clock time on a typical Mac and decide whether htdemucs_ft should be the default on Apple Silicon.
- **OPEN:** Benchmark actual runtime of the default RoFormer ckpt and htdemucs_ft on the target Apple Silicon hardware for a ~4-minute song.
- **OPEN:** Confirm the exact license of the specific Mel-Band/BS-RoFormer checkpoint we ship (ckpt licenses "vary"); ensure it is commercial-safe if needed.
- **OPEN:** Decide whether to flag/handle low-bitrate mp3 uploads (cymbal transient damage is irrecoverable pre-separation). Define a bitrate threshold and user warning.
- **OPEN:** Decide v1 scope — does v1 ship Stage 2 at all, or Stage 1 + multi-class ADT only? Stage 2 is the tom-vs-cymbal arbiter but adds a second cascade stage and its own error budget.
- **TODO:** Stand up jarredou's 150-track DrumSep validation set and define an **onset-F-measure** eval harness (not SDR-only) for both stages.
- **TODO:** Spike retraining MDX23C / BS-RoFormer on StemGMD (CC-BY) to replace LarsNet's NC weights for the commercial-safe per-drum path; measure against DrumSep and LarsNet on real acoustic drums.
- **TODO:** Validate the full QMUL recipe (RoFormer drum stem → ReplayGain → ADT, 5→7 classes + velocity) reproduces the ~0.80 drum-stem F-measure on our test material.
- **OPEN:** Verify MVSEP API terms (audio upload, privacy/IP) are acceptable before offering it as a cloud quality tier.
