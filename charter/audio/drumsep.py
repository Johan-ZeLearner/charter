"""Per-drum-stem ADT — the quality engine (docs/04 Stage-2 arbiter, docs/05).

The band-energy baseline confuses bass for kick and can't find hi-hats, because
it classifies one mixed spectrum per onset. This engine instead SEPARATES the
audio into kick / snare / cymbals / toms stems with a drum-trained Hybrid Demucs
model (``inagoy/drumsep``), then runs onset detection PER STEM — so "which drum"
is decided by "which stem fired," which is exactly what fixes the two worst
failure modes (bass-as-kick, missing hi-hat groove).

Model: ``inagoy/drumsep`` (Hybrid Demucs, 4 stems, trained on a drum-separation
thesis dataset). Reuses the already-installed ``demucs`` package — no new
framework. Weights are a single ~167 MB download (see ``weights_path`` /
``download_weights``). Loads on Apple-Silicon MPS.

Honest limits: 4 stems means hi-hat shares the ``platillos`` (cymbals) stem with
crash/ride, so v1 maps the whole cymbals stem to a yellow hi-hat cymbal (safe,
playable groove) rather than risking wrong blue/green crash calls — the blue-lane
frontier (docs/09). Toms ARE pitch-split high/mid/low into yellow/blue/green by
spectral centroid. A 5-stem model (LarsNet) would separate hi-hat from cymbals;
left as a documented upgrade.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import dsp
from .interfaces import AudioBuffer, DrumOnset, DrumTranscriber

log = logging.getLogger("charter.audio")

# Google-Drive id for the inagoy/drumsep checkpoint (verified, ~167 MB).
DRUMSEP_GDRIVE_ID = "1-Dm666ScPkg8Gt2-lK3Ua0xOudWHZBGC"

# GM percussion notes per stem role (all already in the Stage-6 mapping table).
GM_KICK = 36
GM_SNARE = 38
GM_HAT = 42           # closed hi-hat -> yellow CYMBAL (hi-hat owns yellow)
# Toms split across blue/green ONLY, so they never collide with the yellow hi-hat
# (a yellow tom + yellow hi-hat on one tick forces the resolver to fake a blue
# crash — the blue-lane risk in docs/09). Bright toms -> blue, dark -> green.
GM_TOM_BLUE = 45      # rack tom  -> blue tom
GM_TOM_GREEN = 41     # floor tom -> green tom

# drumsep emits Spanish stem names, in this order.
_STEM_ROLE = {"bombo": "kick", "redoblante": "snare", "platillos": "cymbals", "toms": "toms"}


@dataclass
class DrumSepConfig:
    """Tunables for the per-stem ADT (exposed to the studio)."""

    onset_delta: float = 0.08        # per-stem peak-pick threshold
    onset_min_gap_s: float = 0.050   # min spacing within a stem
    tom_split: bool = True           # split toms blue/green by centroid (else all blue)
    tom_centroid_split: float = 180.0  # >= this Hz -> blue (rack), else green (floor)
    device: str | None = None        # mps/cuda/cpu override


# Module-level cache: the 167 MB checkpoint should load once per process.
_MODEL_CACHE: dict[str, object] = {}


def weights_path(explicit: str | Path | None = None) -> Path | None:
    """Resolve the checkpoint path. Search order: explicit -> $CHARTER_DRUMSEP_MODEL
    -> ./model/drumsep.th -> ~/.cache/charter/drumsep.th. Returns None if missing."""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env = os.environ.get("CHARTER_DRUMSEP_MODEL")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("model/drumsep.th"))
    candidates.append(Path.home() / ".cache" / "charter" / "drumsep.th")
    for c in candidates:
        if c.is_file():
            return c
    return None


def drumsep_available(explicit: str | Path | None = None) -> bool:
    """True iff demucs/torch are importable AND a weights file is present."""
    if importlib.util.find_spec("demucs") is None or importlib.util.find_spec("torch") is None:
        return False
    return weights_path(explicit) is not None


def download_weights(dest: str | Path | None = None) -> Path:
    """Fetch the drumsep checkpoint via gdown into ``dest`` (default ~/.cache/charter)."""
    try:
        import gdown
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pip install gdown to download the drumsep weights") from e
    dest = Path(dest) if dest else Path.home() / ".cache" / "charter" / "drumsep.th"
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading drumsep weights (~167 MB) -> %s", dest)
    gdown.download(id=DRUMSEP_GDRIVE_ID, output=str(dest), quiet=False)
    return dest


def _load_model(path: Path):
    key = str(path)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]
    import torch
    from demucs.states import load_model

    # torch >= 2.6 defaults torch.load to weights_only=True, which rejects the
    # pickled HDemucs class in this checkpoint. We trust the file (known repo),
    # so load the package ourselves and hand the dict to demucs' load_model
    # (which skips torch.load when given a dict).
    pkg = torch.load(str(path), map_location="cpu", weights_only=False)
    model = load_model(pkg)
    model.eval()
    _MODEL_CACHE[key] = model
    return model


def _pick_device(override: str | None):
    import torch

    if override:
        return override
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class DrumSepTranscriber(DrumTranscriber):
    """Separate into 4 drum stems, then detect onsets per stem (docs/05)."""

    name = "drumsep"

    def __init__(self, config: DrumSepConfig | None = None,
                 model_path: str | Path | None = None):
        self.cfg = config or DrumSepConfig()
        self.model_path = weights_path(model_path)
        if self.model_path is None:
            raise FileNotFoundError(
                "drumsep weights not found — run charter.audio.drumsep.download_weights() "
                "or set $CHARTER_DRUMSEP_MODEL"
            )

    def _separate(self, audio: AudioBuffer):
        import torch
        from demucs.apply import apply_model

        model = _load_model(self.model_path)
        sr = model.samplerate
        x = audio.samples
        if audio.sr != sr:  # drumsep is 44.1 kHz; our analysis SR matches, but be safe
            import scipy.signal as sps
            x = sps.resample(x, int(len(x) * sr / audio.sr)).astype(np.float32)
        wav = torch.tensor(x, dtype=torch.float32)[None, :].repeat(model.audio_channels, 1)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)
        device = _pick_device(self.cfg.device)

        def _run(dev):
            with torch.no_grad():
                return apply_model(model, wav[None], device=dev, split=True,
                                   overlap=0.1, progress=False)[0]
        try:
            out = _run(device)
        except Exception:  # pragma: no cover - MPS/CUDA quirks
            if device != "cpu":
                log.info("drumsep: %s failed, retrying on CPU", device)
                out = _run("cpu")
            else:
                raise
        out = out * ref.std() + ref.mean()
        stems = {}
        for i, name in enumerate(model.sources):
            role = _STEM_ROLE.get(name, name)
            stems[role] = out[i].mean(0).detach().cpu().numpy().astype(np.float32)
        return stems, sr

    def transcribe(self, audio: AudioBuffer) -> list[DrumOnset]:
        stems, sr = self._separate(audio)
        out: list[DrumOnset] = []
        out += self._stem_onsets(stems.get("kick"), sr, lambda *_: GM_KICK)
        out += self._stem_onsets(stems.get("snare"), sr, lambda *_: GM_SNARE)
        out += self._stem_onsets(stems.get("cymbals"), sr, lambda *_: GM_HAT)
        out += self._stem_onsets(stems.get("toms"), sr, self._tom_gm)
        out.sort(key=lambda o: o.time_s)
        return out

    def _stem_onsets(self, sig, sr, gm_for):
        """Onsets in one stem -> DrumOnset list. ``gm_for(spec, freqs, sr)`` picks the GM note."""
        if sig is None or sig.size == 0:
            return []
        env, fps = dsp.onset_envelope(sig, sr)
        frames = dsp.peak_pick(env, fps, delta=self.cfg.onset_delta,
                               min_gap_s=self.cfg.onset_min_gap_s)
        if len(frames) == 0:
            return []
        peak = max(env[frames].max(), 1e-9)
        S, freqs, _ = dsp.stft_mag(sig, sr)
        res = []
        for fi in frames:
            spec = S[:, min(fi, S.shape[1] - 1)]
            vel = int(np.clip(30 + 97 * (env[fi] / peak), 1, 127))
            res.append(DrumOnset(time_s=fi / fps, gm_note=gm_for(spec, freqs, sr),
                                 velocity=vel, confidence=float(env[fi] / peak)))
        return res

    def _tom_gm(self, spec, freqs, sr):
        """Map a tom onset to blue (rack) or green (floor) by spectral centroid."""
        if not self.cfg.tom_split:
            return GM_TOM_BLUE
        mag = spec + 1e-9
        centroid = float((freqs * mag).sum() / mag.sum())
        return GM_TOM_BLUE if centroid >= self.cfg.tom_centroid_split else GM_TOM_GREEN
