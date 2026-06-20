"""Stage 6: GM-drum MIDI -> legal Clone Hero ``DrumNote`` mapping.

Mapping table (docs/07 §2), collision resolver + 2x-kick inference (§3-4), and a
dependency-free MIDI loader. The deterministic, zero-ML half of the pipeline.
"""

from .gm_map import MapConfig
from .midi_loader import load_drum_midi
from .stage6 import MapResult, RawDrumEvent, map_events

__all__ = ["MapConfig", "MapResult", "RawDrumEvent", "load_drum_midi", "map_events"]
