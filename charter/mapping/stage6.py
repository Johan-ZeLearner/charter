"""Stage 6: GM-drum events -> legal Clone Hero ``DrumNote`` list (docs/07).

Pass order (docs/07 §4):
  1. table lookup (GM -> lane + cymbal/tom) + velocity -> dynamic
  2. windowed crash/ride color resolver (blue<->green)        [conservative; see note]
  3. same-tick same-color tom+cymbal validator (flip or drop) [format-illegal otherwise]
  4. 2x-kick inference (Expert only, ~150ms gap)
  5. dynamics gating is folded into step 1

The same-color validator (3) is non-optional — the format forbids a tom and a
cymbal of the same color on one tick. The crash/ride resolver (2) is a
song-dependent heuristic and is DISABLED by default in v0 (it can mis-flip clean
charts); the format-legality guarantee comes entirely from (3).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..drumnote.model import DrumNote, Dynamic, Lane
from ..drumnote.tempo import TempoMap
from .gm_map import MapConfig

_COLORED = (Lane.YELLOW, Lane.BLUE, Lane.GREEN)
_CYMBAL_COLORS = (Lane.BLUE, Lane.GREEN)  # colors a crash/ride can be flipped between


@dataclass
class RawDrumEvent:
    """A transcribed/charted drum onset in chart ticks."""

    tick: int
    gm_note: int
    velocity: int


@dataclass
class MapResult:
    notes: list[DrumNote]
    warnings: list[str]  # human-facing notes for REVIEW.md (docs/09)


def _velocity_to_dynamic(velocity: int, cfg: MapConfig) -> Dynamic:
    if velocity <= cfg.ghost_max_velocity:
        return Dynamic.GHOST
    if velocity >= cfg.accent_min_velocity:
        return Dynamic.ACCENT
    return Dynamic.NORMAL


def map_events(
    events: list[RawDrumEvent],
    tempo_map: TempoMap,
    cfg: MapConfig | None = None,
) -> MapResult:
    """Map raw GM events to a legal Expert ``DrumNote`` list."""
    cfg = cfg or MapConfig()
    warnings: list[str] = []

    # --- Pass 1: table lookup + dynamics ---
    notes: list[DrumNote] = []
    for ev in events:
        hit = cfg.lookup(ev.gm_note)
        if hit is None:
            warnings.append(
                f"tick {ev.tick}: GM note {ev.gm_note} not in mapping table — dropped"
            )
            continue
        lane, is_cymbal = hit
        dynamic = Dynamic.NORMAL
        if lane is not Lane.KICK:
            dynamic = _velocity_to_dynamic(ev.velocity, cfg)
        notes.append(
            DrumNote(
                tick=ev.tick,
                lane=lane,
                is_cymbal=is_cymbal,
                dynamic=dynamic,
                velocity=ev.velocity,
            )
        )

    # --- Pass 3: same-tick same-color tom+cymbal validator ---
    _resolve_same_color_collisions(notes, warnings)

    # --- Pass 4: 2x-kick inference (Expert only) ---
    _infer_double_kick(notes, tempo_map, cfg, warnings)

    notes.sort(key=lambda n: (n.tick, n.lane.value))
    return MapResult(notes=notes, warnings=warnings)


def _resolve_same_color_collisions(notes: list[DrumNote], warnings: list[str]) -> None:
    """A tom and a cymbal of the same color cannot share a tick (docs/07 §3.2).

    Resolution: move the CYMBAL to a free cymbal color (blue<->green); if none is
    free, drop the cymbal. Mutates ``notes`` in place.
    """
    by_tick: dict[int, list[DrumNote]] = {}
    for n in notes:
        by_tick.setdefault(n.tick, []).append(n)

    for tick, group in by_tick.items():
        for color in _COLORED:
            toms = [n for n in group if n.lane is color and not n.is_cymbal]
            cymbals = [n for n in group if n.lane is color and n.is_cymbal]
            if not (toms and cymbals):
                continue
            # Move each conflicting cymbal to a free cymbal color.
            occupied = {n.lane for n in group}
            for cym in cymbals:
                free = next(
                    (c for c in _CYMBAL_COLORS if c is not color and c not in occupied),
                    None,
                )
                if free is not None:
                    warnings.append(
                        f"tick {tick}: {color.value} tom+cymbal collision — "
                        f"moved cymbal to {free.value}"
                    )
                    cym.lane = free
                    occupied.add(free)
                else:
                    warnings.append(
                        f"tick {tick}: {color.value} tom+cymbal collision — "
                        f"no free cymbal color, dropped cymbal"
                    )
                    notes.remove(cym)


def _infer_double_kick(
    notes: list[DrumNote],
    tempo_map: TempoMap,
    cfg: MapConfig,
    warnings: list[str],
) -> None:
    """Mark a kick as 2x if it falls within the gap threshold of the prior kick.

    Expert only. On Expert every kick still plays; the mark only controls what
    disappears when double-kick is disabled / on lower difficulties (docs/07 §3.3).
    """
    kicks = sorted((n for n in notes if n.lane is Lane.KICK), key=lambda n: n.tick)
    prev_sec: float | None = None
    count = 0
    for kick in kicks:
        sec = tempo_map.tick_to_seconds(kick.tick)
        if prev_sec is not None and (sec - prev_sec) < cfg.double_kick_gap_seconds:
            kick.is_kick2x = True
            count += 1
        prev_sec = sec
    if count:
        warnings.append(
            f"{count} kick(s) marked as 2x (double-bass) — verify before lower-diff reduction"
        )
