"""Song-structure (section/segment) detection — numpy/scipy only.

A light, dependency-free segmenter: log-band spectral features, a future-vs-past
novelty curve (a section boundary is where the sound *changes*), peak-picked into
boundaries, snapped to downbeats, then sections are lettered (A/B/A/C…) by
clustering their mean feature so repeats (verse/chorus) share a label.

This is a baseline to be judged and corrected in the studio, not ground truth —
the whole point is the user can see and fix it.
"""

from __future__ import annotations

import numpy as np

from ..audio import dsp


def _band_features(samples: np.ndarray, sr: int, n_bands: int = 24, fps_out: float = 4.0):
    """Log-band-energy features at ~``fps_out`` frames/sec. Returns (feat[T, n_bands], t[T])."""
    S, freqs, _ = dsp.stft_mag(samples, sr)
    nyq = sr / 2
    edges = np.logspace(np.log10(40), np.log10(nyq), n_bands + 1)
    rows = []
    for i in range(n_bands):
        sel = (freqs >= edges[i]) & (freqs < edges[i + 1])
        rows.append(S[sel].sum(axis=0) if sel.any() else np.zeros(S.shape[1]))
    band = np.log1p(np.asarray(rows))                       # [n_bands, frames]
    fps = dsp.frames_per_second(sr)
    hop = max(1, int(round(fps / fps_out)))
    # average within each output frame for stability
    n_out = band.shape[1] // hop
    if n_out < 2:
        return band.T, np.array([0.0])
    band = band[:, : n_out * hop].reshape(band.shape[0], n_out, hop).mean(axis=2)
    feat = band.T                                           # [T, n_bands]
    feat = feat / (np.linalg.norm(feat, axis=1, keepdims=True) + 1e-9)
    t = (np.arange(n_out) * hop + hop / 2) / fps
    return feat, t


def _novelty(feat: np.ndarray, win: int) -> np.ndarray:
    """Future-vs-past contrast novelty: how different the next ``win`` frames are
    from the previous ``win``. Peaks mark section boundaries."""
    T = feat.shape[0]
    nov = np.zeros(T)
    for i in range(T):
        a, b = max(0, i - win), min(T, i + win)
        if i - a < 2 or b - i < 2:
            continue
        past = feat[a:i].mean(axis=0)
        future = feat[i:b].mean(axis=0)
        nov[i] = np.linalg.norm(future - past)
    if nov.max() > 0:
        nov = nov / nov.max()
    return nov


def _pick_boundaries(nov: np.ndarray, min_gap: int, thresh: float = 0.30) -> list[int]:
    out: list[int] = []
    last = -min_gap
    for i in range(1, len(nov) - 1):
        if nov[i] < thresh or nov[i] < nov[i - 1] or nov[i] <= nov[i + 1]:
            continue
        if i - last < min_gap:
            if out and nov[i] > nov[out[-1]]:
                out[-1] = i
                last = i
            continue
        out.append(i)
        last = i
    return out


def _label(feat: np.ndarray, spans: list[tuple[int, int]], sim_thresh: float = 0.90) -> list[str]:
    """Letter sections by clustering mean features so repeats share a letter."""
    means = [feat[a:b].mean(axis=0) for a, b in spans]
    means = [m / (np.linalg.norm(m) + 1e-9) for m in means]
    labels: list[str] = []
    protos: list[np.ndarray] = []
    for m in means:
        best, bj = -1.0, -1
        for j, p in enumerate(protos):
            s = float(m @ p)
            if s > best:
                best, bj = s, j
        if best >= sim_thresh:
            labels.append(chr(ord("A") + bj))
        else:
            protos.append(m)
            labels.append(chr(ord("A") + len(protos) - 1))
    return labels


def detect_sections(
    samples: np.ndarray,
    sr: int,
    downbeat_times: np.ndarray,
    *,
    min_section_s: float = 8.0,
) -> list[dict]:
    """Return [{start, end, label, energy}] over the whole signal."""
    duration = len(samples) / sr
    feat, t = _band_features(samples, sr)
    if len(t) < 4:
        return [{"start": 0.0, "end": round(duration, 3), "label": "A", "energy": 1.0}]
    fps_out = 1.0 / (t[1] - t[0]) if len(t) > 1 else 4.0
    win = max(2, int(round(4.0 * fps_out)))
    nov = _novelty(feat, win)
    min_gap = max(2, int(round(min_section_s * fps_out)))
    bidx = _pick_boundaries(nov, min_gap)
    btimes = [float(t[i]) for i in bidx]

    # snap boundaries to nearest downbeat (the grid is the source of truth)
    dbs = np.asarray(downbeat_times, dtype=float)
    if len(dbs):
        btimes = [float(dbs[np.argmin(np.abs(dbs - bt))]) for bt in btimes]
    bounds = sorted({0.0, *[b for b in btimes if 0 < b < duration], round(duration, 3)})

    spans_t = list(zip(bounds[:-1], bounds[1:]))
    # feature spans (in feature-frame indices) for labeling + energy
    spans_i = [(int(np.searchsorted(t, s)), max(int(np.searchsorted(t, e)), int(np.searchsorted(t, s)) + 1))
               for s, e in spans_t]
    labels = _label(feat, spans_i)
    # relative loudness as an energy hint (0..1)
    rms = np.array([float(np.sqrt(np.mean(samples[int(s * sr):int(e * sr)] ** 2)) if e > s else 0.0)
                    for s, e in spans_t])
    rms = rms / (rms.max() + 1e-9)
    return [
        {"start": round(s, 3), "end": round(e, 3), "label": labels[i], "energy": round(float(rms[i]), 3)}
        for i, (s, e) in enumerate(spans_t)
    ]
