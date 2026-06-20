"""Hand-made GM-drum MIDI fixtures for the symbolic-backend round-trip tests.

Each builder returns raw SMF bytes (so tests don't need files on disk). Run this
module directly to also write ``*.mid`` files into this folder for manual
inspection in Moonscraper / a DAW.

Conventions: 480 ticks/quarter, GM channel 10. Velocities: normal=100,
ghost=30, accent=127.
"""

from __future__ import annotations

from pathlib import Path

from charter.mapping.smf import (
    DrumHit,
    SetTempo,
    TimeSignature,
    write_drum_midi,
)

TPQ = 480
BAR = 4 * TPQ  # 4/4 bar
EIGHTH = TPQ // 2
SIXTEENTH = TPQ // 4

# GM percussion notes
KICK = 36
SNARE = 38
CLOSED_HAT = 42
CRASH1 = 49
RIDE = 51
HIGH_TOM = 48
LOW_TOM = 45
FLOOR_TOM = 41

NORMAL, GHOST, ACCENT = 100, 30, 127


def build_basic_groove() -> bytes:
    """Two bars of a rock groove exercising every lane + ghost/accent + a tom fill."""
    hits: list[DrumHit] = []
    for bar_start in (0, BAR):
        # kick on 1 & 3, snare on 2 & 4
        hits.append(DrumHit(bar_start + 0, KICK, NORMAL))
        hits.append(DrumHit(bar_start + 2 * TPQ, KICK, NORMAL))
        hits.append(DrumHit(bar_start + 1 * TPQ, SNARE, ACCENT))  # accented backbeat
        hits.append(DrumHit(bar_start + 3 * TPQ, SNARE, NORMAL))
        # closed hat on every 8th. In bar 2, stop the hats for the last beat so
        # the tom fill stands alone (as a drummer would actually play it).
        hat_eighths = 8 if bar_start == 0 else 6
        for i in range(hat_eighths):
            hits.append(DrumHit(bar_start + i * EIGHTH, CLOSED_HAT, NORMAL))
    # a ghost snare in bar 1
    hits.append(DrumHit(EIGHTH + SIXTEENTH, SNARE, GHOST))
    # crash on the downbeat
    hits.append(DrumHit(0, CRASH1, NORMAL))
    # tom fill at the end of bar 2 (high -> low across the kit)
    fill_start = BAR + 3 * TPQ
    hits.append(DrumHit(fill_start + 0 * SIXTEENTH, HIGH_TOM, NORMAL))
    hits.append(DrumHit(fill_start + 1 * SIXTEENTH, HIGH_TOM, NORMAL))
    hits.append(DrumHit(fill_start + 2 * SIXTEENTH, LOW_TOM, NORMAL))
    hits.append(DrumHit(fill_start + 3 * SIXTEENTH, FLOOR_TOM, NORMAL))
    return write_drum_midi(ticks_per_quarter=TPQ, hits=hits)


def build_double_kick() -> bytes:
    """Fast continuous kicks at 200 BPM -> every kick after the first is 2x."""
    us_per_quarter = round(60_000_000 / 200)
    hits = [DrumHit(i * SIXTEENTH, KICK, NORMAL) for i in range(8)]
    # a snare to keep it a real groove
    hits.append(DrumHit(0, SNARE, NORMAL))
    return write_drum_midi(
        ticks_per_quarter=TPQ,
        hits=hits,
        tempos=[SetTempo(0, us_per_quarter)],
    )


def build_tempo_change() -> bytes:
    """Bar 1: 120 BPM 4/4. Bar 2: 180 BPM in 7/8 (exercises tempo map + TS exponent)."""
    bar2 = BAR
    seven_eight = 7 * EIGHTH
    hits = [
        DrumHit(0, KICK, NORMAL),
        DrumHit(TPQ, SNARE, NORMAL),
        DrumHit(2 * TPQ, KICK, NORMAL),
        DrumHit(3 * TPQ, SNARE, NORMAL),
        DrumHit(bar2 + 0, KICK, NORMAL),
        DrumHit(bar2 + 2 * EIGHTH, SNARE, NORMAL),
        DrumHit(bar2 + 4 * EIGHTH, KICK, NORMAL),
        DrumHit(bar2 + seven_eight - EIGHTH, SNARE, NORMAL),
    ]
    return write_drum_midi(
        ticks_per_quarter=TPQ,
        hits=hits,
        tempos=[SetTempo(0, 500_000), SetTempo(bar2, round(60_000_000 / 180))],
        time_sigs=[TimeSignature(0, 4, 2), TimeSignature(bar2, 7, 3)],
    )


def build_same_color_collision() -> bytes:
    """A blue tom (45) and a crash1 (49 -> blue cymbal) on the SAME tick."""
    hits = [
        DrumHit(0, KICK, NORMAL),
        DrumHit(0, LOW_TOM, NORMAL),  # -> blue TOM
        DrumHit(0, CRASH1, NORMAL),  # -> blue CYMBAL (collides; must be re-colored)
    ]
    return write_drum_midi(ticks_per_quarter=TPQ, hits=hits)


_BUILDERS = {
    "basic_groove": build_basic_groove,
    "double_kick": build_double_kick,
    "tempo_change": build_tempo_change,
    "same_color_collision": build_same_color_collision,
}


def main() -> None:
    out_dir = Path(__file__).parent
    for name, builder in _BUILDERS.items():
        path = out_dir / f"{name}.mid"
        path.write_bytes(builder())
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
