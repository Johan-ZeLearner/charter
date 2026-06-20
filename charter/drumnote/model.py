"""The ``DrumNote`` intermediate model — the contract every pipeline stage agrees on.

This is THE FIREWALL (see docs/02 and docs/08): every format gotcha (the
tom/cymbal inversion, opt-in 2x kick, dynamics encoding, same-color collisions)
is expressed in terms of these neutral fields and only resolved into actual
chart bytes by the serializer in :mod:`charter.drumnote.chart_writer`.

Nothing in this model knows about ``.chart`` note numbers. ``is_cymbal`` is a
plain boolean here; whether that becomes an opt-in flag (``.chart``) or an
opt-in marker (``.mid``) is the serializer's problem, not the model's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Lane(Enum):
    """A Clone Hero drum lane (4-lane Pro). Toms map high->low into Y/B/G."""

    KICK = "kick"
    RED = "red"
    YELLOW = "yellow"
    BLUE = "blue"
    GREEN = "green"

    @property
    def is_colored(self) -> bool:
        """True for the yellow/blue/green lanes that carry a cymbal/tom marker."""
        return self in (Lane.YELLOW, Lane.BLUE, Lane.GREEN)


class Dynamic(Enum):
    """Velocity-derived dynamic. Gates (docs/07 §5): ghost <=60, accent >=120."""

    GHOST = "ghost"
    NORMAL = "normal"
    ACCENT = "accent"


class Difficulty(Enum):
    """The four CH difficulty tracks. Expert is the master (docs/07 §6)."""

    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    EXPERT = "Expert"

    @property
    def chart_section(self) -> str:
        """The ``.chart`` instrument-section name, e.g. ``ExpertDrums``."""
        return f"{self.value}Drums"


# The cymbal/tom marker is meaningless on kick and snare:
#   - Kick is the foot lane.
#   - Red (snare) is ALWAYS a tom and never carries a cymbal marker (docs/03 §3).
_CYMBAL_CAPABLE = frozenset({Lane.YELLOW, Lane.BLUE, Lane.GREEN})


@dataclass
class DrumNote:
    """One playable drum gem.

    Attributes:
        tick: Position on the ``Resolution=192`` grid (set by quantization /
            MIDI tick conversion; the serializer never recomputes it).
        lane: Which CH pad/foot.
        is_cymbal: For yellow/blue/green only. The inversion lives in the
            serializer, NOT here: ``.chart`` defaults toms and emits cymbal
            flags 66/67/68 iff ``is_cymbal``; ``.mid`` does the opposite.
        is_kick2x: Inferred double-kick (~150ms gap, Expert only). Serialized as
            ``.chart`` type 32 / ``.mid`` note 95. Collapsed to a single kick on
            lower difficulties.
        dynamic: ghost / normal / accent (Pro Drums only).
        velocity: Raw 1..127 source of ``dynamic``, carried for fidelity/debug.
    """

    tick: int
    lane: Lane
    is_cymbal: bool = False
    is_kick2x: bool = False
    dynamic: Dynamic = Dynamic.NORMAL
    velocity: int | None = None

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError(f"tick must be >= 0, got {self.tick}")
        # Enforce the format invariants at the model boundary so an illegal
        # DrumNote can never reach the serializer.
        if self.is_cymbal and self.lane not in _CYMBAL_CAPABLE:
            raise ValueError(
                f"{self.lane.value} cannot be a cymbal; only yellow/blue/green can"
            )
        if self.is_kick2x and self.lane is not Lane.KICK:
            raise ValueError("is_kick2x is only valid on the kick lane")
        if self.velocity is not None and not (0 <= self.velocity <= 127):
            raise ValueError(f"velocity out of range: {self.velocity}")
