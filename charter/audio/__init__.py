"""Audio frontend (Stages 0-5): mp3 -> drum onsets + tempo grid.

Dependency-free baseline (numpy/scipy + FFmpeg) with optional SOTA adapters
(Demucs / Beat This! / ADTOF) used if installed. See docs/04, docs/05, docs/06.
"""

from .interfaces import AudioBuffer, BeatGrid, Diagnostics, DrumOnset
from .pipeline import mp3_to_chart_folder, transcribe_buffer, transcribe_file

__all__ = [
    "AudioBuffer",
    "BeatGrid",
    "Diagnostics",
    "DrumOnset",
    "mp3_to_chart_folder",
    "transcribe_buffer",
    "transcribe_file",
]
