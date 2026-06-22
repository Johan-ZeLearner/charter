# Beat / Pace Detection — Handoff

> **Status:** Open frontier · **Created:** 2026-06-22 · **Audience:** the next agent picking up beat/tempo detection
> **Purpose:** Automatic beat/pace detection is **bad on real music** (dense/distorted melodic death metal, fast double-bass/blast beats, tempo changes). The human-correction studio is built and solid; the *detector under it* is the problem. This is the plan to fix it on **both** fronts — the automation, and the human+automation loop. Read [HANDOFF.md](./HANDOFF.md) for the studio context first.
>
> Grounded in a research + codebase-fit pass (SOTA beat tracking that fits this env, octave-error mitigation, interactive/anchor beat tracking). Line refs were read against the committed code (`7043d55`); prefer the **function names** (stable) over exact line numbers.

---

## TL;DR

- **The single highest-leverage first move (P0, ~½ day):** kill the 120-BPM prior in `estimate_tempo` and replace it with a **hybrid tempogram (DFT × ACF product)**, raise `bpm_max` to ~300. This removes the structural cause of the half-time errors and unblocks honest A/B testing. Pure numpy/scipy, no new deps, one function, unchanged signature.
- **The SOTA automation answer (P0, ~1–1.5 days):** wire **Beat This!** (CPJKU, ISMIR 2024, MIT, PyTorch/MPS — *no madmom/TF/librosa*) behind the existing `BeatTracker` interface. It has no 120-BPM prior, follows drift natively (no global-tempo DBN), and emits real downbeats. Its 22.05 kHz / 50 fps matches our `ANALYSIS_SR`.
- **The human-loop answer (P0, ~1 day):** **anchor-constrained DP** — make a tap/edit a *hard pin*, not a soft prior. Today the only authoritative mode is full metronomic `LOCK`; there's no middle ground where "the tap fixes the rate, the model places phase and follows drift."
- **`madmom` is the recurring blocker.** It pins old numpy/Python and isn't installable here, which **disqualifies** BeatNet, allin1, Beat-Transformer-as-published, and BEAST. Every recommendation below either avoids madmom or names the exact surgery.

---

## 🔴 The honest diagnosis — why it's bad (all confirmed in code)

1. **The 120-BPM log-normal prior IS the half-time bug.** `dsp.estimate_tempo` scores the autocorrelation peak by `prior = exp(-0.5*(log2(bpms/120)/0.6)**2)` and caps at `bpm_max=200`. Fast metal (~180–280 BPM) is either penalized ~1 octave down or above the ceiling entirely → the detector lands on **half-time**. `analyze_song` only escapes via a user `tempo_hint`; `analyze_window` hard-codes `prior_bpm=120` and uses the hint only as the DP's `bpm0`, never as a real prior.
2. **Autocorrelation alone can't resolve octaves.** The ACF reinforces a tempo *and* its subharmonics (T, T/2, T/3); on a blast beat the half-time backbeat peaks as strongly as the true rate. There's no harmonic cross-check, so even without the prior the ACF is ambiguous on dense material.
3. **The DP tracker takes ONE scalar BPM and cannot follow drift.** `dsp.dp_beat_track` builds a single `period = 60*fps/bpm` and a fixed transition cost around it. Accelerando/ritardando, or a fast section under a half-time global estimate, gets pinned to the wrong period for the whole pass. `refine_beat_frames` only does parabolic sub-frame nudging — it does not follow drift.
4. **The onset signal is wrong for distorted metal.** `dsp.onset_envelope` is summed positive spectral flux over the **full mix**; a wall of distorted guitar + continuous double-bass makes nearly every frame an onset, so "beat-ness" is flat and noisy. We **already produce a Demucs drum stem** (`out/clay_drumsep/` exists) and never use it for tracking.
5. **A correct TAP genuinely can't win in detect mode.** The tap → `tempo_hint` → only the DP period prior, which the onset-driven DP overrides. The only authoritative path is `_locked_grid` (a rigid metronome, detection fully bypassed). There is **no middle ground** (tap fixes rate, model places phase + follows drift), and **no beat-level editing** anywhere — the studio only drags *section* boundaries.
6. **Downbeats are a max-energy heuristic.** `_downbeat_phase` picks the bar phase with the most summed onset energy and assumes 4/4 — on blast beats every phase looks equally hot, so downbeats are near-random.

---

## ✅ What's already built (do NOT rebuild) + the contract to preserve

The studio is the human layer; the detector plugs *under* it. Already shipped (see [HANDOFF.md](./HANDOFF.md)):
- **Per-section re-track** — `analyze_window(start,end,…)` re-tracks one region; beats in absolute song time, spliced into the global grid (`composeGrid`). Route `GET /api/analyze_region`.
- **Tap-tempo seeding** (`T`) — median tap interval → `tempo_hint`; first tap → beat-1 anchor.
- **LOCK mode** — `_locked_grid()` builds a metronomic grid from the tapped BPM, detection bypassed.
- **Section split / merge / rename** — right-click context menu on the timeline band; drag a boundary to move it (beat-snapped). Boundary-as-shared-handle model keeps `base.sections` gapless.
- Tempo-curve strip, waveform, section auto-labeling, `resample_grid` (×½/×2 octave fix).

**Data contract any replacement MUST preserve** (or the studio frontend breaks):
- `BeatGrid` (`charter/audio/interfaces.py`): `beat_times` (float64 s, quarter-notes), `downbeat_times` (subset), `bpm` (report only), `beats_per_bar`.
- `analyze_song` / `analyze_window` return a JSON dict the frontend consumes: `{duration, bpm, beatsPerBar, phase, tempoMult, beats[], downbeats[], tempoCurve[{t,bpm}], sections[], waveform[], locked, analysis{…}}`. Keep beats **sorted, in absolute song time, half-open `[start,end)`** for `analyze_window`.

---

## 🔌 Swap points (where to plug in — by function, not line)

| Where | File · function | What to do |
|---|---|---|
| Tempo estimator | `audio/dsp.py · estimate_tempo` | Replace ACF+120-prior with hybrid tempogram; add `estimate_tempo_curve()` (per-frame BPM). Keep signature `(env, fps, *, bpm_min, bpm_max=300, prior_bpm)` so callers are untouched; demote `prior_bpm` to a soft tiebreaker. |
| Beat tracker | `audio/dsp.py · dp_beat_track` | Accept `period` as scalar **or** per-frame array (drift); accept **hard anchor frames** (anchored DP). |
| Drift/quantize | `audio/dsp.py · refine_beat_frames`, `audio/quantize.py · build_tempo_map` | Piecewise-linear tempo map; adaptive `coalesce_bpm`. |
| Tracker selection | `studio/analyze.py · analyze_song` / `analyze_window` | **Call the `BeatTracker` interface** (`choose_beat_tracker().track(buf)`) instead of dsp functions directly — today they bypass it. Map `BeatGrid → payload`. Keep numpy as the always-available floor. |
| Beat-level edits | `studio/analyze.py · analyze_window` | Accept `[(beat_idx, new_time), …]` pinned beats (hard anchors). New query param on `/api/analyze_region`. |
| Downbeats | `studio/analyze.py · _downbeat_phase` | Use Beat This! downbeat head when active; for the floor, try bar lengths {3,4,5,7} + confidence. |
| Adapter | `audio/beats.py · BeatThisTracker` | **Broken + unreachable today:** it calls `File2Beats` (file-path-only) but is handed an `AudioBuffer.samples` array, and nothing reaches it because `analyze.py` bypasses the interface. Fix to use `Audio2Beats`, pass `device='mps'`. |

---

## 🤖 Automation roadmap

**P0 — Hybrid tempogram (DFT × ACF product), drop the 120 prior, `bpm_max≈300`.** *(½ day incl. fixtures)*
The DFT tempogram (`scipy.signal.stft` of the onset envelope, ~6–8 s window) emphasizes *harmonics* (T, 2T, 3T); the existing ACF emphasizes *subharmonics* (T, T/2, T/3). Map both to a shared BPM grid `[60,300]`, normalize, take the **elementwise product**, argmax — the true fundamental is the only BPM present in both, so half-time (ACF) and double-time (DFT) peaks cancel. No genre bias, ~30 lines, no new deps. Also add `estimate_tempo_curve()` for P0-drift.

**P0 — Drift-aware DP.** *(½ day)*
Generalize `dp_beat_track` to a per-frame `period[i]` array (broadcast a scalar for back-compat). Recompute the transition cost per frame centered on `period[i]`. One pass then follows accelerando/ritardando without per-section re-tracking. Thread the tempo curve through `analyze_song`/`analyze_window`.

**P0 — Wire Beat This! as a real `BeatTracker`.** *(1–1.5 days)*
`pip install beat-this soxr rotary-embedding-torch` (einops present; torch≥2.0 + MPS present). Fix `BeatThisTracker` to use array-accepting `Audio2Beats`, `device='mps'`, set `PYTORCH_ENABLE_MPS_FALLBACK=1`. Refactor `analyze_*` to call `choose_beat_tracker().track()`; keep numpy as the floor when `beat_this` is absent. A/B against the hybrid-tempogram path on `mp3/venator.mp3` + `mp3/clay.mp3`.

**P1 — Track on the Demucs drum stem, not the full mix.** *(~1 day)*
Run the chosen tracker on the isolated drum stem (reuse existing Demucs; cache next to the song). Captures most of the "demixed" benefit (the Beat-Transformer idea) for near-zero new code. Compare full-mix vs stem; if stem wins, default to it for metal.

**P1 — Cache Beat This! 50-fps activation curves once per song; peak-pick separately.** *(~1 day)*
Persist per-frame beat+downbeat logits (`.npz` next to the song). Reimplement the minimal postprocessor in numpy (sigmoid → threshold → peak-pick → min-IBI dedup, reuse `refine_beat_frames`). This is the **shared substrate the human loop steers** and makes section re-tracking instant (today `server.py` re-decodes + re-detects every call).

**P2 — Disagreement flagging** (hybrid-tempogram vs Beat This! differ >~15% or ~2× → "review here" markers + a confidence ribbon). **P2 — Multi-hypothesis / odd-meter downbeats** (Beat This! head when active; bar lengths {3,4,5,7} + confidence for the floor).

---

## 🧑‍🤝‍🤖 Human + automation roadmap

**P0 — Anchor-constrained DP: a tap/edit is a HARD pin, not a soft prior.** *(~1 day; you own the DP)*
Extend `dp_beat_track` to force the path through anchored instants (clamp the local score / restrict the backtrace), run forward+backward from each anchor and merge, and set the inter-anchor target period from the **actual anchor spacing** (not the 120 prior). Add a "hard tap" mode between soft-hint and full `LOCK`: the tap clamps the period band (rate wins) while onsets only choose phase/drift. Pass anchors via a new `/api/analyze_region` param. **This directly fixes the #1 complaint** ("a correct tap still doesn't win").

**P0 — Per-beat editing: move / insert / delete a beat, snapping to the activation peak.** *(~2 days)*
There is no beat-level editing today (only section boundaries). Render beats as draggable markers (reuse the boundary-drag affordance in `app.js`); on drag, snap to the nearest activation/onset peak (sub-frame via `refine_beat_frames`). Store edits as **hard anchors** in the region override (the `regions` Map already keys by `secKey`); persist so re-track never regresses them.

**P1 — User tempo MIN/MAX band the picker/DP physically cannot violate.** *(~1 day)*
Draw a 180-BPM floor on a known-fast section → the tracker can never collapse to 90. Clamp the hybrid-tempogram argmax + DP period band + peak-picker min/max IBI. Survives re-tracking (mirrors Yamamoto 2021's Tempo-Range editor).

**P1 — Warp-marker grid interpolation (linear-BPM ramp between two anchors).** *(~1–1.5 days, mostly UI)*
The proven DAW UX for accelerando/ritardando: anchor the start+end of a tempo change, ramp BPM linearly between, everything outside stays solid. You only need the *grid* half of warping (you're charting, not time-stretching). Pure numpy on `beat_times`, re-interpolate only the two adjacent spans.

**P2 — Tap-along the whole song + TapCorrect-style snap** ("clean up my taps": capture the full tap train — frontend already captures taps but reduces to one median BPM — cross-correlate to find the global offset, then per-tap local-argmax onto the nearest peak; reimplement in numpy to avoid TapCorrect's LGPL).
**P2 — Per-song fine-tune of Beat This!** on a small user-corrected region (freeze most layers, few low-LR Adam steps on the head on MPS, re-infer; keep user edits as immutable constraints + always undo). Evidence (Pinto/Davies) shows 2–5× F-measure gains on OOD rhythms — metal is OOD. Do only after the constrained-DP + activation-cache layers land.

---

## 🧰 Candidate tools (env-aware)

**Use / build:**
- **Beat This!** — `github.com/CPJKU/beat_this` · **MIT** (code + weights). SOTA transformer beat+downbeat, no DBN/no-120-prior, follows drift, real downbeats, 22.05 kHz/50 fps. Deps: `beat-this soxr rotary-embedding-torch einops` (madmom only for the optional `--dbn`). **Primary automation pick.**
- **Hybrid tempogram (DFT×ACF)** — algorithm, pure numpy/scipy. Octave self-correction. **Ship first.**
- **PLP / localized tempogram** (Grosche & Müller; reimplement, ISC algorithm) — ML-free per-frame local tempo that follows drift; the upgraded always-available floor + cross-check.
- **Anchored Ellis DP** (you already have the DP) — makes a tap a hard pin. Lowest-effort authoritative fix.
- **Warp/stretch-marker UX** (Ableton/Reaper) — interaction pattern, not a dep.
- **TapCorrect** concept (Driedger 2019; reimplement to avoid LGPL) — snap a continuous tap-along to true beats.

**Disqualified here (mostly `madmom`):**
- **BeatNet** (madmom hard-dep even online), **allin1** (madmom + NATTEN/Apple-Silicon pain), **Beat-Transformer as-published** (Spleeter/TF demix + madmom postproc — but the *demix-then-track* idea is reachable via Beat This! on the Demucs drum stem), **BEAST** (online-only, pins torch 1.12 + madmom, weak downbeat F1, unclear license). **TempoCNN** is a useful tempo *oracle* but ships TF weights — port the tiny arch to torch or skip.

---

## 🧪 Experiments to validate direction (cheap, do first)
1. **A/B tempo on the two real clips** (`mp3/clay.mp3`, `mp3/venator.mp3`): current `estimate_tempo` vs hybrid tempogram vs Beat This! — print global BPM + tempo curve. **Pass/fail:** does the metal clip report ~180–280, not ~90–140? Validates the P0 prior fix in an hour.
2. **Full mix vs Demucs drum stem** (`out/clay_drumsep/`) for the same clip — compare by ear (sonified clicks) + curve stability. Decides whether stem-tracking is the metal default.
3. **MPS smoke test** for Beat This!: time `Audio2Beats` on a 4-min song `mps` vs `cpu`, watch for unsupported-op warnings (`PYTORCH_ENABLE_MPS_FALLBACK=1`). De-risks the env before full integration.
4. **Fast-metal fixtures + regression gate:** extend `tests/fixtures/synth.py` (180/220/260 BPM with double-bass 16ths + one 200→170→200 ramp); tighten `tests/test_audio_dsp.py` from ±6 BPM to explicit **octave assertions** (must not return ~half/double).
5. **Tiny ground-truth eval:** hand-correct downbeats for one full metal song in the studio, save as reference, report beat/downbeat **F-measure** (reimplement mir_eval's F1 in numpy) per detector variant so "better" is measured, not felt.
6. **Octave cross-check plot:** ACF-only argmax vs DFT-only vs product — visually confirm the product cancels half/double peaks before committing.

---

## ❓ Open questions for the user (decide before/while building)
- **Add `beat-this` + `soxr` + `rotary-embedding-torch` to the `.venv`, or keep the numpy floor as the only *shipped* path with Beat This! opt-in?** (Decides whether the Beat This! integration or the hybrid tempogram is the true primary.)
- **Default to the Demucs drum stem (slower startup: separation first) or the full mix (faster, worse on metal)?**
- **Beat This! checkpoint:** `small` (8.1 MB) vs `final` (78 MB) — accuracy-on-metal vs load/inference cost on M1; studio default vs CLI default.
- **Persistence:** beat-level edits + tempo bands in the in-memory `regions` Map only (lost on reload) or a per-song sidecar so a charting session survives a restart? (The studio has no project-save concept yet.)
- **Odd meters:** auto-detect {3,5,7} (unreliable on blast beats) or require explicit `beats_per_bar` per section (honest default)?
- **Activation cache key** = `(song path + SR + checkpoint)`; needs an invalidation story if the checkpoint changes or source audio is edited.

---

## ⚙️ Environment reality + reproduce the badness
- **Confirm the real `.venv`** before pinning anything: the sandbox showed **torch 2.10.0 + MPS** (the prior handoff claimed 2.12 in the user's env — both are fine for Beat This!, which needs ≥2.0). `einops` present; `beat_this`, `soxr`, `rotary_embedding_torch` **not** installed in the sandbox. `demucs 4.0.1` present. **No tensorflow/librosa/madmom/adtof.** Sandbox `out/` and pip state do **not** necessarily match the user's terminal — verify there.
- **Reproduce:** `python -m charter.studio mp3/clay.mp3` (or `mp3/venator.mp3`) → play with the metronome on, watch the click drift / the BPM read half. The studio is the eval harness; the human tools (tap/lock/split-merge) are how you'll sanity-check any new detector by ear.
- **Smallest loop:** unit-test `estimate_tempo`/`dp_beat_track` against new fast-metal fixtures (no ffmpeg needed for synth), then validate by ear in the studio on the real clips.
