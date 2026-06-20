# Stage 4 — Drum Transcription (ADT Core: Audio → GM Drum MIDI with Velocity)
> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Define the Automatic Drum Transcription (ADT) stage that converts audio (full mix or isolated drum stem) into GM-mapped drum MIDI with per-onset instrument and velocity — the accuracy bottleneck of the whole `charter` pipeline.

## Related docs
- [Source Separation](./04-source-separation.md) — Stage 2/3, produces the drum stem (and per-stem loudness) this stage consumes.
- [Beat, Tempo & Quantization](./06-beat-tempo-quantization.md) — Stage 5, snaps the raw MIDI onsets this stage emits onto a grid.
- [Lane Mapping & Difficulty](./07-lane-mapping-and-difficulty.md) — Stage 6, turns the GM MIDI + velocity bands this stage emits into Clone Hero Pro Drums lanes.

---

## 1. What this stage does

Input: audio — either the full mix, or (preferred) the isolated drum stem(s) from [Stage 2](./04-source-separation.md).
Output: a standard **GM-mapped drum MIDI** file with one note per detected hit, carrying `(time, GM drum note number, velocity)`.

The task decomposes into three sub-problems, in order of difficulty:

1. **Onset detection** — *when* did a drum hit happen? Solved-ish, but it sets a hard **recall ceiling** (see §4) that caps everything downstream.
2. **Per-onset instrument / lane classification** — *which* drum (kick / snare / hi-hat / tom / crash / ride / …)? This is the real frontier; accuracy collapses as the class count grows (§3).
3. **Velocity estimation** — *how hard* was it hit? Decides ghost notes vs accents, which Pro Drums needs (§6).

> **Thesis check:** ADT is a **transcription** problem — reproduce the actual performance — not a creative-choreography problem. The job is to recover what the drummer played, including dynamics, not to invent a fun pattern. Everything here optimizes for fidelity to the real recording.

This stage's MIDI is *not* yet a chart. It is raw, un-quantized GM MIDI. Quantization is [Stage 5](./06-beat-tempo-quantization.md); lane assignment and difficulty are [Stage 6](./07-lane-mapping-and-difficulty.md).

---

## 2. State of the art and lineage

ADT in 2024–2026 has split into two practical camps:

1. **Production CRNN packages** (ADTOF the de-facto standard): reliably do **5 classes** (kick, snare, hi-hat, toms, cymbals) at high F-measure (~0.85–0.89 on MDB/ENST), but collapse ride/crash/splash into one "cymbals" class and historically do **not** output velocity.
2. **Research SOTA seq2seq Transformers** (MT3 / YourMT3+, synthetic-data Transformers) and the newest **diffusion models** (Noise-to-Notes, Sept 2025) that jointly predict onset **and** velocity.

### 2.1 Tool comparison

F-measures are **not** comparable across rows unless the onset tolerance window, class mapping, and "drum-only stem vs full mix" condition match (see RISK in §7). Numbers below are verbatim from the research source.

| Tool | Type / lineage | Classes | Velocity? | Reported accuracy (source caveats) | Code | Maturity |
|---|---|---|---|---|---|---|
| **ADTOF** (`MZehren/ADTOF`) | CRNN, crowdsourced-CH-chart trained | **5** (KD, SD, HH, toms, cymbals — crash/ride/splash **merged**) | **No** (released models) | 5-class F ≈ **0.89 MDB**, **0.85 ENST**, **0.63 RBMA** (Zehren et al., Signals 2023) | Public | Production (de-facto standard) |
| **Magenta OaF-Drums** (E-GMD) | Onsets-and-Frames CNN/RNN, E-GMD-trained | GM drum classes | **Yes** (native MIDI velocity) | onset F **0.83** / velocity F **0.62** on E-GMD (per N2N comparison) | Public | Production but **TF1-era, brittle install** |
| **Noise-to-Notes (N2N)** (arXiv 2509.21739) | Conditional **diffusion**, MERT-conditioned, Annealed Pseudo-Huber loss | onset + continuous velocity | **Yes** (best-in-class) | E-GMD onset **86.31** / velocity **80.16** (beats OaF 83.40 / 61.70); weaker OOD: IDMT 70.61, MDB 70.81. SOTA even at **5** diffusion steps | **Code unconfirmed** at search time | Research |
| **ADT_STR** (`pier-maker92/ADT_STR`) | Encoder-decoder Transformer, mel→MIDI tokens, **synthetic-only** training (CLAP-curated one-shots + Lakh MIDI) | 26 perc. (8 for benchmarking) | Onset-focused | F **0.73 ENST** / **0.79 MDB** (8-class); claimed SOTA in synthetic-data regime | Public | Research (Jan 2026) |
| **MT3** (`magenta/mt3`) | Multitask T5X seq2seq, multi-instrument | onset + GM drum type | **No** (no offset, effectively no velocity) | — (multi-instrument context only) | Public | Research, semi-maintained, Colab-only |
| **YourMT3+** (`mimbres/YourMT3`) | PerceiverTF + MoE + multi-channel decoder | drum onset + GM type | **No** (velocity tokens **removed**, kept 0/1) | onset F1 **87.27 ENST-drums**, **90.1 drum-F1 Slakh** | Public | Research, actively released (2024) |
| **Omnizart** (drum module) | General AMT toolbox | drums | No | pre-2022 drum models; not SOTA | Public (`pip install omnizart`) | Community, maintenance slowed |
| **ADTLib** (`CarlSouthall/ADTLib`) | Bidirectional-RNN | **3** (KD, SD, HH) | No | — (dated baseline) | Public | **Abandoned** — sanity baseline only |

**Enablers (source separation, not transcription)** — used to split the merged cymbal class and estimate per-stem velocity:

| Tool | Stems | Notes |
|---|---|---|
| **LarsNet** (`polimi-ispl/larsnet`) | **5** (kick, snare, toms, hihat, cymbals) | U-Net bank, faster-than-realtime, trained on StemGMD (1,224 h). Pattern Recognition Letters 2024. |
| **Jarredou MDX23C DrumSep** (`aufr33-jarredou_MDX23C_DrumSep_v0.1`) | **6** | Splits cymbals into **crash vs ride** and isolates open/closed hat. Community; via MVSep. Used by the 5→7 expansion paper. |

> See [Stage 2 / Source Separation](./04-source-separation.md) for where these stems are produced in the pipeline and how their loudness is exported for velocity.

### 2.2 Lineage to avoid for new work
**DECIDED:** Do **not** ship ADTLib (3-class RNN), the Vogl-et-al CNN/RNN line, or madmom drum transcription as the primary engine — all 3-class, dated, superseded. Keep at most one (e.g. ADTLib) as a sanity baseline. **DECIDED:** Do **not** use MT3 / YourMT3+ as a velocity source — they are onset+GM-type only; YourMT3+ explicitly stripped velocity tokens.

---

## 3. The class-count frontier (the central hard problem)

3-class (KD/SD/HH) is essentially **solved**. Everything past it degrades, and the degradation is now quantified.

**FRONTIER QUANTIFIED — STAR Drums benchmark (ISMIR TISMIR 2025), F-measure on the MDB-Drums test set:**

| Class count | F-measure |
|---|---|
| 3-class | **0.81** |
| 5-class | **0.79** |
| 8-class | **0.75** |
| 18-class | **0.67** |

This monotonic 0.81 → 0.67 drop on the *same* test set is the single clearest published number for the "toms / ride / crash / ghost" difficulty cliff.

What specifically collapses past 3-class:
- **Toms** (multiple pitched toms vs each other).
- **Ride vs crash vs splash** — the hardest cymbal disambiguation. ADTOF merges all three into one "cymbals" class precisely because separating them is unreliable. The blue/high-tom-vs-ride region is a known bottleneck.
- **Open vs closed hi-hat.**
- **Ghost notes & accents** — low-velocity vs high-velocity hits (a velocity problem, §6, but also a recall problem: ghost notes are quiet and easily missed).

**RISK:** Aggregate F-measure hides exactly these frontier failures. **DECIDED:** Track F-measure **separately** for toms, ride-vs-crash, open-vs-closed hat, and ghost-note recall in CI — do not gate on a single aggregate number (recall the 0.81 → 0.67 cliff).

---

## 4. The onset recall ceiling (invest here first)

Classification can only label hits the onset detector found. Missed onsets are unrecoverable downstream — no lane mapping or velocity model can resurrect a hit that was never detected.

**The ceiling:** roughly **~89% of true hits fall within ±100 ms of *some* detected onset** — a hard cap on recall *before* any classification happens. Whatever the classifier's headline F-measure, the achievable note recall is bounded by the onset stage.

**DECIDED:** Invest in onset recall **first**. A more accurate classifier on top of a leaky onset detector wins nothing. Tune the onset front-end (and the source-separation that feeds it) before optimizing class disambiguation.

> **Note on tolerance windows:** ADT onsets are typically scored with a **50 ms** (±25–50 ms) tolerance. The ~89% recall ceiling above is quoted at **±100 ms** — a looser window. Keep the window explicit in every reported number; headline figures across papers are otherwise not comparable (§7).

---

## 5. Datasets and what they enable

| Dataset | Size | Type | Velocity? | What it enables |
|---|---|---|---|---|
| **E-GMD** (g.co/magenta/e-gmd) | **444 h**, 43 kits | onset+velocity MIDI, CC BY 4.0 | **Yes** | The **only large dataset with onset+velocity MIDI** → velocity-aware training (OaF, N2N). |
| **GMD (Groove MIDI)** | symbolic | MIDI | (symbolic) | Underlies E-GMD and StemGMD. |
| **StemGMD** | **1,224 h**, 9-piece kit | synthesized stems from GMD | — | Trains source-separation (LarsNet). |
| **ENST-Drums** | ~61 min | real audio | — | Standard real-audio **test** benchmark. |
| **MDB-Drums** | ~21 min | real audio | — | Standard real-audio **test** benchmark. |
| **ADTOF corpus** | ~359 h | crowdsourced CH game charts | — | Large training corpus for the production CRNN. |
| **STAR Drums** (TISMIR 2025) | **124.5 h**, FLAC 48 kHz | **18 classes**, velocity via **ITU-R BS.1770-4** loudness | **Yes** | Large training/eval for **full-kit + velocity**; source of the 3/5/8/18-class degradation numbers. |

**DECIDED — training/eval split:**
- Train velocity-aware models on **E-GMD** (only large onset+velocity corpus) **plus STAR Drums** (18-class + ITU-R loudness velocity) for full-kit coverage.
- **Always** report cross-dataset on **ENST-Drums** and **MDB-Drums** (and **RBMA**) with a **50 ms** onset window — this exposes the synthetic-to-real gap.

**RISK (synthetic-to-real domain gap):** Models trained on SoundFont/synth data (and the synthetic Transformer ADT_STR) degrade on real recordings. Conversely, E-GMD-trained models can be weaker out-of-distribution (N2N: E-GMD 86 but MDB ~71). Cross-dataset evaluation is mandatory before trusting any number.

---

## 6. Velocity → dynamics (not an afterthought for Pro Drums)

**Why it matters:** Magenta's listening study found velocity prediction won **919 vs 456** pairwise comparisons over fixed-velocity output — predicting velocity nearly **doubled** perceptual-quality wins. Ghost notes are low-velocity snare hits; accents are high-velocity. Both **vanish** without a velocity-aware model or stem-loudness post-processing. For a playable Pro Drums chart that feels like the real performance, velocity is decisive.

**Two ways to get velocity:**

1. **Velocity-aware model** — the model emits per-note velocity directly:
   - **OaF-Drums (E-GMD)** — proven, native MIDI velocity (velocity F 0.62 on E-GMD). The TF1-era fallback when you need velocity today.
   - **Noise-to-Notes (N2N)** — best-in-class joint onset+velocity (velocity F **80.16**), but **code unconfirmed** (§7).
2. **Per-stem loudness post-processing** — derive velocity from the separated drum stems (from [Stage 2](./04-source-separation.md)): apply an **equal-loudness / ITU-R BS.1770** filter, take **RMS**, and take the **max in a ~50 ms window** around each onset; normalize across stems. This is the recipe in arXiv 2509.24853 and needs no velocity-aware model.

**Velocity → Pro Drums bands** (handed to [Stage 6](./07-lane-mapping-and-difficulty.md)): threshold velocity into **ghost (~<40) / normal / accent (~>100)** bands. STAR Drums centers velocity ~**105** with a floor ~**40** — a useful prior.

---

## 7. DECIDED engine choice + cross-check strategy

### 7.1 Primary pipeline

**DECIDED — default pipeline** (best quality-vs-effort, **all public code**; reproduces arXiv 2509.24853, which beats an 8-class baseline by **+10–12%** on ENST/MDB):

```
(a) [optional] drum source separation of the full mix into stems
    → LarsNet (5-stem), or Jarredou MDX23C (6-stem) if you need crash/ride split
(b) run ADTOF (or ADTOF-pytorch) on the drum stem/mix
    → onset + instrument, 5 classes (KD, SD, HH, toms, cymbals)
(c) expand 5 → 7 classes:
    - assign ADTOF "cymbal" onsets to CRASH vs RIDE, and
    - "hi-hat" onsets to OPEN vs CLOSED,
    by which separated stem carries energy at that onset
(d) estimate velocity per onset from per-stem loudness:
    equal-loudness / ITU-R BS.1770 filter + RMS, max in a 50 ms window, normalize across stems
```

Resulting 7 classes: **kick, snare, closed-hat, open-hat, tom, crash, ride.** Reported: MDB **0.84 vs 0.72** (+12%), ENST **0.76 vs 0.65** (+10%); slightly worse on RBMA (0.56 vs 0.58).

> Source notes a "STRUM" CH-tuned end-to-end engine (~0.838 drum F1 at ±100 ms, ~6 GB model) as a candidate primary; the provided research file does not document STRUM's repo/install. **OPEN:** confirm STRUM's repo, release, and Apple-Silicon support before adopting it as primary. Until then, **ADTOF + 5→7 stem-expansion + stem-loudness velocity** is the DECIDED, all-public-code default above.

> **ADTOF install (from source):** `pip3 install .`; CLI `drumTranscriptor`; outputs MIDI. The **ADTOF-pytorch** variant drops the TensorFlow/madmom deps at ~**−0.2% F-measure** cost and is the easier modern entry point.

### 7.2 Independent cross-check / verifier

**DECIDED:** Run a **second, independent transcriber as a verifier** to catch frontier errors (the class-count cliff means single-engine output is untrustworthy on toms/cymbals/ghosts). The primary engine emits notes; a disagreeing verifier flags low-confidence onsets/classes for the cleanup pass.

Candidate verifiers (orthogonal to the ADTOF+stem primary so failures don't correlate):
- **OaF-Drums (E-GMD)** — independent architecture, *and* supplies native velocity as a cross-check on stem-loudness velocity.
- **ADT_STR** — independent (synthetic-trained Transformer); useful as a class-disambiguation second opinion. Run: `python inference.py configs/eval/ENSTinference.yaml`.

> Source frames a "STRUM primary, ADTOF independent verifier" cross-check. With STRUM unverified (above), the build-now form is **ADTOF-stem-expansion primary + OaF/ADT_STR verifier**; swap STRUM into the primary slot once its repo is confirmed.

### 7.3 RISK flags on non-turnkey repos
- **RISK (no public code):** **N2N diffusion** and the **5→7 stem-expansion paper (2509.24853)** had **no public code** at search time — budget for reimplementation or wait for releases. Public code exists for ADTOF, ADT_STR, MT3, YourMT3+, LarsNet.
- **RISK (brittle install):** **OaF-Drums** and **MT3** are TensorFlow-1 / T5X-era (old CUDA/TF deps, Colab-oriented). Prefer **ADTOF-pytorch** and **ADT_STR** (PyTorch/HuggingFace) for reproducible builds. **OPEN:** verify each chosen engine runs on **Apple Silicon**.
- **RISK (drum-only vs full-mix):** many headline F-measures are on **drum-only** ENST/MDB stems, not full songs — real-world full-mix accuracy will be lower. This is the strongest argument for running ADT on the separated drum stem from [Stage 2](./04-source-separation.md).

---

## 8. Output format (contract for Stage 5)

Emit **standard GM-mapped MIDI with per-note velocity.** GM mapping is **not** standardized across tools — confirm the exact mapping and whether the tool emits separate open/closed hat or a single hi-hat *before* wiring output.

```
GM drum note numbers (verbatim from source):
  36  kick
  38  snare
  42  closed hi-hat
  44  pedal hi-hat
  46  open hi-hat
  45 / 47 / 48 / 50  toms
  49  crash
  51  ride
```

(MT3-family standard mapping seen in source: 36=kick, 38=snare, 42=closed-hat, 47=low-mid tom, 49=crash, 51=ride.)

Each emitted note: `(onset_time, GM_note, velocity)`. Velocity bands for Pro Drums: ghost `~<40` / normal / accent `~>100`. This MIDI is consumed un-quantized by [Stage 5](./06-beat-tempo-quantization.md); band/lane semantics are finalized in [Stage 6](./07-lane-mapping-and-difficulty.md).

---

## 9. Extensibility (optional, later)

**OPEN / candidate:** for per-kit / user-custom kits (live or library-specific), the **dynamic few-shot prototypical-network** approach (Weber/Uhle/Müller/Lang, IEEE IS2 2024, DOI 10.1109/IS262782.2024.10704130) lets users register custom toms/cymbals from a few examples at inference, real-time, without retraining. Evaluate only if per-kit generalization becomes a requirement.

---

## Open questions / TODO
- **Verify STRUM:** confirm repo, release availability, ~6 GB model, ~0.838 drum F1 at ±100 ms claim, and **Apple-Silicon support** before adopting it as primary engine. Source file does not document STRUM's repo/install. (**OPEN**)
- **Confirm N2N code release** (arXiv 2509.21739). Until then it is an architectural target (diffusion + MERT features + Annealed Pseudo-Huber loss), not a drop-in. (**RISK: no public code**)
- **Confirm 5→7 stem-expansion code** (arXiv 2509.24853) — currently must be reimplemented from the paper. (**RISK: no public code**)
- **Verify Apple-Silicon / reproducible install** for each engine actually shipped (ADTOF / ADTOF-pytorch, OaF-Drums TF1, ADT_STR). (**OPEN**)
- **Validate the onset recall ceiling** (~89% within ±100 ms) on our own real-mix audio post Stage-2 separation — confirm it holds and isn't worse on full mixes. (**OPEN**)
- **Pin GM mapping per chosen engine** — verify whether each emits separate open/closed hat or a merged hi-hat, and the exact tom note numbers, before wiring Stage 5. (**OPEN**)
- **Decide velocity source of truth** — model-native (OaF/N2N) vs per-stem loudness (2509.24853 recipe) vs both, and how to reconcile when the verifier disagrees. (**OPEN**)
- **CI metric harness:** implement per-class F-measure tracking (toms, ride-vs-crash, open-vs-closed hat, ghost-note recall) at a fixed 50 ms window — not a single aggregate. (**TODO**)
