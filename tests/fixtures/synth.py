"""Synthesize deterministic drum audio for the audio-frontend tests.

Renders simple kick/snare/hi-hat one-shots at known beat times so the DSP
(onset detection, tempo, classification) can be checked without any model
downloads or real recordings. Returns the mono signal plus ground-truth hits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SynthTruth:
    samples: np.ndarray  # mono float32
    sr: int
    bpm: float
    beats_per_bar: int
    hits: list[tuple[float, str]]  # (time_s, label in {kick,snare,hat})


def _env(n: int, tau_s: float, sr: int) -> np.ndarray:
    t = np.arange(n) / sr
    return np.exp(-t / tau_s)


def _kick(sr: int) -> np.ndarray:
    n = int(0.22 * sr)
    t = np.arange(n) / sr
    # pitch drops from ~110 to ~45 Hz
    freq = 45 + 65 * np.exp(-t / 0.03)
    phase = 2 * np.pi * np.cumsum(freq) / sr
    return (np.sin(phase) * _env(n, 0.09, sr)).astype(np.float32)


def _snare(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.16 * sr)
    noise = rng.standard_normal(n)
    tone = np.sin(2 * np.pi * 185 * np.arange(n) / sr)
    sig = (0.8 * noise + 0.5 * tone) * _env(n, 0.05, sr)
    return sig.astype(np.float32)


def _hat(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.06 * sr)
    noise = rng.standard_normal(n)
    # crude high-pass: emphasise fast differences
    hp = np.diff(noise, prepend=noise[:1])
    return (hp * _env(n, 0.02, sr) * 0.7).astype(np.float32)


def synth_drum_track(sr: int = 44100, bpm: float = 120.0, bars: int = 2,
                     beats_per_bar: int = 4, seed: int = 0) -> SynthTruth:
    """Kick on beats 1&3, snare on 2&4, closed hat on every 8th."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    total_beats = bars * beats_per_bar
    length = int((total_beats * beat + 0.5) * sr)
    buf = np.zeros(length, dtype=np.float32)
    hits: list[tuple[float, str]] = []

    def place(sig: np.ndarray, t: float, gain: float = 1.0) -> None:
        i = int(round(t * sr))
        end = min(length, i + len(sig))
        buf[i:end] += gain * sig[: end - i]

    kick = _kick(sr)
    for b in range(total_beats):
        t = b * beat
        in_bar = b % beats_per_bar
        if in_bar in (0, 2):
            place(kick, t, 1.0)
            hits.append((t, "kick"))
        if in_bar in (1, 3):
            place(_snare(sr, rng), t, 0.9)
            hits.append((t, "snare"))
        # hats on the beat and the off-beat 8th
        place(_hat(sr, rng), t, 0.5)
        hits.append((t, "hat"))
        place(_hat(sr, rng), t + beat / 2, 0.4)
        hits.append((t + beat / 2, "hat"))

    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * 0.9
    hits.sort()
    return SynthTruth(samples=buf, sr=sr, bpm=bpm, beats_per_bar=beats_per_bar, hits=hits)
