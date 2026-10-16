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


def _bpm_grid(bpm_min: float, bpm_max: float, step: float = 1.0) -> np.ndarray:
    return np.arange(float(bpm_min), float(bpm_max) + step, step, dtype=float)


def _acf_tempogram(env: np.ndarray, fps: float, bpms: np.ndarray) -> np.ndarray:
    """Autocorrelation strength on a BPM grid. Emphasises a tempo and its
    *subharmonics* (T, 2T, 3T → bpm, bpm/2, bpm/3): the half-time peak is strong.
    """
    e = env - env.mean()
    ac = signal.correlate(e, e, mode="full")
    ac = ac[len(ac) // 2:]  # non-negative lags
    if ac[0] != 0:
        ac = ac / ac[0]
    n = len(ac)
    lags = 60.0 * fps / np.clip(bpms, 1e-6, None)
    out = np.zeros(len(bpms))
    valid = (lags >= 1.0) & (lags <= n - 2)
    li = lags[valid]
    lo = np.floor(li).astype(int)
    frac = li - lo
    out[valid] = ac[lo] * (1.0 - frac) + ac[lo + 1] * frac  # linear interp between lags
    return np.maximum(out, 0.0)


def _dft_tempogram(env: np.ndarray, fps: float, bpms: np.ndarray) -> np.ndarray:
    """Fourier magnitude at each tempo frequency. Emphasises a tempo and its
    *harmonics* (f0, 2f0, 3f0 → bpm, 2·bpm, 3·bpm): the double-time peak is strong.
    """
    e = env - env.mean()
    nn = len(e)
    t = np.arange(nn)
    out = np.empty(len(bpms))
    for j, bpm in enumerate(bpms):
        w = 2.0 * np.pi * (bpm / 60.0) / fps
        wt = w * t
        out[j] = np.hypot(e @ np.cos(wt), e @ np.sin(wt))
    return np.maximum(out, 0.0)


def hybrid_tempo_score(env: np.ndarray, fps: float, bpms: np.ndarray,
                       prior_bpm: float = 130.0, prior_sigma: float = 1.0) -> np.ndarray:
    """DFT × ACF product tempo salience over ``bpms``, with a wide perceptual prior.

    The ACF peaks at a tempo *and its subharmonics* (half-time); the DFT peaks at a
    tempo *and its harmonics* (double-time). Their elementwise product suppresses the
    *spurious* octave peaks that only one transform produces. But when a signal has
    genuine energy at several metrical levels (e.g. hats on every 8th, or a half-time
    backbeat), the product alone can't decide WHICH level is "the beat" — so a *wide*
    log-normal resonance prior (~130 BPM, σ≈1 octave) gently favours the perceptual
    tactus. This is deliberately far wider than the old σ=0.6 / 120-locked prior (the
    cause of the fast-metal half-time bug): with ``bpm_max`` now 300, true metal tempi
    (180–280) stay reachable while pure double/half octave artefacts are damped.
    """
    acf = _acf_tempogram(env, fps, bpms)
    m = acf.max()
    if m > 0:
        acf = acf / m
    dft = _dft_tempogram(env, fps, bpms)
    m = dft.max()
    if m > 0:
        dft = dft / m
    score = acf * dft
    if prior_bpm and prior_bpm > 0:
        score = score * np.exp(-0.5 * (np.log2(np.clip(bpms, 1e-6, None) / prior_bpm) / prior_sigma) ** 2)
    return score


def estimate_tempo(env: np.ndarray, fps: float, *, bpm_min: float = 60.0,
                   bpm_max: float = 300.0, prior_bpm: float = 130.0) -> float:
    """Estimate global tempo (BPM) via a hybrid DFT×ACF tempogram (octave-robust).

    Replaces the old ACF + log-normal-120-prior estimator, whose prior mathematically
    preferred half-time on fast metal. ``bpm_max`` is raised to 300 so genuinely fast
    tempos are reachable; ``prior_bpm`` is now only a soft tiebreaker.
    """
    if len(env) < 4:
        return prior_bpm
    bpms = _bpm_grid(bpm_min, bpm_max)
    score = hybrid_tempo_score(env, fps, bpms, prior_bpm)
    if not np.any(score > 0):
        return prior_bpm
    return float(bpms[int(np.argmax(score))])


def estimate_tempo_curve(env: np.ndarray, fps: float, *, center_bpm: float,
                         win_s: float = 8.0, hop_s: float = 0.5,
                         drift: float = 0.15) -> np.ndarray:
    """Per-frame local tempo (BPM) that *follows drift around* ``center_bpm``.

    Slides a local ACF tempogram across the onset envelope, but in each window picks
    the periodicity nearest ``center_bpm`` (a tight log-normal prior of width ``drift``
    octaves), NOT the globally strongest one. This is the critical distinction: an
    unconstrained per-window argmax happily jumps to the 8th/16th-note pulse in dense
    metal, which would make the drift-aware DP over-segment (median tempo ≫ the real
    beat). Anchoring to ``center_bpm`` keeps the curve a smooth small deviation, so the
    DP follows genuine accelerando/ritardando without octave-hopping. ``drift`` is the
    half-band: ~0.15 oct (±11%) for free detect, tighter when seeded by a tap.
    Returned length matches ``env`` (per-frame), ready for :func:`dp_beat_track`.

    ``center_bpm`` MUST already be the octave-correct global tempo (it is, in callers:
    the hybrid :func:`estimate_tempo` output or a tapped BPM). The search grid only spans
    ``center_bpm·2^(±3·drift)``, so a center that is itself an octave off cannot be
    recovered here — that is the global estimator's job, not the drift curve's.
    """
    n = len(env)
    if n < 2 or center_bpm <= 0:
        return np.full(max(n, 1), float(center_bpm) if center_bpm > 0 else 120.0)
    # grid extends a little past the drift band so the prior tails are represented
    bpms = _bpm_grid(center_bpm / (2 ** (3 * drift)), center_bpm * (2 ** (3 * drift)))
    prior = np.exp(-0.5 * (np.log2(np.clip(bpms, 1e-6, None) / center_bpm) / drift) ** 2)
    win = max(4, int(win_s * fps))
    hop = max(1, int(hop_s * fps))
    centers = np.arange(0, n, hop)
    if len(centers) == 0:
        centers = np.array([n // 2])
    local = np.empty(len(centers))
    for k, c in enumerate(centers):
        lo = max(0, c - win // 2)
        hi = min(n, c + win // 2)
        seg = env[lo:hi]
        if len(seg) < 4:
            local[k] = center_bpm
            continue
        acf = _acf_tempogram(seg, fps, bpms) * prior
        local[k] = bpms[int(np.argmax(acf))] if acf.max() > 0 else center_bpm
    if len(local) >= 5:
        local = signal.medfilt(local, kernel_size=5)  # kill single-window outliers
    curve = np.interp(np.arange(n), centers, local)
    return curve


def dp_beat_track(env: np.ndarray, fps: float, bpm, *,
                  tightness: float = 100.0,
                  anchors: np.ndarray | list[int] | None = None) -> np.ndarray:
    """Dynamic-programming beat tracker (Ellis 2007 / librosa-style).

    Returns beat frame indices. ``bpm`` may be:

    * a **scalar** — a single global tempo (the original fast path), or
    * a **per-frame array** (from :func:`estimate_tempo_curve`) — the expected
      period varies frame-to-frame, so the tracker follows accelerando/ritardando
      in a single pass instead of being pinned to one period for the whole song.

    ``anchors`` are frame indices the path is forced through (a tap / a hand-edited
    beat becomes a **hard pin**, not a soft prior): each gets a dominating score
    bonus so the optimal path always routes a beat onto it, while onsets still
    choose phase + drift between anchors. This is the missing middle ground between
    the soft ``tempo_hint`` and the rigid metronomic ``_locked_grid``. Anchors must be
    spaced at least ~half a beat apart (the DP places one beat per frame); duplicates
    are dropped and anchors closer than the local min transition are not all guaranteed.
    """
    n = len(env)
    if n < 2:
        return np.array([], dtype=int)
    local = env.astype(np.float64)
    std = local.std()
    if std > 0:
        local = (local - local.mean()) / std

    if anchors is not None:
        af = np.unique(np.asarray(list(anchors), dtype=int))  # sorted, de-duplicated
        af = af[(af >= 0) & (af < n)]
        if len(af):
            # bonus >> any achievable cumulative score, so including an anchor always wins
            local[af] += 10.0 * (float(np.abs(local).sum()) + 1.0)

    cumscore = np.zeros(n)
    backlink = np.full(n, -1, dtype=int)

    if np.ndim(bpm) == 0:
        # ---- scalar fast path (constant period; precompute offsets once) ----
        if bpm <= 0:
            return np.array([], dtype=int)
        period = 60.0 * fps / float(bpm)
        offsets = np.arange(-int(round(2 * period)), -int(round(period / 2)) + 1)
        offsets = offsets[offsets < 0]
        if len(offsets) == 0:
            return np.array([], dtype=int)
        txcost = -tightness * (np.log(-offsets / period)) ** 2
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
    else:
        # ---- drift path (per-frame period centered on the local tempo) ----
        b = np.asarray(bpm, dtype=float)
        if len(b) != n:  # resample a coarse curve up to per-frame
            b = np.interp(np.arange(n), np.linspace(0, n - 1, len(b)), b)
        period_arr = 60.0 * fps / np.clip(b, 1e-3, None)
        for i in range(n):
            p = period_arr[i]
            c0 = max(0, i - int(round(2 * p)))
            c1 = i - max(1, int(round(p / 2)))
            if c1 < c0:
                cumscore[i] = local[i]
                backlink[i] = -1
                continue
            cand = np.arange(c0, c1 + 1)
            dist = (i - cand).astype(float)
            tx = -tightness * (np.log(dist / p)) ** 2
            scores = tx + cumscore[cand]
            k = int(np.argmax(scores))
            cumscore[i] = local[i] + scores[k]
            backlink[i] = int(cand[k])

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
