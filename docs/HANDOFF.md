# Handoff & Open Issues

> **Status:** Living handoff · **Last updated:** 2026-06-20 · **Audience:** the next build agent(s)
> **Purpose:** Where the project actually stands, the BLOCKING open bug, what was already tried (so you don't repeat it), and the remaining work. Read [README.md](./README.md) first for the doc map, then this.

---

## 🔴 BLOCKING BUG #1 — Clone Hero shows **"No Part"** (no playable instrument)

**This is the top priority. Nothing else matters until a generated chart actually loads as playable drums in the user's real Clone Hero.**

### Symptom
A generated song folder is added to Clone Hero. **The song appears and the audio plays**, but the instrument/difficulty screen shows **"No Part"** — no drums (no playable chart). Reported by the user on a real song (`mp3/clay.mp3` → `out/clay/`) **and** still occurring after the format-hardening fix below.

### The core contradiction (start here)
`scan-chart` — which is *supposed* to byte-match Clone Hero's own parser (v8.0.1, validated on 40k charts) — **accepts our chart**:
```
drumType = fourLanePro, playable = True, instruments = ['drums'],
noteCounts: drums/expert = 1690, PASS
```
…but the user's **actual Clone Hero disagrees** and shows no part. So either (a) scan-chart ≠ the user's CH version, (b) a Clone Hero **song-cache / rescan** problem, or (c) a subtle `.chart`/`song.ini` issue scan-chart tolerates but CH does not. **We do not yet know which.** Do not trust the scan-chart PASS as proof the user's CH will load it — that assumption is exactly what's in question.

### What was already tried (commit `ef4483c`) — did NOT fix it
The first output had a minimal `[Song]` block, no `[Events]` section, and an empty `year =` line. We hardened the serializer to match what Moonscraper actually writes:
- `[Song]`: full key set (`Album`, `Year`, `Player2`, `Difficulty`, `PreviewStart/End`, `Genre`, `MediaType`) + `MusicStream = "song.opus"`.
- Added an (empty) `[Events]` section.
- `song.ini`: dropped the empty `year =`, added `diff_drums_real`.

Result: `out/clay/notes.chart` now has `[Song]` / `[SyncTrack]` / `[Events]` / `[ExpertDrums]` (1690 notes), `pro_drums=True`. scan-chart still PASSes. **User reports the "No Part" issue persists.** So format minimalism was *not* the (whole) cause.

### Leads / next steps, in priority order
1. **Confirm a TRUE full rescan, not a cached result.** CH caches scans in `songcache.bin`. If the song was first seen with the broken pre-fix chart, CH may keep the cached "no part". **Delete the song from the library AND delete/secure `songcache.bin`, then full-rescan.** This is the cheapest possible cause and must be ruled out first. (Audio playing proves the folder is scanned, but not that the chart was re-parsed.)
2. **Get the user's exact Clone Hero version.** scan-chart 8.0.1 targets a specific CH parser; a mismatch (older/newer CH) could explain the disagreement.
3. **Moonscraper round-trip (isolates our serialization).** Open `out/clay/notes.chart` in Moonscraper:
   - If Moonscraper **loads the drums track** → our serialization is structurally fine; re-export from Moonscraper and test *that* in CH. If the Moonscraper re-export loads but ours doesn't → diff the two files byte-for-byte to find what CH cares about.
   - If Moonscraper **also shows nothing** → our `.chart` is malformed in a way scan-chart misses. Diff against a known-good chart.
4. **Diff against a known-good community chart** that *does* load in the user's CH: compare `notes.chart` header/section structure and `song.ini` field-by-field. Look especially at: file **encoding** (UTF-8 vs UTF-8-BOM), **line endings** (we emit `\n`; some tooling expects `\r\n`), and section/key casing.
5. **Try emitting `notes.mid` instead** as a cross-check (docs/03 §4 has the full spec: `PART DRUMS`, type-1, note numbers 95–101, tom markers 110/111/112, `[ENABLE_CHART_DYNAMICS]`). If the `.mid` loads but the `.chart` doesn't, the bug is `.chart`-specific.
6. **Re-examine drum-type detection.** We set `pro_drums=True`. Confirm against the user's CH that a `.chart` Expert-only drums track with `pro_drums=True` is actually offered as a part. (Our chart has only `[ExpertDrums]`, no Hard/Medium/Easy — confirm CH doesn't require lower difficulties to show the part. scan-chart did not flag this, but verify in-game.)

### Useful facts already established
- `mp3/clay.mp3` has a **~13 s drumless intro** (first note ~tick 4992). Not related to "no part", but explains sparse early output.
- Files in `out/clay/`: `notes.chart` (40 KB, 1690 notes), `song.ini` (pro_drums=True), `song.opus` (3.3 MB, plays fine).

---

## What is built and working (as of 2026-06-20)

The pipeline runs **end-to-end**: `audio file → out/<song>/ (notes.chart + song.ini + song.opus)` that **scan-chart** reports as `fourLanePro` / `playable=True`. See [README.md](./README.md) for run/test commands and [10-mvp-roadmap.md](./10-mvp-roadmap.md) for phase status.

- **Phases 1–2 (symbolic backend):** `charter/drumnote/` (DrumNote model + `.chart` serializer + song.ini — the format firewall) and `charter/mapping/` (GM→CH table, collision resolver, 2× kick, dependency-free SMF loader). Deterministic, unit-tested.
- **Phase 3 (audio frontend):** `charter/audio/` — FFmpeg ingest, HPSS separation (+ optional Demucs), numpy DP beat tracker + smoothed tempo map, band-energy kick/snare/hat ADT, quantization. **Baseline-grade.**
- **Phase 4 (partial):** GO/CAUTION/REFUSE drum-RMS gate is in; **REVIEW.md artifact is NOT** (see remaining work).
- **Validation gate:** `tools/validation/` (Node ≥24 scan-chart) + `charter/validate.py`.
- **37 tests pass** (`python -m pytest`). scan-chart / ffmpeg tests auto-skip if absent.
- **CLI:** `mp3tochart` / `midi2chart` / `validate`, with `--sep`, `--device`, `--max-seconds`, `--quiet`, `--validate`, and per-stage progress logging.

---

## Known quality issues (non-blocking, but real)

1. **Bass bleeds into kick detection (over-busy kicks).** On bass-heavy tracks the HPSS+low-band ADT marks far too many kicks (Clay: 1690 notes, **439** flagged "2× kick"). The chart is playable but machine-gun on the kick. **Biggest single quality win:** stricter low-band gating in `charter/audio/adt.py` + more conservative 2× inference in `charter/mapping/stage6.py` (the ~150 ms gap over-fires). The user explicitly offered this as the next tuning task.
2. **Demucs is track-dependent.** Verified: on `clay.mp3`, Demucs routes percussion into `other` (RMS 0.139) and leaves `drums` near-silent (0.0002) — it's trained on acoustic kits, so electronic/programmed percussion is stripped. `--sep auto` now uses `SmartSeparator`, which detects the empty drum stem and **falls back to HPSS** (commit `cdffa25`). Caveat: on a full song, `auto` runs the slow Demucs pass *first* before falling back — for known electronic tracks tell the user to use `--sep hpss` directly.
3. **Baseline ADT = kick/snare/hi-hat only.** No toms, no ride-vs-crash, no velocity dynamics. Tested on **synthetic drums only** — real-music accuracy is unmeasured.
4. **4/4 assumed; tempo map is good but not downbeat-anchored.** Odd meters not detected.

---

## Remaining work (carried over)

**First: fix BLOCKING BUG #1 above.** Then, from [10-mvp-roadmap.md](./10-mvp-roadmap.md) Part B, in payoff order:

- [ ] **Bass-as-kick tuning** (quality issue #1 above) — highest-value, no new deps.
- [ ] **Phase 6 — RoFormer** separation (better drum stem than Demucs on real kits; doesn't help electronic tracks).
- [ ] **Phase 7 — DrumSep per-drum arbiter** → toms + ride-vs-crash (the blue-lane frontier). This is what makes charts feel non-empty.
- [ ] **Phase 8 — velocity / dynamics** (ghost/accent) — per-stem loudness now, ADT model later.
- [ ] **Phase 9 — allin1 segments** for fills / star-power / meter-disagreement flags.
- [ ] **Phase 10 — difficulty reduction** (Expert → Hard/Medium/Easy via EasyChartGenerator logic; `charter/mapping` currently emits Expert only). *Note: confirm whether CH needs lower difficulties to show the part — possibly related to BUG #1.*
- [ ] **Phase 4 — write `REVIEW.md`** (the confidence surface: low-RMS regions, inferred 2× runs, meter guess). Currently only printed to stdout.
- [ ] **ADTOF adapter** in `charter/audio/adt.py` is a stub (`NotImplementedError`) — wire the `drumTranscriptor` call for the real 5-class ADT.

---

## How to reproduce / test (for the next agent)

```bash
cd /Users/johanleche/Documents/Code/charter
python -m pytest -q                                  # 37 tests

# the failing case (electronic track; bug #1 reproduces in the user's CH):
python -m charter.cli mp3tochart mp3/clay.mp3 out/clay --sep hpss --validate
#  -> 1690 notes, scan-chart PASS, but user's CH shows "No Part"

# fast clip test on any audio:
python -m charter.cli mp3tochart <audio> out/x --max-seconds 30 --validate
```
- **Optional SOTA:** Demucs is installed in the user's env (4.0.1 — note: **`demucs.api` is absent in this build**, use `demucs.apply.apply_model` + manual normalization, see `charter/audio/separation.py`). M1 has MPS; Demucs runs on it but is slow on full songs.
- **Sandbox note:** the Bash sandbox is an ephemeral snapshot — `out/` and pip-installs there do NOT reflect the user's real terminal env. Don't rely on sandbox state persisting between commands.

## Commit trail (this session)
```
cdffa25  feat: progress logging, --max-seconds, robust Demucs path + HPSS fallback
ef4483c  fix: Moonscraper-complete .chart/song.ini   (attempted bug #1 fix — INSUFFICIENT)
d50c107  feat: audio frontend (Phase 3)
f63112b  docs: sync roadmap (Phases 1-2)
903854f  feat: symbolic backend (Phases 1-2)
e6cb205  docs: research source-of-truth
```
