# Beat, Tempo, Downbeat & Quantization (Stage 3 + Stage 5)

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Define how charter derives a real tempo map, downbeats/meter, and song structure (Stage 3), then snaps drum onsets to a subdivided musical grid (Stage 5) so the output chart is actually playable.

## Related docs
- [Drum Transcription](./05-drum-transcription.md) — produces the raw onset/instrument events that Stage 5 quantizes.
- [Chart Format Reference](./03-chart-format-reference.md) — the `[SyncTrack]` and resolution spec the tempo map must emit into.
- [Quality, Risks & Gates](./09-quality-risks-and-gates.md) — validation gates for tempo drift, wrong bar-1, and meter errors.

---

## 0. Where these stages sit

```
mp3 ──► [Stage 1-2: load/demix] ──► Stage 3: beat / downbeat / tempo / structure ─┐
                                                                                   ├─► Stage 6: chart write
        Stage 4-5: drum onset transcription (see 05) ──► Stage 5: quantize ───────┘
```

- **Stage 3** turns audio into: beat times, downbeat times, a **per-beat tempo map**, time-signature events, and a functional structure segmentation (intro/verse/chorus/fill...). This becomes the `[SyncTrack]` plus the metadata that drives difficulty/star-power/fill placement.
- **Stage 5** takes the drum onsets from [Stage 4 transcription](./05-drum-transcription.md) and snaps them to a beat grid that is *subdivided between the Stage 3 beats* — never a fixed global-BPM grid.

These two stages share one spine: **the detected beat array**. Get the beats wrong and both the SyncTrack and the quantization are wrong.

---

## 1. Why a real TEMPO MAP, not a single global BPM

**DECIDED:** charter emits a **per-beat tempo map** (one tempo event per beat interval), never a single global BPM, for every chart.

> **RISK (the #1 unplayability cause):** Quantizing variable-tempo audio against one fixed global BPM is the dominant cause of drift and unplayable charts. A song that speeds up over its runtime will accumulate error; by the final chorus, notes that are correctly transcribed in *time* land in the *wrong grid cell*, and off-grid notes are literally unhittable in Clone Hero.

The mechanism: Clone Hero positions notes by **tick**, and ticks are converted to seconds through the `[SyncTrack]` tempo events. If the SyncTrack says "120 BPM forever" but the drummer drifted to 126 BPM, every later note's tick-to-second mapping is off, even when the audio-domain timing was perfect. The fix is to make the tempo map *follow the actual tempo curve* so the tick grid stays glued to the audio.

### Tempo map construction
For each consecutive beat pair from the tracker:

```
bpm_i = 60 / (beats[i+1] - beats[i])          # BPM for the interval starting at beats[i]
tempo_us_i = mido.bpm2tempo(bpm_i)            # microseconds-per-quarter-note
```

Emit one MIDI `set_tempo` meta message (or one `[SyncTrack]` `B` event) per beat. `pretty_midi` stores these internally as `_tick_scales`; `mido.bpm2tempo()` / `tempo2bpm()` convert between BPM and microseconds-per-quarter-note. Default MIDI tempo is `500000` us/qn (= 120 BPM).

**DECIDED:** coalesce runs of near-identical tempi within a small tolerance (e.g. `<0.5 BPM`) into a single event to reduce SyncTrack event count, **but preserve the curve** — do not flatten it to one value. Coalescing identical/near-identical tempi is safe; over-aggressive smoothing reintroduces drift.

> **ASSUMPTION:** `<0.5 BPM` coalescing tolerance is a reasonable starting default. Tune against the drift gate in [09-quality-risks-and-gates](./09-quality-risks-and-gates.md).

See the `[SyncTrack]` section of [03-chart-format-reference](./03-chart-format-reference.md) for the exact event syntax and tick resolution this map writes into.

---

## 2. SOTA beat / downbeat tracking (Stage 3 core)

**DECIDED:** Primary tracker = **Beat This!** (`beat-this`, checkpoint **final0**), run on GPU when available. It feeds the SyncTrack. Run **allin1** in parallel purely for functional structure and as a cross-check.

Beat This! outputs **beat times and downbeat times only** — no BPM, no time signature. We compute the tempo map (§1) and meter (§3) ourselves from those arrays.

### Comparison table

| Tool | Type | Outputs | Beat F1 (where known) | Maturity / install | Verdict |
|---|---|---|---|---|---|
| **Beat This!** (CPJKU, ISMIR 2024, MIT) | Offline CNN+transformer, no DBN | beat times, downbeat times (50 FPS, 22.05 kHz mono) | Ballroom **97.5**, Hainsworth **91.9**, Harmonix **95.8**, RWC Pop **96.1**; GTZAN **89.1 beat / 78.3 downbeat** | `pip install beat-this`; PyTorch ≥ 2.0; no madmom dep | **Primary tracker.** SOTA, clean install, handles tempo/meter changes. |
| **allin1** (mir-aidj, ISMIR 2023, MIT) | Offline all-in-one | bpm (global int), beats, downbeats, beat_positions (1-2-3-4), **segments** (10 functional labels) | SOTA on Harmonix all 4 tasks; beats *slightly weaker* than Beat This! | Needs **NATTEN** (historically no easy Apple-Silicon wheels) + **Demucs** (large model, GPU preferred). ~73 s for 33 min audio on RTX 4090 | **Structure + cross-check only.** Don't trust its scalar `bpm`. |
| **BeatNet** (mjhydri, ISMIR 2021, CC-BY-4.0) | Online/real-time joint beat+downbeat+tempo+meter (CRNN + particle filter) | (N,2) beats+downbeats; estimates meter unprimed | — | **Depends on madmom 0.16.1**, needs Python 3.9 + numpy shims | **Only if** we add live/streaming charting. Skip otherwise. |
| **madmom** DBNDownBeatTracker / RNNDownBeat (BSD + GPL-restricted parts) | RNN activations + DBN/HMM postproc | beats, downbeats | historical baseline | **Abandoned**: last release 0.16.1 (2018), Python ≤ 3.7 only, breaks on NumPy ≥ 1.24 & Python ≥ 3.10 | **Avoid as primary.** Optional DBN smoother only, in a pinned env. |
| **librosa.beat.beat_track** (ISC) | Dynamic programming over onset envelope | beats, single global tempo; **no downbeats, no meter** | weak | dependency-light, easy | **Baseline only.** Keep for cheap onset-envelope features feeding the quantizer. |
| **BeatFM / HingeNet** (2025, arXiv 2508.09790 / 2508.09788) | Fine-tuned music foundation models (MERT, MusicFM) | beats/downbeats; *claim* to edge past Beat This! | claimed > Beat This! (unverified here) | **No mature released package** | **Watch-list.** Re-evaluate when maintained weights ship. |

### Why Beat This! over the DBN baseline
Beat This! deliberately **removes the DBN**. Its **shift-tolerant loss** (max-pools predictions over 7 frames / ±70 ms before comparing to annotations) is what lets it drop the DBN and still handle tempo changes, time-signature changes, and tempos outside normal ranges. A `--dbn` flag exists for optional smoothing but is **not recommended/needed**.

> **RISK (madmom dependency trap):** madmom forces Python 3.9 + old NumPy and is unmaintained since 2018. Anything depending on it (BeatNet; allin1 internally in some paths) inherits this. Prefer Beat This!, which has **no madmom dependency**. If madmom's DBN is ever used as a post-smoother, isolate it in a pinned env.

> **RISK (madmom licensing):** parts of madmom are BSD but some components are restricted for commercial use. Verify before shipping a commercial charting product.

> **RISK (Beat This! resolution):** input is resampled to 22.05 kHz mono at 50 FPS internally → temporal resolution ~20 ms. **Do not** expect sub-20 ms onset precision from the beat grid itself. Fine drum-hit timing must come from the [Stage 4 onset/transcription stage](./05-drum-transcription.md), then be snapped to this grid.

---

## 3. Downbeat / meter difficulty → wrong bar-1

**RISK (the meter gate):** GTZAN downbeat F1 is still only **~78%** even for SOTA. Downbeat (hence time-signature / bar) detection is **materially less reliable** than beat detection. A wrong downbeat shifts **bar 1**, which cascades: fills land in the wrong bar, star-power phrases sit on the wrong boundary, and the crash-on-chorus-downbeat misses.

### Inferring time signature
```
numerator = count of beat times in [downbeat_k, downbeat_k+1)
```
- allin1's `beat_positions` gives this directly (max value per bar = numerator).
- Emit a MIDI/`[SyncTrack]` time-signature event **only at changes** (not per bar).
- Most charting formats (incl. Clone Hero `.chart` `[SyncTrack]`) store TS events as bar-position + numerator — see [03-chart-format-reference](./03-chart-format-reference.md).

### Cross-check Beat This! vs allin1
**DECIDED:** when both trackers run, cross-check Beat This! downbeats against allin1 `beat_positions`/`downbeats`.

- **Agreement** → high confidence; proceed.
- **Disagreement** (different bar-1 phase or different numerator) → **flag for manual review**. Do not silently pick one. This disagreement is a primary signal for the meter gate in [09-quality-risks-and-gates](./09-quality-risks-and-gates.md).

> **DECIDED:** always expose a **manual override for bar-1 position and time signature**. Downbeat F1 (~78% on hard sets) means automatic meter detection will occasionally be wrong on intros, pickup bars, and odd meters — exactly the spots where a human can fix it in seconds in Moonscraper but the auto-pipeline can't.

---

## 4. Quantization (Stage 5)

**DECIDED:** snap drum onsets to a **subdivided beat grid derived from the Beat This! beats** — interpolate N subdivisions *between each detected beat pair* — **not** a fixed-global-BPM grid.

```
# straight 16ths: 4 subdivisions per beat
for i in range(len(beats) - 1):
    t0, t1 = beats[i], beats[i+1]
    grid = [t0 + (t1 - t0) * k / 4 for k in range(4)]   # 16th-note grid lines for this beat
    # snap each onset in [t0, t1) to nearest grid line
```

Because the grid is rebuilt *per beat interval*, it follows the actual tempo curve automatically — this is the structural fix for the §1 drift problem at the onset level.

### Resolution policy (per region, not global)

| Region type | Grid | Subdivisions per beat |
|---|---|---|
| Most rock / metal drums (default) | straight 16th | 4 |
| Fast double-kick passages | straight 32nd | 8 |
| Swing / triplet regions only | triplet (1/8T, 1/16T) | 3 / 6 |

**DECIDED:** default to **straight 16ths**; promote to **32nds** only for fast double-kick; use **triplet grids only where swing/triplet is detected** (§4.2).

### 4.1 Snap strength — 100%, the opposite of music-production advice

**DECIDED:** quantize at **~100% snap strength** for game charts.

> This is deliberately the **opposite** of music-production guidance. DAW advice keeps ~80% strength to preserve human feel; but in Clone Hero / GH-style charts, **off-grid notes are unhittable**. You want every note exactly on a hittable grid line. 100% snap is correct here precisely because we are charting a playable game, not mixing a record.

### 4.2 Swing / triplet detection (per-segment, two-stage)

Swing = even 8th/16th notes played as the 1st + 3rd of a triplet.

**DECIDED:** two-stage quantize.
1. **Quantize hard to straight 16ths first** (establish the straight grid).
2. **Then** detect swing per region and apply a triplet grid only there.

Detection method — **onset-histogram clustering**: build a histogram of onset positions *within the beat* (phase 0..1). If a region's onsets cluster at **1/3 and 2/3** of the beat, that region is triplet/swing → switch it to a triplet grid (1/8T or 1/16T). Otherwise straight.

> **RISK (global triplet grid):** applying a triplet grid globally mangles straight sections, and vice versa. Triplet/swing detection **must be per-segment**. Detect per region, then use triplet grids only there.

---

## 5. Structure / segmentation (difficulty, star-power, fills)

**DECIDED:** run **allin1** in parallel and use its `segments[]` to drive chart musicality.

allin1 labels (10 functional types): `start, end, intro, outro, break, bridge, inst, solo, verse, chorus`. Each segment has `start`/`end`/`label`, and segment boundaries **align to downbeats** — exactly where phrase/activation markers belong.

| Structure signal | Charting action |
|---|---|
| `chorus` | Denser / harder patterns; higher star-power density. |
| `break` / `inst` / pre-chorus (last bar before a downbeat into a chorus) | Insert drum **fills**; put a **crash on the downbeat** entering the chorus. |
| `intro` / `outro` | Lower difficulty. |
| segment boundary (on downbeat) | Candidate phrase / star-power activation marker. |

This feeds difficulty modulation, star-power placement, and fill placement downstream. See [09-quality-risks-and-gates](./09-quality-risks-and-gates.md) for how fill/star-power correctness is gated.

> **RISK (allin1 install footprint):** allin1 needs NATTEN (historically no easy macOS / Apple-Silicon wheels) and Demucs (large model download, GPU strongly preferred). Plan for a heavier install footprint than Beat This! alone. If allin1 cannot be installed on a target platform, structure features degrade gracefully but beats/tempo still come from Beat This!.

---

## 6. DECIDED stack (summary)

| Concern | Decision |
|---|---|
| Primary beat + downbeat | **Beat This!** `beat-this`, checkpoint **final0**, GPU if available. `File2Beats → (beats, downbeats)`. |
| Tempo | **Per-beat tempo map** via `60/(beats[i+1]-beats[i])` → `mido.bpm2tempo`; coalesce within ~0.5 BPM. **Never** a single global BPM. |
| Time signature | Inferred from downbeat spacing; cross-checked vs allin1 `beat_positions`; emit only at changes. |
| Structure | **allin1** `segments[]` for difficulty / star-power / fills. |
| Quantization | Subdivided beat grid (16th default, 32nd double-kick, triplet only where swing detected), **~100% snap**, two-stage. |
| Swing detection | Per-segment onset-histogram clustering at 1/3, 2/3 of beat. |
| MIDI/SyncTrack emit | **mido / pretty_midi** (`set_tempo`, `time_signature`). |
| Real-time | **BeatNet** — only if a live/streaming charting feature is added. |
| Avoid as primary | **madmom** (dependency/license trap), **librosa.beat_track** (weak baseline; keep only for onset-envelope features). |
| Watch-list | **BeatFM / HingeNet** — future upgrade when maintained weights ship. |

---

## Open questions / TODO

- **OPEN (variable-tempo confidence):** we have no confidence score on the derived tempo curve. Decide whether disagreement between Beat This! inter-beat tempo and allin1 beats triggers a "low tempo confidence" flag, and what the gate threshold is. → [09-quality-risks-and-gates](./09-quality-risks-and-gates.md).
- **OPEN (manual-override compromise):** the honest target is "instantly playable AI draft + a few minutes of Moonscraper cleanup." Decide how much meter/bar-1 correction is exposed in-pipeline vs deferred to manual Moonscraper editing. Bar-1 and time-signature override are **DECIDED** to be exposed; the rest is open.
- **VERIFY:** Beat This! (`beat-this`, PyTorch ≥ 2.0) installs and runs on **Apple Silicon**; confirm `final0` checkpoint download path and float16/GPU behavior.
- **VERIFY:** allin1's **NATTEN** dependency now has usable macOS / Apple-Silicon wheels (historically it did not). If not, decide whether structure analysis runs only on a GPU/Linux worker.
- **VERIFY:** madmom licensing — which specific components are commercial-restricted — before any production dependency, including transitively via BeatNet/allin1.
- **OPEN (coalescing tolerance):** confirm the `<0.5 BPM` tempo-coalescing tolerance and 16th-default subdivision against real drift measurements; these are current **ASSUMPTION**s, not validated.
- **OPEN (BeatFM/HingeNet):** re-evaluate as a primary-tracker upgrade once a maintained package with released weights exists.
