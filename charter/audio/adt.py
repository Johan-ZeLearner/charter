"""Stage 4: automatic drum transcription (docs/05).

Baseline = onset detection + multi-label band-energy classification into the
near-solved 3-class backbone (kick / snare / hi-hat). Toms and ride-vs-crash are
NOT attempted by the baseline (that is the hard frontier the DrumSep arbiter and
ADTOF/STRUM target — Phase 7). Optional SOTA adapter = ADTOF (used if installed).

Output is GM-drum onsets with velocity, consumed by quantize -> Stage-6 mapping.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass

import numpy as np

from . import dsp
from .interfaces import AudioBuffer, DrumOnset, DrumTranscriber

# GM percussion notes for the 3-class backbone (map cleanly in Stage 6).
GM_KICK = 36
GM_SNARE = 38
GM_CLOSED_HAT = 42


@dataclass
class BaselineConfig:
    """Tunable band-energy thresholds (validated on synthetic drums)."""

    kick_low_ratio: float = 0.28  # E(20-150Hz) / total -> kick
    hat_vhigh_ratio: float = 0.45  # E(8kHz-Nyq) / total -> hi-hat
    hat_mid_max: float = 0.30  # ...but only if mid isn't dominant (else snare)
    snare_mid_ratio: float = 0.18  # E(250-3000Hz) / total -> snare
    low_hi: float = 150.0
    mid_lo: float = 250.0
    mid_hi: float = 3000.0
    vhigh_lo: float = 8000.0


class BaselineDrumTranscriber(DrumTranscriber):
    name = "baseline-bandenergy"

    def __init__(self, config: BaselineConfig | None = None):
        self.cfg = config or BaselineConfig()

    def transcribe(self, audio: AudioBuffer) -> list[DrumOnset]:
        x, sr = audio.samples, audio.sr
        env, fps = dsp.onset_envelope(x, sr)
        onset_frames = dsp.peak_pick(env, fps)
        if len(onset_frames) == 0:
            return []
        S, freqs, _ = dsp.stft_mag(x, sr)
        peak_env = max(env[onset_frames].max(), 1e-9)

        out: list[DrumOnset] = []
        for fi in onset_frames:
            spec = S[:, min(fi, S.shape[1] - 1)]
            labels = self._classify(spec, freqs, sr)
            vel = int(np.clip(30 + 97 * (env[fi] / peak_env), 1, 127))
            time_s = fi / fps
            for gm in labels:
                out.append(DrumOnset(time_s=time_s, gm_note=gm, velocity=vel,
                                     confidence=float(env[fi] / peak_env)))
        return out

    def _classify(self, spec: np.ndarray, freqs: np.ndarray, sr: int) -> list[int]:
        c = self.cfg
        total = dsp.band_energy(spec, freqs, 20, sr / 2) + 1e-9
        low = dsp.band_energy(spec, freqs, 20, c.low_hi) / total
        mid = dsp.band_energy(spec, freqs, c.mid_lo, c.mid_hi) / total
        vhigh = dsp.band_energy(spec, freqs, c.vhigh_lo, sr / 2) / total

        labels: list[int] = []
        if low > c.kick_low_ratio:
            labels.append(GM_KICK)
        if mid > c.snare_mid_ratio and low <= c.kick_low_ratio:
            labels.append(GM_SNARE)
        if vhigh > c.hat_vhigh_ratio and mid < c.hat_mid_max:
            labels.append(GM_CLOSED_HAT)
        if not labels:
            # fall back to the single dominant band
            dominant = max((low, GM_KICK), (mid, GM_SNARE), (vhigh, GM_CLOSED_HAT))
            labels.append(dominant[1])
        return labels


class ADTOFTranscriber(DrumTranscriber):  # pragma: no cover
    """ADTOF 5-class CRNN (~0.85-0.89 F) — optional, used if installed (docs/05)."""

    name = "adtof"

    def transcribe(self, audio: AudioBuffer) -> list[DrumOnset]:
        raise NotImplementedError(
            "ADTOF adapter not wired yet — install adtof and implement the "
            "drumTranscriptor call here (returns GM-mapped onsets)."
        )


def adtof_available() -> bool:
    return importlib.util.find_spec("adtof") is not None


def choose_transcriber(prefer: str = "auto") -> DrumTranscriber:
    # ADTOF is left unwired for now (heavy TF dependency); default to baseline.
    return BaselineDrumTranscriber()
