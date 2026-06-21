"""Genre drum-pattern library + region application (the template approach).

Blind ADT on dense, distorted material (metal) is unreliable: stems bleed and
onset-per-stem produces an unrealistic smear. Instead of transcribing such
sections note-by-note, the user selects a region and applies a KNOWN genre
pattern — and the audio/ML refines only the robustly-detectable parts.

The key split (see docs): in metal the **kick pattern is song-specific** but
**reliably detectable**, while the **snare/cymbal voicing is genre-conventional**
but where ADT fails. So the hybrid is: kick from audio, voicing from a template,
both locked to the tempo grid.
"""

from __future__ import annotations

from .library import (
    LIBRARY,
    VOICE_MAP,
    Pattern,
    apply_pattern,
    list_patterns,
    pattern_by_name,
)

__all__ = [
    "LIBRARY",
    "VOICE_MAP",
    "Pattern",
    "apply_pattern",
    "list_patterns",
    "pattern_by_name",
]
