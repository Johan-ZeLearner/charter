"""Tunable settings, genre presets, and settings -> pipeline-config translation.

The studio exposes the baseline ADT knobs (``charter.audio.adt.BaselineConfig``)
plus the mapping policy (``charter.mapping.MapConfig``), the separator choice,
and the quantization grid. A "genre preset" is just a named bundle of sane
starting points for a kind of music — the user fine-tunes from there.

Every value here is a *starting point*, not a claim of correctness. The whole
point of the studio is that the baseline can't be tuned blind; it can be tuned
fast with a preview.
"""

from __future__ import annotations

from typing import Any

from ..audio.adt import BaselineConfig
from ..audio.drumsep import DrumSepConfig, drumsep_available
from ..audio.separation import (
    PassthroughSeparator,
    PercussiveSeparator,
    Separator,
    choose_separator,
)
from ..mapping import MapConfig

# The full knob set the UI drives. Defaults reproduce the current baseline.
DEFAULTS: dict[str, Any] = {
    "engine": "baseline",        # baseline | drumsep (per-drum-stem, quality)
    "separation": "hpss",        # hpss | passthrough | demucs | auto (baseline engine)
    "onset_delta": 0.06,         # peak-pick threshold (higher = fewer onsets)
    "onset_min_gap_s": 0.045,    # min spacing between onsets (higher = fewer)
    "kick_low_ratio": 0.28,      # low-band fraction -> kick (raise to reject bass)
    "snare_mid_ratio": 0.18,     # mid-band fraction -> snare
    "hat_vhigh_ratio": 0.45,     # very-high-band fraction -> hi-hat (lower to find hats)
    "hat_mid_max": 0.30,         # hat only if mid below this
    "tom_split": True,           # drumsep: split toms blue/green by pitch
    "subdivisions": 4,           # grid: 2=8th, 4=16th, 8=32nd, 3/6=triplets
    "tempo_mult": 1.0,           # ×0.5 / ×1 / ×2 — fix half/double-time tracking
    "kick_gap_s": 0.030,         # drumsep kick onset min gap (LOWER = faster double bass)
    "snare_gate": 0.13,          # drumsep snare onset threshold (HIGHER = less snare)
    "dynamics": False,           # emit ghost/accent modifiers
    "double_kick": False,        # infer 2x kick from close kicks
    "double_kick_gap_s": 0.140,  # gap under which a kick is marked 2x
    "device": None,              # demucs/drumsep device override (mps/cuda/cpu)
}

# Named starting points. Only the keys that differ from DEFAULTS are listed.
PRESETS: dict[str, dict[str, Any]] = {
    "Default": {},
    "Electronic": {
        # Demucs strips programmed percussion -> HPSS. Bass dominates the low
        # band, so raise the kick bar and thin out onsets; find the hats.
        "separation": "hpss",
        "kick_low_ratio": 0.42,
        "hat_vhigh_ratio": 0.22,
        "onset_delta": 0.12,
        "onset_min_gap_s": 0.070,
        "dynamics": False,
        "double_kick": False,
    },
    "Rock": {
        "separation": "auto",
        "kick_low_ratio": 0.30,
        "hat_vhigh_ratio": 0.30,
        "onset_delta": 0.07,
        "dynamics": True,
        "double_kick": False,
    },
    "Metal": {
        # Tuned for fast melodic death metal: fine kick gap for sustained double
        # bass, less snare, a 1/32 grid so fast kicks don't merge, 2x kick on.
        # If the BPM readout is HALF the real tempo, bump Tempo to ×2.
        "separation": "auto",
        "kick_low_ratio": 0.26,
        "hat_vhigh_ratio": 0.32,
        "onset_delta": 0.05,
        "onset_min_gap_s": 0.030,
        "subdivisions": 8,            # 1/32 — resolve fast double bass
        "kick_gap_s": 0.026,          # very fine — catch every double-bass hit
        "snare_gate": 0.16,           # curb snare over-detection
        "dynamics": True,
        "double_kick": True,
        "double_kick_gap_s": 0.110,
    },
    "Pop": {
        "separation": "auto",
        "kick_low_ratio": 0.30,
        "hat_vhigh_ratio": 0.28,
        "onset_delta": 0.08,
        "dynamics": True,
        "double_kick": False,
    },
    "Acoustic / Jazz": {
        "separation": "auto",
        "kick_low_ratio": 0.30,
        "hat_vhigh_ratio": 0.24,
        "snare_mid_ratio": 0.16,
        "onset_delta": 0.05,
        "subdivisions": 3,
        "dynamics": True,
        "double_kick": False,
    },
}


def resolve_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Merge DEFAULTS <- preset(genre) <- explicit overrides, coercing types."""
    raw = dict(raw or {})
    out = dict(DEFAULTS)
    genre = raw.pop("genre", None)
    if genre and genre in PRESETS:
        out.update(PRESETS[genre])
    for k, v in raw.items():
        if k in out:
            out[k] = v
    # Type coercion (JSON gives us strings/floats/bools loosely).
    out["subdivisions"] = max(1, int(out["subdivisions"]))
    out["dynamics"] = bool(out["dynamics"])
    out["double_kick"] = bool(out["double_kick"])
    out["tom_split"] = bool(out["tom_split"])
    for f in ("onset_delta", "onset_min_gap_s", "kick_low_ratio", "snare_mid_ratio",
              "hat_vhigh_ratio", "hat_mid_max", "double_kick_gap_s",
              "tempo_mult", "kick_gap_s", "snare_gate"):
        out[f] = float(out[f])
    out["tempo_mult"] = max(0.25, min(4.0, out["tempo_mult"]))
    if out["engine"] not in ("baseline", "drumsep"):
        out["engine"] = "baseline"
    out["_genre"] = genre or "Default"
    out["_drumsep_available"] = drumsep_available()
    return out


def _make_separator(name: str, device: str | None) -> Separator:
    if name == "hpss":
        return PercussiveSeparator()
    if name == "passthrough":
        return PassthroughSeparator()
    # "demucs" / "auto" -> reuse the smart chooser (HPSS fallback if absent).
    return choose_separator(prefer=name, device=device)


def build_map_config(settings: dict[str, Any]) -> MapConfig:
    """MapConfig from settings (dynamics + 2x-kick gating), shared by both engines."""
    s = settings
    mc = MapConfig()
    if not s["dynamics"]:
        # Push the gates out of range so every hit stays NORMAL (no ghost/accent).
        mc.ghost_max_velocity = 0
        mc.accent_min_velocity = 128
    mc.double_kick_gap_seconds = s["double_kick_gap_s"] if s["double_kick"] else 0.0
    return mc


def build_engine(settings: dict[str, Any]):
    """Translate settings into (separator, transcriber, MapConfig, subdivisions).

    ``drumsep`` engine does its own separation from the raw mix, so it pairs with
    a passthrough separator; it falls back to the baseline (with a name change the
    diagnostics surface) if the weights/demucs aren't installed.
    """
    s = settings
    mc = build_map_config(settings)
    subdiv = int(s["subdivisions"])

    if s["engine"] == "drumsep" and drumsep_available():
        from ..audio.drumsep import DrumSepConfig, DrumSepTranscriber

        dcfg = DrumSepConfig(
            onset_delta=s["onset_delta"],
            onset_min_gap_s=s["onset_min_gap_s"],
            kick_min_gap_s=s["kick_gap_s"],
            snare_delta=s["snare_gate"],
            tom_split=s["tom_split"],
            device=s.get("device"),
        )
        try:
            return PassthroughSeparator(), DrumSepTranscriber(dcfg), mc, subdiv
        except Exception:  # weights vanished mid-session -> fall through to baseline
            pass

    from ..audio.adt import BaselineDrumTranscriber

    bc = BaselineConfig(
        kick_low_ratio=s["kick_low_ratio"],
        snare_mid_ratio=s["snare_mid_ratio"],
        hat_vhigh_ratio=s["hat_vhigh_ratio"],
        hat_mid_max=s["hat_mid_max"],
        onset_delta=s["onset_delta"],
        onset_min_gap_s=s["onset_min_gap_s"],
    )
    sep = _make_separator(s["separation"], s.get("device"))
    return sep, BaselineDrumTranscriber(bc), mc, subdiv
