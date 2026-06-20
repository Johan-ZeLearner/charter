"""Dependency-free DSP primitives (numpy + scipy only).

Everything the baseline audio frontend needs — STFT magnitude, onset envelope
(spectral flux), HPSS percussive separation, peak picking, tempo estimation, a
dynamic-programming beat tracker, and per-onset band energies — implemented
without librosa/torch so the pipeline runs offline (docs/08: the heavy SOTA
tools are optional adapters, this is the always-available floor).

Functions take ``(x: np.ndarray mono float32, sr: int)`` and frame params; they
never assume a global tempo downstream (docs/06).
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage, signal

N_FFT = 2048
HOP = 512


def frames_per_second(sr: int, hop: int = HOP) -> float:
    return sr / hop


def stft_mag(x: np.ndarray, sr: int, n_fft: int = N_FFT, hop: int = HOP):
    """Return (magnitude [freq, frames], freqs, complex STFT) using scipy."""
    f, _, Z = signal.stft(
        x,
        fs=sr,
        window="hann",
        nperseg=n_fft,
        noverlap=n_fft - hop,
        boundary="zeros",
        padded=True,
    )
    return np.abs(Z), f, Z


def onset_envelope(x: np.ndarray, sr: int, n_fft: int = N_FFT, hop: int = HOP):
    """Spectral-flux onset strength envelope and its frame rate (fps)."""
    S, _, _ = stft_mag(x, sr, n_fft, hop)
    # Log-compress to tame dynamic range, then positive first difference (flux).
    S = np.log1p(S)
    flux = np.diff(S, axis=1, prepend=S[:, :1])
    env = np.maximum(flux, 0.0).sum(axis=0)
    # Light smoothing.
    env = ndimage.uniform_filter1d(env, size=3)
    if env.max() > 0:
        env = env / env.max()
    return env.astype(np.float64), frames_per_second(sr, hop)


def hpss_percussive(x: np.ndarray, sr: int, n_fft: int = N_FFT, hop: int = HOP,
                    kernel_harm: int = 17, kernel_perc: int = 17) -> np.ndarray:
    """Median-filter Harmonic/Percussive Source Separation; return percussive signal.

    A light, dependency-free drum emphasiser (the baseline 'separation'): median
    along time captures sustained/harmonic content, along frequency captures
    transients. A soft Wiener mask isolates percussion (docs/04 fallback tier).
    """
    _, _, Z = signal.stft(
        x, fs=sr, window="hann", nperseg=n_fft, noverlap=n_fft - hop,
        boundary="zeros", padded=True,
    )
    mag = np.abs(Z)
    harm = ndimage.median_filter(mag, size=(1, kernel_harm))
    perc = ndimage.median_filter(mag, size=(kernel_perc, 1))
    eps = 1e-8
    mask = (perc**2) / (perc**2 + harm**2 + eps)
    _, xp = signal.istft(
        Z * mask, fs=sr, window="hann", nperseg=n_fft, noverlap=n_fft - hop,
    )
    return xp.astype(np.float32)


def peak_pick(env: np.ndarray, fps: float, *, delta: float = 0.06,
              pre_avg_s: float = 0.10, post_avg_s: float = 0.10,
              min_gap_s: float = 0.045) -> np.ndarray:
    """Pick onset peaks from an onset envelope. Returns frame indices.

    A frame is an onset if it is a local maximum, exceeds a moving-average
    threshold + ``delta``, and is at least ``min_gap_s`` after the previous one.
    """
    n = len(env)
    if n == 0:
        return np.array([], dtype=int)
    pre = max(1, int(round(pre_avg_s * fps)))
    post = max(1, int(round(post_avg_s * fps)))
    win = pre + post + 1
    moving = ndimage.uniform_filter1d(env, size=win, mode="nearest")
    thresh = moving + delta
    min_gap = max(1, int(round(min_gap_s * fps)))

    peaks: list[int] = []
    last = -min_gap - 1
    for i in range(1, n - 1):
        if env[i] < thresh[i]:
            continue
        if env[i] < env[i - 1] or env[i] < env[i + 1]:
            continue
        if i - last < min_gap:
            # keep the stronger of two close peaks
            if peaks and env[i] > env[peaks[-1]]:
                peaks[-1] = i
                last = i
            continue
        peaks.append(i)
        last = i
    return np.array(peaks, dtype=int)


def estimate_tempo(env: np.ndarray, fps: float, *, bpm_min: float = 60.0,
                   bpm_max: float = 200.0, prior_bpm: float = 120.0) -> float:
    """Estimate global tempo (BPM) by autocorrelation with a log-normal prior."""
    e = env - env.mean()
    ac = signal.correlate(e, e, mode="full")
    ac = ac[len(ac) // 2:]  # non-negative lags
    if ac[0] != 0:
        ac = ac / ac[0]
    lag_min = int(round(60.0 * fps / bpm_max))
    lag_max = min(len(ac) - 1, int(round(60.0 * fps / bpm_min)))
    if lag_max <= lag_min:
        return prior_bpm
    lags = np.arange(lag_min, lag_max + 1)
    bpms = 60.0 * fps / lags
    # Log-normal prior around prior_bpm to discourage octave errors.
    prior = np.exp(-0.5 * (np.log2(bpms / prior_bpm) / 0.6) ** 2)
    score = ac[lags] * prior
    return float(bpms[int(np.argmax(score))])


def dp_beat_track(env: np.ndarray, fps: float, bpm: float, *,
                  tightness: float = 100.0) -> np.ndarray:
    """Dynamic-programming beat tracker (Ellis 2007 / librosa-style).

    Returns beat frame indices. The caller derives a per-beat tempo map from the
    actual inter-beat intervals, so mild tempo drift is preserved.
    """
    n = len(env)
    if n < 2 or bpm <= 0:
        return np.array([], dtype=int)
    period = 60.0 * fps / bpm
    local = env.astype(np.float64)
    std = local.std()
    if std > 0:
        local = (local - local.mean()) / std

    offsets = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
    offsets = offsets[offsets < 0]
    if len(offsets) == 0:
        return np.array([], dtype=int)
    txcost = -tightness * (np.log(-offsets / period)) ** 2

    cumscore = np.zeros(n)
    backlink = np.full(n, -1, dtype=int)
    for i in range(n):
        cand = i + offsets
        valid = cand >= 0
        scores = np.full(offsets.shape, -np.inf)
        scores[valid] = txcost[valid] + cumscore[cand[valid]]
        best = int(np.argmax(scores))
        if np.isfinite(scores[best]):
            cumscore[i] = local[i] + scores[best]
            backlink[i] = cand[best]
        else:
            cumscore[i] = local[i]
            backlink[i] = -1

    # Backtrace from the strongest cumulative score.
    beats: list[int] = []
    i = int(np.argmax(cumscore))
    while i >= 0:
        beats.append(i)
        i = backlink[i]
    beats.reverse()
    return np.array(beats, dtype=int)


def refine_beat_frames(env: np.ndarray, frames: np.ndarray) -> np.ndarray:
    """Sub-frame beat positions via parabolic interpolation of the onset envelope.

    Integer beat frames have ~one-hop (~11 ms) quantization noise, which makes a
    constant-tempo song look like it oscillates ±1-2 BPM. Nudging each beat that
    sits on a local envelope peak to the interpolated peak removes most of that
    jitter; beats not on a peak keep their integer position.
    """
    out: list[float] = []
    for f in frames:
        f = int(f)
        if 1 <= f < len(env) - 1:
            a, b, c = env[f - 1], env[f], env[f + 1]
            denom = a - 2 * b + c
            if denom < 0:  # concave => local maximum
                delta = 0.5 * (a - c) / denom
                if -0.5 <= delta <= 0.5:
                    out.append(f + delta)
                    continue
        out.append(float(f))
    return np.array(out, dtype=float)


def band_energy(spectrum: np.ndarray, freqs: np.ndarray,
                lo: float, hi: float) -> float:
    """Summed magnitude energy in [lo, hi) Hz for a single-frame spectrum."""
    sel = (freqs >= lo) & (freqs < hi)
    if not sel.any():
        return 0.0
    return float(np.sqrt((spectrum[sel] ** 2).sum()))
