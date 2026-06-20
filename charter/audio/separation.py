"""Stage 1: drum-stem separation (docs/04).

Baseline = dependency-free HPSS percussive emphasis. Optional SOTA adapter =
Demucs (used only if installed). The interface is identical so the rest of the
pipeline is blind to which ran.
"""

from __future__ import annotations

import importlib.util
import logging

import numpy as np

from . import dsp
from .interfaces import AudioBuffer, Separator

log = logging.getLogger("charter.audio")


class PassthroughSeparator(Separator):
    """No separation — analyse the full mix. The trivial floor."""

    name = "passthrough"

    def separate(self, audio: AudioBuffer) -> AudioBuffer:
        return audio


class PercussiveSeparator(Separator):
    """Median-filter HPSS percussive emphasis (numpy/scipy only)."""

    name = "hpss"

    def separate(self, audio: AudioBuffer) -> AudioBuffer:
        perc = dsp.hpss_percussive(audio.samples, audio.sr)
        return AudioBuffer(samples=perc.astype(np.float32), sr=audio.sr)


class DemucsSeparator(Separator):
    """Demucs v4 drum stem — optional, used if installed (docs/04).

    Defaults to the single ``htdemucs`` model (one ~80 MB download, 4x faster
    than the bagged ``htdemucs_ft``) and the best available device (Apple-Silicon
    MPS / CUDA / CPU). Shows a progress bar — separation is the slow stage.
    """

    name = "demucs"

    def __init__(self, model: str = "htdemucs", device: str | None = None):
        self.model_name = model
        self.device = device

    def _pick_device(self) -> str:
        import torch

        if self.device:
            return self.device
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def separate(self, audio: AudioBuffer) -> AudioBuffer:  # pragma: no cover
        # Imported lazily so the package has no hard torch/demucs dependency.
        # (demucs.api is absent in some 4.0.1 builds, so use the stable
        # apply_model path and do the input normalization ourselves — the models
        # are trained on standardized input and skipping this hurts the stem.)
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        model = get_model(self.model_name)
        model.eval()
        device = self._pick_device()

        # mono -> model channels; decode_audio already gives us model.samplerate.
        wav = torch.tensor(audio.samples, dtype=torch.float32)[None, :]
        wav = wav.repeat(model.audio_channels, 1)  # (channels, T)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / (ref.std() + 1e-8)

        def _run(dev: str):
            with torch.no_grad():
                return apply_model(model, wav[None], device=dev, progress=True,
                                   shifts=0, split=True, overlap=0.1)[0]

        try:
            sources = _run(device)
        except Exception:
            if device != "cpu":  # MPS/CUDA quirks -> fall back to CPU
                sources = _run("cpu")
            else:
                raise
        drums = sources[model.sources.index("drums")] * ref.std() + ref.mean()
        mono = drums.mean(dim=0).detach().cpu().numpy()
        return AudioBuffer(samples=mono.astype(np.float32), sr=audio.sr)


class SmartSeparator(Separator):
    """Demucs with an automatic HPSS fallback for tracks it can't separate.

    Demucs is trained on acoustic drum kits; electronic / programmed percussion
    often lands in its ``other`` stem, leaving ``drums`` near-silent. When that
    happens we'd emit an empty chart — so if the Demucs drum stem is negligible
    relative to the mix, we fall back to HPSS (which grabs all transients).
    """

    name = "demucs"

    def __init__(self, device: str | None = None,
                 abs_floor: float = 0.005, rel_floor: float = 0.02):
        self.demucs = DemucsSeparator(device=device)
        self.hpss = PercussiveSeparator()
        self.abs_floor = abs_floor
        self.rel_floor = rel_floor

    def separate(self, audio: AudioBuffer) -> AudioBuffer:
        out = self.demucs.separate(audio)
        mix_rms, drum_rms = audio.rms(), out.rms()
        if drum_rms < self.abs_floor or drum_rms < self.rel_floor * mix_rms:
            log.info(
                "Demucs drum stem near-silent (%.4f vs mix %.4f) — this track has "
                "no acoustic kit Demucs recognizes; falling back to HPSS.",
                drum_rms, mix_rms,
            )
            self.name = "hpss (demucs drums empty)"
            return self.hpss.separate(audio)
        self.name = "demucs"
        return out


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def choose_separator(prefer: str = "auto", device: str | None = None) -> Separator:
    """Pick a separator.

    ``auto`` uses Demucs-with-HPSS-fallback if installed, else the HPSS baseline.
    ``demucs`` forces plain Demucs (no fallback); ``hpss`` / ``passthrough`` force
    those baselines.
    """
    if prefer == "auto" and demucs_available():
        return SmartSeparator(device=device)
    if prefer == "demucs" and demucs_available():
        return DemucsSeparator(device=device)
    if prefer == "passthrough":
        return PassthroughSeparator()
    return PercussiveSeparator()
