"""Stage 1: drum-stem separation (docs/04).

Baseline = dependency-free HPSS percussive emphasis. Optional SOTA adapter =
Demucs (used only if installed). The interface is identical so the rest of the
pipeline is blind to which ran.
"""

from __future__ import annotations

import importlib.util

import numpy as np

from . import dsp
from .interfaces import AudioBuffer, Separator


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
    """Demucs v4 (htdemucs_ft) drum stem — optional, used if installed (docs/04)."""

    name = "demucs"

    def __init__(self, model: str = "htdemucs_ft"):
        self.model = model

    def separate(self, audio: AudioBuffer) -> AudioBuffer:  # pragma: no cover
        # Imported lazily so the package has no hard torch/demucs dependency.
        import torch
        from demucs.apply import apply_model
        from demucs.pretrained import get_model

        model = get_model(self.model)
        model.eval()
        wav = torch.tensor(audio.samples, dtype=torch.float32)[None, None, :]
        wav = wav.repeat(1, model.audio_channels, 1)
        with torch.no_grad():
            sources = apply_model(model, wav, progress=False)[0]
        drums = sources[model.sources.index("drums")].mean(dim=0).cpu().numpy()
        return AudioBuffer(samples=drums.astype(np.float32), sr=audio.sr)


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def choose_separator(prefer: str = "auto") -> Separator:
    """Pick a separator. ``auto`` uses Demucs if installed, else HPSS baseline."""
    if prefer in ("auto", "demucs") and demucs_available():
        return DemucsSeparator()
    if prefer == "passthrough":
        return PassthroughSeparator()
    return PercussiveSeparator()
