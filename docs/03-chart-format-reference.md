# Clone Hero Chart Format Reference

> **Status:** Living document · **Last updated:** 2026-06-20 · **Audience:** build agents & maintainers
> **Purpose:** The exact, exhaustive spec of the Clone Hero song folder, `.chart`/`.mid` encodings, `song.ini`, and audio stems — so serializer/parser agents can read or write a PLAYABLE Pro Drums chart with every number correct.

## Related docs
- [Lane Mapping & Difficulty](./07-lane-mapping-and-difficulty.md)
- [Pipeline Architecture](./02-pipeline-architecture.md)
- [Quality, Risks & Gates](./09-quality-risks-and-gates.md)

---

## 0. How to read this doc

This is the format **bible**. Downstream agents serialize the pipeline's internal `DrumNote` model into a real Clone Hero song folder, and may parse existing charts for reference/validation. Every byte value, tick number, and flag below is load-bearing. The single authoritative external spec is **TheNathannator/GuitarGame_ChartFormats** (`https://github.com/TheNathannator/GuitarGame_ChartFormats`); the de-facto correct parser to mirror is **Geomitron/scan-chart** (TypeScript, v8.0.1, Feb 2026), built to byte-match Clone Hero's own parser and validated against 40,000 charts.

**DECIDED:** We emit `.chart` (text, `Resolution=192`, drums-as-toms-by-default) as the canonical output. `.mid` is only for Rock Band ecosystem interop. See [§5 The Tom/Cymbal Inversion](#5-the-tomcymbal-inversion-1-serializer-bug) — this is the #1 serializer bug and the reason the format choice matters.

**DECIDED:** We keep one shared intermediate model — `DrumNote { lane ∈ {kick,red,yellow,blue,green/orange}, isCymbal: bool, isKick2x: bool, dynamic ∈ {ghost,normal,accent}, difficulty }` — and write format-specific serializers. This isolates the inversion to exactly one place. (Detail in [Lane Mapping & Difficulty](./07-lane-mapping-and-difficulty.md).)

---

## 1. Song folder anatomy

A Clone Hero song is a **folder** containing:

| Component | Filenames | Notes |
| --- | --- | --- |
| Chart | `notes.chart` **OR** `notes.mid` | Exactly one chart format. `.chart` = plaintext; `.mid` = binary MIDI (Rock Band lineage). |
| Metadata | `song.ini` | Under a `[song]` / `[Song]` header. Required for CH. |
| Audio | reserved stem filenames | One or more; see [§7 Audio](#7-audio-stems-codecs-sync). |
| Art (optional) | `album.*`, `background.*`, `video.*` | Referenced from `song.ini`. |

### File-name precedence rules
- The game prefers a file literally named **`notes`** over a custom-named chart file.
- The game prefers chart files with a **`[Y]` / `[F]` (forced-notes)** suffix over a `[N]` suffix.
- **Reserved audio filenames are preferred** over `.chart`'s `<X>Stream` metadata tags (see [§7](#7-audio-stems-codecs-sync)).
- If numbered drum stems `drums_1..drums_4` exist, a plain `drums` file is **ignored**.

**DECIDED:** The pipeline writes the chart as `notes.chart` (literal name, no bracket suffix needed for a fresh export) to hit the highest-precedence path.

---

## 2. `.chart` structure

`.chart` is INI-like: named `[Sections]` wrapped in curly braces. Required sections are `[Song]` (carries `Resolution`) and `[SyncTrack]`. Instrument sections are named `[<Difficulty><Instrument>]`.

```
[Song]
{
  Resolution = 192
  Offset = 0
}
[SyncTrack]
{
  0 = TS 4
  0 = B 120000
}
[ExpertDrums]
{
  0 = N 0 0
  192 = N 1 0
}
```

- **Difficulties:** `Expert`, `Hard`, `Medium`, `Easy`. Drum sections: `[ExpertDrums]`, `[HardDrums]`, `[MediumDrums]`, `[EasyDrums]`.

### Event line grammar
Every event line is:

```
<tick> = <TypeCode> <values...>
```

`<tick>` is an integer position in ticks. Type codes:

| Code | Meaning | Section | Form |
| --- | --- | --- | --- |
| `B` | Tempo | `[SyncTrack]` | `<tick> = B <BPM*1000>` |
| `TS` | Time signature | `[SyncTrack]` | `<tick> = TS <num> [<exp>]` |
| `A` | Tempo anchor | `[SyncTrack]` | `<tick> = A <microseconds>` — editor-only, ignore at playback |
| `N` | Note / modifier | instrument | `<tick> = N <type> <length>` |
| `S` | Special phrase | instrument | `<tick> = S <type> <length>` |
| `E` | Text event | any | `<tick> = E <text>` |
| `H` | Legacy GH1 hand anim | instrument | rarely used |

### Resolution
`[Song] Resolution` = **ticks per QUARTER note**. **Almost universally 192** (Moonscraper default). All `.chart` positions are integer ticks relative to this.

> **GOTCHA:** Resolution is ticks per *quarter note*, NOT per measure/bar. **DECIDED:** always emit `Resolution = 192`.

### Tempo (`B`)
`<tick> = B <tempo>` where `tempo` is **`BPM * 1000`** as an integer:
- `120000` = 120.000 BPM
- `150325` = 150.325 BPM
- Max 3 decimal places.

A `B` marker at tick 0 is **required** (defaults to 120 BPM if absent — but always emit one explicitly).

> **GOTCHA:** Tempo is `BPM * 1000`. Easy to off-by-1000. `B 120` would mean 0.12 BPM.

### Time signature (`TS`) — the `7 4` gotcha
`<tick> = TS <numerator> [<denominator exponent>]`. **The second number is an EXPONENT**, denominator = `2^exponent`. Exponent defaults to `2` (= `/4`).

| Line | Means | Why |
| --- | --- | --- |
| `0 = TS 4` | 4/4 | exponent omitted → `2^2 = 4` |
| `768 = TS 7 4` | **7/16** | `2^4 = 16`, NOT 7/4 |
| `1104 = TS 3 3` | 3/8 | `2^3 = 8` |

A `TS` at tick 0 is **required** (defaults 4/4).

> **RISK:** Writing `TS 7 4` intending 7/4 yields 7/16 and a corrupt measure grid. **DECIDED:** when serializing a time signature `n/d`, emit `TS n log2(d)` and only omit the exponent when `d == 4`.

### Tempo anchors (`A`)
`<tick> = A <microseconds>` locks a tempo marker to an audio time. **Editor-only; ignore at playback.** The pipeline does not emit these.

> **GOTCHA:** To convert tick↔seconds you MUST walk the `[SyncTrack]` tempo map and integrate over tempo segments. A single global BPM is wrong for any tempo-changing song. **DECIDED:** always build a full tempo map from `B`/`TS` markers; never assume constant BPM. See [Pipeline Architecture](./02-pipeline-architecture.md).

---

## 3. `.chart` DRUMS note types

Drum notes use `N <type> <length>`. `length` is in **ticks** (used for 5-lane sustains; `~0` for normal hits).

### Lane note types

| `<type>` | Lane | Notes |
| --- | --- | --- |
| `0` | Kick | |
| `1` | Red (snare) | Always a tom; never has a cymbal marker |
| `2` | Yellow | |
| `3` | Blue | |
| `4` | 5-lane Orange **OR** 4-lane Green | Value collision — resolve only after drum-type detection ([§6](#6-drum-type-detection-order)) |
| `5` | 5-lane Green | 5-lane only |
| `32` | **2x / Expert+ kick** | Separate, opt-in double-kick note |

> **RISK:** `N 4` is "5-lane Orange OR 4-lane Green" depending on detected track type. The same byte is two different lanes. Don't resolve it until [§6](#6-drum-type-detection-order) decides the type.

### Cymbal modifiers (opt-in; share the note's tick)

| `<type>` | Meaning |
| --- | --- |
| `66` | Yellow cymbal |
| `67` | Blue cymbal |
| `68` | Green cymbal |

A 4-lane note is a **cymbal only if** a cymbal modifier (66/67/68) shares its tick. **Default is TOM.** Red (1) is always a tom and has no cymbal marker. It is impossible to have a tom and a cymbal of the same color on the same tick.

### Dynamics modifiers (per-lane, share the note's tick)

| Range | Meaning |
| --- | --- |
| `34`–`38` | Accent (per lane) |
| `40`–`44` | Ghost (per lane) |

In `.chart`, dynamics use these **explicit modifier note types** — NOT velocity. (Contrast `.mid` §4, which uses velocity behind a gate.)

### Example: Pro Drums `.chart` snippet
A kick, a snare on red, a yellow **cymbal** (hi-hat), a blue **tom**, and a 2x kick — at quarter-note spacing on `Resolution=192`:

```
[ExpertDrums]
{
  0 = N 0 0      ; kick
  0 = N 32 0     ; 2x / Expert+ kick (opt-in, same tick as kick here for illustration)
  192 = N 1 0    ; red snare (always tom)
  384 = N 2 0    ; yellow note...
  384 = N 66 0   ; ...marked as a CYMBAL (hi-hat)
  576 = N 3 0    ; blue note — TOM by default (no modifier)
  576 = N 42 0   ; ghost on blue lane (40-44 range)
}
```

### Special phrases (`S <type> <length>`)

| `<type>` | Meaning | Final-tick behavior |
| --- | --- | --- |
| `2` | Star Power phrase | excludes final tick |
| `64` | SP / drum **activation (fill)** phrase | **INCLUDES its final tick** (start+length) — unlike all other phrases |
| `65` | 1-lane roll | |
| `66` | 2-lane roll | |

Rolls cannot apply to kicks.

> **RISK:** `S 64` is the ONLY special phrase that includes its final tick. Off-by-one here misplaces the activation note. Handle the `64` boundary as inclusive; all other phrase types as exclusive.

---

## 4. `.mid` format (Rock Band lineage)

**Use `.mid` only for Rock Band ecosystem interop.** It is harder to get right than `.chart`.

### Track & file requirements
- Drums track name: **`PART DRUMS`** (also accepted: `PART DRUM` for FoFiX; `PART DRUMS_2X` for the RBN 2x-kick variant; `PART REAL_DRUMS_PS` for Phase Shift).
- `notes.mid` **MUST be MIDI format type 1**, ticks-per-quarter resolution. **Type 0/2 and SMPTE timing are unsupported by CH.**

> **RISK:** Some Phase Shift charts violate the MIDI spec (running status after SysEx/meta, `0xFF` bytes in SysEx) and break strict parsers (e.g. NAudio). Generate clean type-1 MIDI with `mido`.

### Drum note numbers (one octave per difficulty)

| | Expert | Hard | Medium | Easy |
| --- | --- | --- | --- | --- |
| **Expert+ / 2x kick** | `95` | — | — | — |
| **Kick** | `96` | `84` | `72` | `60` |
| **Red** | `97` | `85` | `73` | `61` |
| **Yellow** | `98` | `86` | `74` | `62` |
| **Blue** | `99` | `87` | `75` | `63` |
| **4-lane Green / 5-lane Orange** | `100` | `88` | `76` | `64` |
| **5-lane Green** | `101` | `89` | `77` | `65` |

So Expert spans `95–101`, Hard `84–89`, Medium `72–77`, Easy `60–65`. (`95` = Expert+/2x kick exists only on Expert.)

> **RISK:** `100/88/76/64` mean "4-lane Green OR 5-lane Orange" depending on detected type — same collision as `.chart` `N 4`. Resolve after [§6](#6-drum-type-detection-order).

### Marker notes (above the per-difficulty octaves)

| Note | Meaning |
| --- | --- |
| `103` | Solo |
| `105` / `106` | P1 / P2 versus |
| `109` | Flam |
| `110` | **Yellow tom marker** |
| `111` | **Blue tom marker** |
| `112` | **Green tom marker** |
| `116` | Star Power / Overdrive |
| `120`–`124` | Fill / BRE markers — **all 5** needed for a BRE |
| `126` | 1-lane roll |
| `127` | 2-lane roll |

> **RISK:** A BRE requires all five of `120–124` present. Emitting fewer is invalid.

### `.mid` dynamics — velocity gated by `[ENABLE_CHART_DYNAMICS]`
- **Accent** = MIDI velocity `127`
- **Ghost** = MIDI velocity `1`
- **Normal** = any other velocity

These are **IGNORED unless the text event `[ENABLE_CHART_DYNAMICS]` is present on the drums track** (a legacy-compat gate).

> **RISK:** A parser that reads velocities unconditionally mis-marks dynamics on legacy charts. A serializer that encodes vel 127/1 dynamics but forgets `[ENABLE_CHART_DYNAMICS]` ships a chart where all dynamics are silently dropped. **DECIDED:** when emitting `.mid` with any accent/ghost, ALWAYS write the `[ENABLE_CHART_DYNAMICS]` text event.

### `.mid` rolls
Roll lanes `126`/`127` apply to **Expert only**, unless authored at velocity `41–50`, which also enables them on Hard.

---

## 5. The Tom/Cymbal inversion (#1 serializer bug)

**This is the single biggest gotcha for Pro Drums. Getting it backwards silently corrupts every chart.**

| Format | Default for a plain yellow/blue/green note | How to express the OTHER thing |
| --- | --- | --- |
| **`.chart`** | **TOM** | Add cymbal modifier `66`/`67`/`68` on the same tick |
| **`.mid`** | **CYMBAL** | Add tom marker `110`/`111`/`112` |

In both formats, **Red (snare) is always a tom**. The inversion only affects yellow/blue/green.

```
Same musical phrase (yellow = hi-hat CYMBAL, blue = rack TOM):

  .chart            ->  N 2 0  +  N 66 0   (yellow + cymbal modifier = cymbal)
                        N 3 0             (blue, no modifier = tom)

  .mid              ->  note 98            (yellow, no marker = cymbal)
                        note 99 + note 111 (blue + tom marker = tom)
```

> **DECIDED:** We emit `.chart`, where **toms are the default** and only cymbals need an opt-in modifier. This matches Moonscraper's native model and minimizes the surface area for the inversion bug. The shared `DrumNote.isCymbal` flag is consumed by exactly one place per format:
> - `.chart` serializer: emit `66/67/68` **iff** `isCymbal`.
> - `.mid` serializer: emit `110/111/112` **iff** `!isCymbal` (and never for red).

> **RISK:** Community MIDI→.chart converters frequently get this inversion wrong. Any borrowed mapping code MUST be re-verified against this table.

---

## 6. Drum-type detection order

The drum track type is **NOT stored explicitly** — one `[Drums]` / `PART DRUMS` track serves standard 4-lane, 4-lane Pro, and 5-lane. The game disambiguates at parse time in this order:

1. **`song.ini` flags first:** if `pro_drums` is true → force **4-lane Pro**; if `five_lane_drums` is true → force **5-lane**.
2. **Else heuristics:**
   - Cymbal markers present → **4-lane Pro**.
   - 5-lane green note present **OR** sustained notes → **5-lane**.
   - Otherwise fall back to **standard 4-lane**.
   - If both Pro and 5-lane signals appear, **prefer Pro**.

> **RISK:** `pro_drums` AND `five_lane_drums` both true is an **invalid state** — pick one (prefer Pro). Real-world `song.ini` files have inconsistent capitalization and may use `1`/`0` instead of `True`/`False`.

**DECIDED:** Our charts are 4-lane Pro. We set `pro_drums=True` so detection never relies on heuristics. **DECIDED:** treat `scan-chart`'s `drumType` output (`four-lane` / `four-lane-pro` / `five-lane`) as ground truth when validating ([§8](#8-validation)).

---

## 7. Audio: stems, codecs, sync

### Reserved filenames (any supported extension)
Audio is resolved by reserved filename, **preferred over** `.chart`'s `<X>Stream` tags:

| Filename | Content |
| --- | --- |
| `song` | background / no-stem mix |
| `guitar` | |
| `rhythm` | |
| `bass` | |
| `keys` | |
| `vocals` (`_1` / `_2`) | |
| `crowd` | |
| `preview` | |
| **`drums`** | single drum stem |
| **`drums_1`** | kick (+ anything not in 2–4) |
| **`drums_2`** | snare (+ rest) |
| **`drums_3`** | toms (+ cymbals) |
| **`drums_4`** | cymbals |

> **GOTCHA:** Stems are **cumulative** — `drums_1` = kick + anything not captured by `drums_2/3/4`. You cannot assume `drums_1` is kick-only unless `drums_2`, `drums_3`, AND `drums_4` all exist. And once any `drums_#` exists, a plain `drums` file is **ignored**.

### Codecs (decoded via FFmpeg in CH)

| Codec | Recommendation |
| --- | --- |
| `.opus` (libopus) | **Recommended** — ~80 kbps, best size/quality |
| `.ogg` (libvorbis) | Fine for a single file — Q8 / ~256 kbps |
| `.mp3` | **Discouraged** for new charts — 320 kbps |

**DECIDED:** encode stems to `.opus` (~80 kbps) via FFmpeg. If stemming drums, use `drums_1=kick`, `drums_2=snare`, `drums_3=toms`, `drums_4=cymbals` and set the corresponding mix config `5` ([§9](#9-mix--disco-flip-events)).

### Sync: `Offset` vs `delay`

| Mechanism | Where | Sign convention | Hash impact |
| --- | --- | --- | --- |
| `Offset` (seconds) | `.chart` `[Song]` | higher = audio starts **SOONER** | affects chart hash (safe) |
| `delay` (ms) | `song.ini` | higher = notes **LATER**; may be negative | **does NOT change the chart hash** |

> **RISK:** `delay` breaks leaderboard hash parity because it does not affect the chart hash. **DECIDED:** bake sync into the chart (prefer `.chart [Song] Offset`); **avoid `song.ini delay`.** Note the sign conventions are opposite between the two — do not copy one value into the other.

(Context: Clone Hero V1.0/V1.1, Nov 2024, shipped a reworked parser plus leaderboards — hence the hash-parity concern.)

---

## 8. `song.ini`

Lives under a `[song]` / `[Song]` header. Booleans accept `True`/`False` or `1`/`0`.

### Core fields
`name`, `artist`, `album`, `genre`, `year`, `charter` (alias `frets`), `rating`, `song_length` (ms), `preview_start_time` / `preview_end_time` (ms), `loading_phrase`, `playlist` / `sub_playlist`, `album_track` / `track`, `icon`, `background`, `video`.

### Drum-critical fields

| Field | Meaning |
| --- | --- |
| `diff_drums` | 4-lane difficulty number; **`-1` = track absent** |
| `diff_drums_real` | Pro Drums difficulty |
| `diff_drums_real_ps` | Phase Shift Real Drums difficulty |
| `pro_drums` | **boolean — FORCES the drums track to parse as 4-lane Pro** |
| `five_lane_drums` | **boolean — FORCES 5-lane** (never set together with `pro_drums`) |
| `delay` | ms offset; higher = later notes; can be negative. **Discouraged** (breaks hash). |

> Difficulty estimate numbers (`diff_*`) are typically `-1` (no track) or a `0–6` "intensity" scale shown as dots in the song list; `diff_band` is overall. **These are metadata only and do not affect note parsing.**

**DECIDED:** write `song.ini` with at minimum: `name`, `artist`, `album`, `genre`, `year`, `charter`, `diff_drums` (real `0–6` intensity, or `-1` if absent), **`pro_drums=True`**, `song_length`, `preview_start_time`, `preview_end_time`. Set `five_lane_drums` only if genuinely 5-lane (never both). **Avoid `delay`** — bake offset into the chart instead.

---

## 9. Mix / disco-flip events

Disco flip is encoded as a **`mix` text/local event, NOT a note flag**, and must be applied **per-difficulty over a range**.

| Format | Syntax |
| --- | --- |
| `.mid` | `[mix <diff> drums<config><flag>]` |
| `.chart` | `mix_<diff>_drums<config><flag>` (brackets/underscores/spaces all tolerated) |

`<diff>`: `0`=Easy, `1`=Medium, `2`=Hard, `3`=Expert.

### Flags
| Flag | Effect |
| --- | --- |
| `d` | **Disco flip.** On Pro Drums: swaps red ↔ yellow-cymbal note assignments to restore correct hands. On non-Pro: swaps snare/other stems. |
| `dnoflip` | Swaps stems **without** swapping Pro notes. |
| `easy` | mix variant |
| `easynokick` | mix variant |

### Stem config number (`<config>`)
| Value | Layout |
| --- | --- |
| `0` | single stereo stem |
| `1` | mono kick + mono snare + stereo other |
| `2` | mono kick + stereo snare + stereo other |
| `3` | stereo kick / snare / other |
| `4` | mono kick + stereo other |
| `5` | stereo kick / snare / toms / cymbals (community CH-43 extension, matches GH 4-stem layout) |

> **RISK:** Ignoring a disco-flip `d` event makes hi-hat sections play with the wrong hands on Pro Drums. **ASSUMPTION:** the v1 pipeline produces straightforward grooves and will **not emit disco-flip events**; if the transcription model later distinguishes hi-hat-on-snare-hand passages, revisit this. If we use the 4-stem drum layout (`drums_1..4`), emit mix config `5`.

---

## 10. Validation

**DECIDED:** the canonical acceptance check is **`scan-chart` (Geomitron)** — TypeScript, v8.0.1 (Feb 2026), explicitly built to **byte-match Clone Hero's own parser including the leaderboard hash**, and validated against **40,000 charts**. It extracts `drumType` (`four-lane` / `four-lane-pro` / `five-lane`), the `pro_drums` / `five_lane_drums` flags, per-difficulty note counts, and chart issues.

The validation gate (see [Quality, Risks & Gates](./09-quality-risks-and-gates.md)) round-trips our output through `scan-chart` (or Moonscraper's Song Validator) and asserts:
1. detected `drumType == four-lane-pro`,
2. expected per-difficulty note counts,
3. **zero parser issues**,

before the chart is considered shippable.

> **DECIDED:** Treat `scan-chart`'s `drumType` as ground truth for our own detection logic. If we need leaderboard parity ("will CH accept this and hash it identically"), shelling out to or porting `scan-chart` is the only correct check — a hand-rolled parser is not sufficient.

---

## 11. Tool landscape (candidates, with maturity caveats)

| Tool | Role | Maturity | Caveat |
| --- | --- | --- | --- |
| **GuitarGame_ChartFormats** (TheNathannator) | Spec of record | production reference docs | Vendor the relevant `.md` files into the repo for traceable citations. |
| **scan-chart** (Geomitron) | Canonical parser/validator | production, MIT (verify) | TS/Node — our validation gate mirrors or shells to it. |
| **Moonscraper** (FireFox2000000) | Reference C# read/write editor; writes `.chart`, im/exports `.mid` | production but **maintenance mode** | "Moonscraper 2" is the planned successor; original repo won't get major features. |
| **mido** | Python `.mid` read/WRITE | production, MIT | Gives resolution, tempo meta, time-sig meta, note_on/off + velocity. You implement the drum note-number map & tom-marker logic. Best choice for generating `.mid`. |
| **chartparse** (emptierset) | Python read-only `.chart` parser | community, Moonscraper-tested | **Models notes as guitar frets** — does NOT decode cymbal modifiers, dynamics, or 2x kick. You must layer drum semantics on top, or use scan-chart. |
| **chparse** (Kenny2github) | Older Python `.chart` parser | community | Lighter/less rigorous; verify drum handling. |
| **parsehero** (awphi) | Permissive TS parser (`.mid`+`.chart`) | community (verify) | More lenient than CH-exact scan-chart; verify drum-type/cymbal handling. |
| **Onyx** (mtolly) | RB↔CH conversion, 1x/2x kick handling, auto-1x from 2x | production, actively developed | Hub of the C3/RB→CH lineage; reference for 2x-kick reduction. |
| **C3 Authoring Tools** (Magma/REAPER) | Source of `.mid` drum conventions | legacy RB, still used | Where tom markers, `[ENABLE_CHART_DYNAMICS]`, mix/disco-flip originate. |
| **Auto-Chart Engine** (PyPI) | MIDI-drum → `.chart` worked example | community/research (Apr 2025) | **Re-verify** its cymbal/tom & 2x-kick mapping against this spec — community converters frequently get the inversion wrong. |
| **FFmpeg / libopus** | Encode/normalize audio stems | production | Encode to `.opus` ~80 kbps or `.ogg` Q8. |

---

## 12. Serializer checklist (`.chart`, our canonical output)

A correct `.chart` drum serializer must:

1. Emit `[Song] { Resolution = 192 }` and bake sync via `Offset` (seconds, higher = sooner) — **never** `song.ini delay`.
2. Build a full tempo map from `[SyncTrack]`; emit a `B` (BPM*1000) and `TS` (numerator + exponent, `2^exp` denominator) at **tick 0** explicitly.
3. Emit drum notes as `N <type> <length>` with **toms as default**; add cymbal modifier `66/67/68` **only** for cymbals (`isCymbal`). Red (`1`) is always a tom.
4. Encode dynamics as explicit modifier note types (`34–38` accent, `40–44` ghost) — **not** velocity.
5. Make 2x kick opt-in: emit kicks as `N 0` by default; emit `N 32` **only** for genuine double-pedal passages.
6. Emit the activation/fill phrase as `S 64` treating its **final tick as inclusive**; all other phrases exclusive.
7. Write `song.ini` with `pro_drums=True` so [§6](#6-drum-type-detection-order) detection never relies on heuristics.
8. Pass the output through `scan-chart` and assert `drumType == four-lane-pro`, expected note counts, and zero issues ([§10](#8-validation)).

---

## Open questions / TODO
- **Verify** `scan-chart` runs cleanly on Apple Silicon / our build environment, and confirm its license is MIT (source says "MIT (verify)").
- **Verify** the `drums_3` vs `drums_4` semantics in practice — source says `drums_3` = "toms (+cymbals)" and `drums_4` = "cymbals"; confirm against a real 4-stem chart and against the cumulative-stem rule before we commit to the 4-stem layout + mix config `5`.
- **OPEN:** Decide whether the v1 pipeline ever needs `.mid` output at all, or `.chart`-only ships. If `.mid` is needed, write a dedicated round-trip test asserting the tom/cymbal inversion is applied correctly (cymbal-default + tom markers `110/111/112`) and that `[ENABLE_CHART_DYNAMICS]` is emitted whenever vel 127/1 dynamics are present.
- **OPEN:** Disco-flip handling is deferred ([§9 ASSUMPTION](#9-mix--disco-flip-events)) — confirm the transcription model never produces hi-hat-on-snare-hand passages that would require a `mix_<diff>_drums<config>d` event, or add support.
- **OPEN:** Confirm the exact `diff_drums` / `diff_drums_real` intensity values our difficulty estimator should write (`0–6` scale) — metadata-only but affects the song-list display. See [Lane Mapping & Difficulty](./07-lane-mapping-and-difficulty.md).
- **Verify** whether we vendor `scan-chart` source or shell out to a Node process in the validation gate; tie this decision to [Quality, Risks & Gates](./09-quality-risks-and-gates.md).
- **Verify** Auto-Chart Engine's MIDI→`.chart` mapping against [§5](#5-the-tomcymbal-inversion-1-serializer-bug) before reusing any of its code.
