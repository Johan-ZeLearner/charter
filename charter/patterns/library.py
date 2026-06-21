"""The pattern library + the tiler that turns a pattern into ``DrumNote``s.

A ``Pattern`` is one bar of 4/4 on a 16th-note grid (16 steps; step 0 = beat 1,
4 = beat 2, 8 = beat 3, 12 = beat 4). Each *voice* lists the steps it hits.
``apply_pattern`` tiles the bar across a region and places phrase crashes; an
optional ``kick_ticks`` (detected kick onsets) overrides the template kick so the
song's actual double-bass figure is used while the voicing stays conventional.

Voices map to Clone Hero lanes via ``VOICE_MAP``. The serializer's tom/cymbal
inversion still lives downstream — here we only set the neutral ``DrumNote``
fields (lane + is_cymbal).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..drumnote.model import DrumNote, Lane

# voice -> (lane, is_cymbal). Yellow carries hi-hat (cymbal) or high tom; blue/
# green carry crash/ride (cymbal) or mid/floor tom (tom).
VOICE_MAP: dict[str, tuple[Lane, bool]] = {
    "kick": (Lane.KICK, False),
    "snare": (Lane.RED, False),
    "hihat": (Lane.YELLOW, True),
    "ride": (Lane.GREEN, True),
    "crash": (Lane.BLUE, True),
    "tom_hi": (Lane.YELLOW, False),
    "tom_mid": (Lane.BLUE, False),
    "tom_lo": (Lane.GREEN, False),
}

# 16-step (16th-note) positions, for readability below.
_8THS = [0, 2, 4, 6, 8, 10, 12, 14]
_16THS = list(range(16))
_QUARTERS = [0, 4, 8, 12]
_BACKBEAT = [4, 12]          # snare on beats 2 & 4
_OFF8THS = [1, 3, 5, 7, 9, 11, 13, 15]


@dataclass
class Pattern:
    """One bar of 4/4 on a 16-step grid. ``voices`` maps voice -> [step indices]."""

    name: str
    genre: str
    voices: dict[str, list[int]] = field(default_factory=dict)
    steps: int = 16
    description: str = ""


# Patterns are intentionally a starting library — extend per genre. Metal-heavy
# because that is the user's case (the genre where ADT fails worst).
LIBRARY: list[Pattern] = [
    Pattern(
        "Double-bass groove (8th kick)", "Metal",
        {"kick": _8THS, "snare": _BACKBEAT, "ride": _8THS},
        description="Steady 8th double bass, snare on 2 & 4, ride on 8ths.",
    ),
    Pattern(
        "Double-bass groove (16th kick)", "Metal",
        {"kick": _16THS, "snare": _BACKBEAT, "hihat": _QUARTERS},
        description="Driving 16th double bass under a 2 & 4 backbeat — chorus feel.",
    ),
    Pattern(
        "Blast beat", "Metal",
        {"kick": _8THS, "snare": _OFF8THS, "ride": _8THS},
        description="Kick and snare alternate at 8ths (traditional blast).",
    ),
    Pattern(
        "Thrash / skank beat", "Metal",
        {"kick": _QUARTERS, "snare": [2, 6, 10, 14], "hihat": _8THS},
        description="Fast 2-feel: kick on quarters, snare on the off-beats.",
    ),
    Pattern(
        "D-beat", "Metal",
        {"kick": [0, 3, 8, 10], "snare": _BACKBEAT, "hihat": _8THS},
        description="Classic d-beat kick figure with a 2 & 4 backbeat.",
    ),
    Pattern(
        "Half-time / breakdown", "Metal",
        {"kick": [0, 3, 8], "snare": [8], "ride": _8THS},
        description="Heavy half-time: snare on beat 3, sparse syncopated kick.",
    ),
    Pattern(
        "Backbeat", "Rock",
        {"kick": [0, 8], "snare": _BACKBEAT, "hihat": _8THS},
        description="Standard rock backbeat: kick on 1 & 3, snare on 2 & 4.",
    ),
    Pattern(
        "Driving 8ths", "Rock",
        {"kick": [0, 6, 8, 14], "snare": _BACKBEAT, "hihat": _8THS},
        description="Busier rock groove with syncopated kick.",
    ),
    Pattern(
        "Punk 2-beat", "Punk",
        {"kick": _QUARTERS, "snare": _BACKBEAT, "hihat": _8THS},
        description="Fast four-on-the-floor punk feel.",
    ),
]


def list_patterns(genre: str | None = None) -> list[dict]:
    """Library as JSON-friendly dicts, optionally filtered by genre."""
    return [
        {"name": p.name, "genre": p.genre, "description": p.description}
        for p in LIBRARY
        if genre is None or p.genre == genre
    ]


def pattern_by_name(name: str) -> Pattern | None:
    return next((p for p in LIBRARY if p.name == name), None)


def apply_pattern(
    pattern: Pattern,
    n_bars: int,
    *,
    beats_per_bar: int = 4,
    resolution: int = 192,
    kick_ticks: list[int] | None = None,
    crash_every: int = 8,
) -> list[DrumNote]:
    """Tile ``pattern`` across ``n_bars`` bars -> ``DrumNote``s (Expert).

    ``kick_ticks`` (detected, already-quantized kick onset ticks) overrides the
    template's kick voice — the song-specific double bass over a conventional
    voicing. ``crash_every`` places a phrase crash on bar 0 and every Nth bar.
    """
    ticks_per_bar = beats_per_bar * resolution
    step_ticks = ticks_per_bar // pattern.steps
    notes: list[DrumNote] = []

    use_audio_kick = kick_ticks is not None
    for b in range(max(0, n_bars)):
        base = b * ticks_per_bar
        for voice, positions in pattern.voices.items():
            if voice == "kick" and use_audio_kick:
                continue  # the audio supplies the kick instead
            lane, is_cym = VOICE_MAP[voice]
            for i in positions:
                notes.append(DrumNote(tick=base + i * step_ticks, lane=lane, is_cymbal=is_cym))
        if crash_every and b % crash_every == 0:
            lane, is_cym = VOICE_MAP["crash"]
            notes.append(DrumNote(tick=base, lane=lane, is_cymbal=is_cym))

    if use_audio_kick:
        for t in kick_ticks:
            notes.append(DrumNote(tick=int(t), lane=Lane.KICK))

    notes.sort(key=lambda n: (n.tick, n.lane.value))
    return notes
