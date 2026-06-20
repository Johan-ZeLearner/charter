"""GM percussion note -> Clone Hero lane mapping (docs/07 §2).

Seeded from ``apvilkko/midi2clonehero`` — the most accurate open-source GM->CH
Expert Pro-Drums converter. The table is data, not hardcoded ``if``s, so
non-standard kits and the crash/ride policy can be overridden via config.

Numbers are GM percussion note numbers (C1 = 36). Preserve them verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..drumnote.model import Lane

# (lane, is_cymbal) for each GM percussion note.
_DEFAULT_TABLE: dict[int, tuple[Lane, bool]] = {
    # Kick
    35: (Lane.KICK, False),
    36: (Lane.KICK, False),
    # Snare / sidestick / clap -> red (always a tom; never a cymbal)
    37: (Lane.RED, False),
    38: (Lane.RED, False),
    39: (Lane.RED, False),
    40: (Lane.RED, False),
    # Toms high->low into yellow/blue/green TOM
    48: (Lane.YELLOW, False),  # high tom
    50: (Lane.YELLOW, False),  # high-mid tom
    45: (Lane.BLUE, False),  # low tom
    47: (Lane.BLUE, False),  # low-mid tom
    41: (Lane.GREEN, False),  # low floor tom
    43: (Lane.GREEN, False),  # high floor tom
    # Hi-hats -> yellow CYMBAL
    42: (Lane.YELLOW, True),  # closed hat
    44: (Lane.YELLOW, True),  # pedal hat
    46: (Lane.YELLOW, True),  # open hat
    # Crash1 / china / splash -> blue CYMBAL
    49: (Lane.BLUE, True),  # crash 1
    52: (Lane.BLUE, True),  # china
    55: (Lane.BLUE, True),  # splash
    # Ride / ride-bell / crash2 / ride2 -> green CYMBAL
    51: (Lane.GREEN, True),  # ride
    53: (Lane.GREEN, True),  # ride bell
    57: (Lane.GREEN, True),  # crash 2
    59: (Lane.GREEN, True),  # ride 2
}


@dataclass
class MapConfig:
    """Configurable mapping policy (docs/07 §2, §3.3, §5).

    Thresholds and the table are exposed so non-standard kits and tuning are
    possible without touching code.
    """

    table: dict[int, tuple[Lane, bool]] = field(
        default_factory=lambda: dict(_DEFAULT_TABLE)
    )
    ghost_max_velocity: int = 60  # velocity <= this -> ghost
    accent_min_velocity: int = 120  # velocity >= this -> accent
    double_kick_gap_seconds: float = 0.150  # < this gap from prior kick -> 2x kick

    def lookup(self, gm_note: int) -> tuple[Lane, bool] | None:
        """Return (lane, is_cymbal) for a GM note, or None if out of table."""
        return self.table.get(gm_note)
