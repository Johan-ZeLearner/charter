# Lane Mapping & Difficulty Reduction (Stage 6)

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** Specify the deterministic, zero-ML symbolic backend that converts GM-drum MIDI (with velocities) into playable Clone Hero Pro-Drums lanes and derives Hard/Medium/Easy from the Expert master.

## Related docs
- [Chart Format Reference](./03-chart-format-reference.md)
- [Drum Transcription](./05-drum-transcription.md)
- [Pipeline Architecture](./02-pipeline-architecture.md)

---

## 1. What this stage is

Stage 6 takes the **GM-drum MIDI with note velocities** produced by transcription (see [Drum Transcription](./05-drum-transcription.md)) and turns it into a **Clone Hero playable chart**: kick + 4 colored lanes (red/yellow/blue/green), each of yellow/blue/green carrying a per-note **cymbal-vs-tom** marker (Pro Drums), plus dynamics (ghost/accent), inferred 2x-kick, and the Hard/Medium/Easy difficulty tiers.

**DECIDED:** This is a **deterministic, rule-based** stage. As of 2024–2026 there is **no ML-based GM→CH drum mapper in production**; the state of the art is a configurable mapping table + a windowed collision resolver + rule-based difficulty thinning. This entire backend is therefore **testable with hand-made MIDI and zero ML** — you can write a 4-bar GM drum MIDI by hand, run Stage 6, and assert on the emitted chart. That makes it the natural MVP foundation (see [Pipeline Architecture](./02-pipeline-architecture.md)).

**DECIDED:** Emit **`.chart`** (Moonscraper/CH text format) as the primary output unless RB3/`.rba` compatibility is required. `.chart` is simpler to generate and is CH/YARG-native. The `.mid` (`notes.mid`) path is documented here too because EOF and RB tooling consume it. See [Chart Format Reference](./03-chart-format-reference.md) for the byte-level format; this doc covers the *mapping logic* that fills it.

---

## 2. Canonical GM → Clone Hero lane map

This is the reference table, seeded from **apvilkko/midi2clonehero** (the most accurate open-source GM→CH Expert Pro-Drums converter). Numbers are **GM percussion note numbers** (C1 = 36). Preserve these verbatim.

| GM note(s) | GM instrument | CH lane | Pro marker |
|---|---|---|---|
| 35, 36 | Acoustic / Electric kick | **Kick** | — |
| 37, 38, 39, 40 | Side stick, Acoustic snare, Hand clap, Electric snare | **Red** | (snare — no cymbal/tom marker) |
| 48, 50 | High tom, High-mid tom | **Yellow** | **TOM** |
| 45, 47 | Low tom, Low-mid tom | **Blue** | **TOM** |
| 41, 43 | Low floor tom, High floor tom | **Green** | **TOM** |
| 42, 44, 46 | Closed HH, Pedal HH, Open HH | **Yellow** | **CYMBAL** |
| 49, 52, 55 | Crash 1, China, Splash | **Blue** | **CYMBAL** |
| 51, 53, 57, 59 | Ride, Ride bell, Crash 2, Ride 2 | **Green** | **CYMBAL** |

Read the policy out of that table:

- **Snare / clap / sidestick → red.**
- **Hi-hats (42/44/46) → yellow CYMBAL.**
- **Toms high→low into yellow/blue/green TOM**, by pitch.
- **Crash1 (49), splash (55), china (52) → blue CYMBAL.**
- **Ride (51), ride-bell (53), crash2 (57), ride2 (59) → green CYMBAL.** So `crash2` and `ride` land on GREEN; every *other* crash lands on BLUE.

**RISK (tom bucketing 6→3):** Real GM defines **6 tom notes (41/43/45/47/48/50)** but CH has only **3 tom lanes**. The table buckets high→low: `48/50→yellow`, `45/47→blue`, `41/43→green`. This is a 6→3 reduction with judgment calls. Add a fallback for kits using non-standard tom notes, and **log when more than 3 distinct tom lanes are needed on one tick (physically impossible) and drop/merge.**

**RISK (crash vs ride is ambiguous):** A static table will mis-color busy two-cymbal passages. Crash/ride color is genuinely song-dependent. Do **not** hardcode it — make it a *resolvable policy* and run the windowed resolver in §4. (`apvilkko` uses exactly this; `auto-chart-engine` chooses the opposite convention `ride→blue, crash→green` — a config choice, **not** a standard. Pick one and expose it.)

**DECIDED:** Implement the map as a **configurable table seeded from midi2clonehero**, not as hardcoded `if`s, so non-standard kits and the crash/ride policy can be overridden.

### 2.1 4-lane vs 4-lane Pro vs 5-lane (GH)

| Mode | Lanes | Cymbal/tom info | Notes |
|---|---|---|---|
| **4-lane (standard)** | kick + red/yellow/blue/green | none — every colored gem is just a pad | Accents/ghosts silently disabled here |
| **4-lane Pro** ← *our target* | kick + red/yellow/blue/green | each Y/B/G gem flagged cymbal **or** tom | Full fidelity; dynamics live here |
| **5-lane (Guitar Hero)** | kick + red/yellow/blue/orange/green | no cymbal/tom toggle; 5th color instead | CH **squashes** this to 4-lane Pro at runtime |

**CH runtime 5-lane(GH) → 4-lane Pro auto-conversion** (authoritative, from the CH wiki):

```
Red             -> Red
Yellow          -> Yellow CYMBAL
Blue            -> Blue TOM
Orange          -> Green CYMBAL
Green           -> Green TOM
Orange + Green together -> Green cymbal + Blue tom
```

Reverse (4-lane Pro → 5-lane): `Yellow cym→Yellow cym, Yellow tom→Blue tom, Blue cym→Green cym, Blue tom→Blue tom, Green cym→Green cym, Green tom→Green tom`.

**DECIDED:** Author **native 4-lane Pro**. 5-lane is *supported* but gets squashed at runtime, so targeting it buys nothing and loses control. Set `five_lane_drums=False` in `song.ini`.

---

## 3. Pro-Drums semantics

### 3.1 Cymbal vs tom markers — and the inverted default

The cymbal/tom toggle is encoded **oppositely** in the two formats. **Do not mix these mental models** (this is the #1 footgun; RBN1 charts all became cymbals in RB3 because of it):

| Format | Default for an unmarked Y/B/G gem | How you flip it | Marker |
|---|---|---|---|
| **`.mid` (notes.mid / RB3)** | **CYMBAL** | add a tom marker | notes **110**=yellow, **111**=blue, **112**=green TOM markers spanning the gem |
| **`.chart` (Moonscraper/CH)** | **TOM** | add a cymbal flag | flags **66**=yellow cym, **67**=blue cym, **68**=green cym on the same tick |

So in our primary `.chart` output: a yellow/blue/green gem **without** its cymbal flag is a **tom**; you attach `66/67/68` to make it a cymbal.

**RISK:** You **must** set `pro_drums=True` in `song.ini` *and* include at least one cymbal marker, or the game treats the whole chart as toms (or all-cymbals in raw RB3). EOF's convention: if a chart contains at least one explicit cymbal, it writes tom-markers for all non-cymbal Y/B/G notes and sets `pro_drums=True`.

### 3.2 Hard constraint: same-color tom + cymbal collision

**A tom and a cymbal of the SAME color cannot occupy the same tick.** "Blue tom" + "blue cymbal" on one tick is **format-illegal**. A real drummer hitting a tom + crash simultaneously must be re-colored.

**DECIDED — collision resolver (always run as a final same-tick validator):**

1. Detect any tick where a tom and a cymbal share a color.
2. **Flip** one to a free cymbal color (blue↔green) — e.g. move the crash off the tom's color.
3. If no free color exists, **drop** the lower-priority gem (drop the cymbal before the tom, or per config).

`midi2clonehero` warns `Blue cymbal/pad overlap!` and resolves via its windowed flipper; `--cymbalflip` globally swaps blue/green cymbals, `--strict` disables all auto-improvements. The CH wiki documents the runtime same-color move (`blue cym→green cym`, `yellow tom→blue tom`). Port this resolver; it is **not optional** — the format forbids the collision.

### 3.3 2x-kick (double kick / Expert+) inference

Double kick is **not present in GM data semantically** — it must be **inferred** from fast successive kicks.

**DECIDED — inference rule:**
- Compute the inter-kick gap. Any Expert kick closer than **~150 ms** to the prior kick is marked as **2x / Expert+ kick**.
- Encoding: `.chart` **lane 32**; `.mid` **note 95**.
- **Expert ONLY.** This mirrors `EasyChartGenerator --doublekick <ms>` (recommended `150`; a negative value converts 32 back to 0).

**RISK:** Lower difficulties **must collapse 2x → single kick** (lane 32 → lane 0), or they become unplayable on a single pedal. This collapse happens in difficulty reduction (§6), not in mapping.

---

## 4. Crash/ride windowed collision resolver

The static table in §2 will mis-color busy passages. Add a **windowed crash/ride resolver** that runs before the §3.2 validator:

**DECIDED:** Within a window of **~1 beat**, if two cymbals would land on the **same color**, flip one between **blue↔green**. Concretely: if a ride already occupies green in the window, flip an incoming crash to blue (and vice versa). This is the heuristic `midi2clonehero` ships; expect to need it rather than a flat lookup.

Order of passes (mapping → legal chart):
```
1. table lookup (GM -> lane + cymbal/tom)        (§2)
2. windowed crash/ride color resolver (blue<->green within ~1 beat)  (§4)
3. same-tick tom-vs-cymbal-same-color validator (flip or drop)       (§3.2)
4. 2x-kick inference (Expert only)               (§3.3)
5. dynamics gating (ghost/accent)                (§5)
```

---

## 5. Dynamics — velocity gates

Velocity from transcription drives ghost/accent notes. **Defaults (from midi2clonehero; Fureniku uses the same):**

| Condition | Result |
|---|---|
| velocity **≤ 60** | **ghost** note (writes ghost flag) |
| velocity **≥ 120** | **accent** note (writes accent flag) |
| otherwise | normal |

Encoding:

- **`.chart`:** accent flags `34`=red, `35`=yellow, `36`=blue, `37`=green/orange, `38`=5-green; ghost flags `40`=red, `41`=yellow, `42`=blue, `43`=green/orange, `44`=5-green (on the same tick as the gem).
- **`.mid`:** dynamics are encoded by **note velocity directly** — accent = velocity **127**, ghost = velocity **1** — and **must** be enabled by the text event `[ENABLE_CHART_DYNAMICS]` in the track. Without it the velocity ghost/accent encoding is ignored.

**RISK:** Accents and ghosts exist **only in Pro Drums mode** — they are silently disabled on standard 4-lane Drums. Do **not** rely on them for core playability.

**DECIDED:** Expose the `60`/`120` thresholds as config. Only emit dynamics for Pro Drums and only on notes that **survive** difficulty reduction (§6).

---

## 6. Difficulty reduction (Expert → Hard / Medium / Easy)

**DECIDED:** Generate **Expert as the master**, then derive Hard/Medium/Easy by **rule-based thinning** — not ML. The most concrete open-source reference is **eerovil/EasyChartGenerator**'s `notes_to_diff_drums()` (operates per beat). Each difficulty is a **separate set of notes in the same track** (`PART DRUMS`).

**RISK:** Reduction is **per-instrument**. `EasyChartGenerator` has a separate `notes_to_diff_drums` vs `notes_to_diff_single` — **do not reuse the guitar reducer for drums**; it won't respect kick/cymbal semantics.

### 6.1 EasyChartGenerator `notes_to_diff_drums` logic (port this)

Pre-pass for all lower diffs: **strip cymbal markers (66/67/68) and accent markers (34/35/36)**, but **preserve ghost (40)**; re-attach cymbal/accent only to surviving notes. A `ms_delta_around` guard **promotes sparse sections** so isolated hits aren't deleted.

| Diff | Rule |
|---|---|
| **Hard** | on-beat = kick + one other gem; off-beat = up to **2** gems (drop the kick if >2 notes). Collapse 2x→single kick. |
| **Medium** | on-beats and off-beats **only** (drop anything off the 8th-note grid). On-beat = kick **or** one gem (fold **green 4→blue 3**); off-beat = up to **2** non-kick gems. |
| **Easy** | **only on-beats.** If a gem exists at beat-start keep kick, else keep **ONE** gem, and **fold blue(3)/green(4) down to yellow(2)**. |

Color-fold summary: **Medium folds green→blue; Easy folds blue/green→yellow.** Ghosts are preserved across all diffs; cymbal/accent markers are dropped on lower diffs and re-attached only to survivors. **All 2x kicks collapse to single kick on Hard and below.**

### 6.2 Official RB / C3 reduction guidance (human guidelines)

From the C3/RBN Drum Authoring docs (reduce **Expert → Hard → Medium → Easy** successively; C3 Automation Tools / CAT auto-does Expert→Hard):

- **Hard:** thin kicks to roughly **halfway between Medium and Expert**; remove kicks on adjacent 8th/16th notes and any kicks during fills. Keep crashes often **UNpaired** with kicks. Avoid 16th-note rolls at **≥140 bpm**; Hard 8th-note-stream ceiling **~170 bpm**.
- **Core principle:** when a note is removed, **never extend the previous note to fill the gap** — space teaches timing. (Validate the port against this rule.)
- In editors, removed/altered gems display as semi-transparent **"ghost" previews**.

**OPEN:** Whether to port `notes_to_diff_drums` verbatim or reimplement against the C3 bpm-ceiling guidance is unresolved. Recommended: port the beat-grid reducer first (deterministic, testable), then layer the C3 bpm guards as a second pass. Needs a spike.

---

## 7. Existing converters to reuse

| Tool | Use it for | Maturity caveat |
|---|---|---|
| **TheNathannator/GuitarGame_ChartFormats** | **Format ground truth** (`.mid`/`.chart` note blocks, tom markers 110/111/112, 2x-kick 95, cymbal flags 66/67/68, accent 34-38, ghost 40-44, `[ENABLE_CHART_DYNAMICS]`, disco flip). Implement **against** this. | Production reference spec for CH/YARG/Moonscraper; docs repo. |
| **apvilkko/midi2clonehero** | **Mapping table** (§2) + **velocity ghost/accent** + **crash/ride blue↔green collision flipper** (`--cymbalflip`/`--strict`/`--ghosts`/`--accents`). Best starting point for the mapping stage. | Community/research; small but directly applicable. |
| **Fureniku/Drum-MIDI-To-Clone-Hero-Converter** | **Pro markers + automatic 2x-kick** processing; cross-check for mapping decisions. Same GM convention. | Community Java GUI; actively maintained (updated 2026-01). |
| **eerovil/EasyChartGenerator** | **Difficulty reduction** (`notes_to_diff_drums`) + `--doublekick <ms>` 2x marking. | Community; actively maintained (updated 2026-06). |
| **Editor on Fire (EOF) / raynebc** | **MIDI import conventions** (auto-writes tom markers + `pro_drums=True` when any explicit cymbal exists); **QA oracle** for format legality (flags illegal tom/cymbal overlaps). "Paste From" / "Thin difficulty to match" for manual reduction. | Production editor; manual reduction workflow, **not** fully automatic for drums. |
| **C3 Automation Tools (CAT) + RBN/C3 docs** | Human reduction guidelines (kick thinning, fill removal, bpm ceilings). | Production RB community standard. **`docs.c3universe.com` serves an EXPIRED TLS cert** — fetch over http or via Wayback. |
| **auto-chart-engine (PyPI)** | Reference only. | v2.0.1 (2026); uses opposite `ride→blue, crash→green` convention — a config choice, not a standard. |

---

## 8. Playability & ergonomics constraints

The chart must be playable by a human on a 4-pad (+ pedals) kit, not just format-legal:

- **No impossible simultaneous hits.** More than the available limbs on one tick is unplayable; the same-color collision (§3.2) and the 3-tom-lane cap (§2) are the format-level expressions of this. **Log and drop/merge** when >3 distinct toms or an illegal overlap appears.
- **Physical e-kit vs visual lanes diverge.** The visual lane layout (red/yellow/blue/green) does not equal the physical pad layout; a chart that looks fine on screen can force a cross-handed pattern. Crash/ride coloring (§4) directly affects whether a two-cymbal passage is reachable.
- **Disco flip.** Steady 16th hi-hats with a snare backbeat on 2 & 4 play **wrong** if charted literally as red-snare + yellow-hat: a 4-pad player alternates hands on the hat and hits snare with the right hand. The human-feasible version swaps snare↔hat (hats on red, snare on yellow) via the text event `[mix <diff> drums0d]` (ON) / `[mix <diff> drums0]` (OFF).
  - **OPEN:** Whether to emit `[mix N drums0d]` events or pre-swap snare/hat coloring is unresolved. **DECIDED:** make disco-flip detection an **optional pass** (steady 16th hats + snare on 2&4). A naive GM mapper that ignores it produces technically-correct-but-awkward charts.
- **2x-kick collapse** (§3.3) is an ergonomics rule, not just a difficulty rule: a single-pedal player on Hard/below cannot play sub-150ms kicks.

---

## 9. song.ini requirements (so the game reads it correctly)

**DECIDED:** Write `song.ini` with **`pro_drums=True`** and **`five_lane_drums=False`**, and include **at least one cymbal marker** in the chart to avoid the all-toms default. Dynamics require **`[ENABLE_CHART_DYNAMICS]`** in the track or velocity ghost/accent encoding is silently ignored. See [Chart Format Reference](./03-chart-format-reference.md) for the full `song.ini` field list.

---

## Open questions / TODO

- **OPEN:** Final `.chart`-vs-`notes.mid` output decision — `.chart` recommended (CH/YARG-native, simpler), but confirm no RB3/`.rba` consumer needs `notes.mid`.
- **OPEN:** Port `EasyChartGenerator notes_to_diff_drums` verbatim vs reimplement with C3 bpm-ceiling guards layered on top — needs a spike (§6.2).
- **OPEN:** Disco-flip — emit `[mix N drums0d]` events vs pre-swap snare/hat coloring (§8). Make it an optional pass.
- **OPEN:** Crash/ride default convention — adopt midi2clonehero's `crash→blue, ride→green` (recommended) and expose the policy as config; document the deviation if auto-chart-engine's inverse is ever used.
- **VERIFY:** The exact `~150 ms` 2x-kick threshold and `60`/`120` velocity gates against real charted songs — these are converter defaults, expose as config and tune.
- **VERIFY:** Tom 6→3 bucketing (`48/50→Y`, `45/47→B`, `41/43→G`) holds for non-standard kits; add fallback + logging for out-of-table tom notes.
- **VERIFY:** Round-trip Stage 6 output through Editor on Fire (EOF) as the QA oracle to confirm no illegal same-color tom/cymbal overlaps slipped through.
- **VERIFY:** `apvilkko/midi2clonehero` and `EasyChartGenerator` run on Apple Silicon (both Python; likely fine, but unconfirmed); confirm each repo has a usable release/entry point before depending on it.
- **VERIFY:** C3 Drum Authoring docs are reachable despite the expired TLS cert (use http / Wayback) before treating them as the reduction spec.
