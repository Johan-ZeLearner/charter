"""The ``.chart`` serializer — THE place the tom/cymbal inversion lives.

Every constant here is the format firewall (docs/03 §3, §5; docs/07 §2-5).
Get a number wrong and you silently corrupt every chart, so each mapping cites
the spec and is covered by ``tests/test_chart_writer.py``.

Key invariants enforced/encoded here:
  * ``Resolution = 192`` (ticks per quarter).
  * Tempo ``B = round(bpm*1000)``; time signature ``TS <num> [<exp>]`` where the
    second number is an EXPONENT (denominator = 2**exp), omitted when ==2.
  * Drum notes are TOMS BY DEFAULT; a cymbal needs an opt-in flag 66/67/68.
  * Red is always a tom; kick/red never carry a cymbal flag.
  * 2x kick is opt-in: normal kick = ``N 0``, double-kick = ``N 32``.
  * Dynamics are explicit modifier note types (accent 34-37, ghost 40-43),
    NOT velocity (that is the ``.mid`` mechanism).
"""

from __future__ import annotations

from .model import DrumNote, Dynamic, Lane
from .tempo import TempoMap

# --- .chart drum note type codes (docs/03 §3) --------------------------------
_LANE_NOTE = {
    Lane.KICK: 0,
    Lane.RED: 1,
    Lane.YELLOW: 2,
    Lane.BLUE: 3,
    Lane.GREEN: 4,  # type 4 == 4-lane green (== 5-lane orange in 5-lane mode)
}
_KICK2X_NOTE = 32

# Cymbal flags (opt-in; share the gem's tick). Yellow=66, Blue=67, Green=68.
_CYMBAL_FLAG = {Lane.YELLOW: 66, Lane.BLUE: 67, Lane.GREEN: 68}

# Dynamics modifiers, per colored lane (docs/07 §5). 5-lane green (38/44) unused.
_ACCENT_FLAG = {Lane.RED: 34, Lane.YELLOW: 35, Lane.BLUE: 36, Lane.GREEN: 37}
_GHOST_FLAG = {Lane.RED: 40, Lane.YELLOW: 41, Lane.BLUE: 42, Lane.GREEN: 43}

# Sort order of multiple events on one tick: base gem first, then flags. Purely
# cosmetic (CH parses by tick) but keeps output deterministic and diff-able.
_ORDER_BASE = 0
_ORDER_CYMBAL = 1
_ORDER_DYNAMIC = 2

_INDENT = "  "


def _note_lines(note: DrumNote) -> list[tuple[int, int, str]]:
    """Yield (tick, order, text) tuples for one DrumNote's ``.chart`` events."""
    out: list[tuple[int, int, str]] = []

    if note.lane is Lane.KICK:
        base = _KICK2X_NOTE if note.is_kick2x else _LANE_NOTE[Lane.KICK]
        out.append((note.tick, _ORDER_BASE, f"N {base} 0"))
        return out  # kick carries no cymbal/dynamics flags

    out.append((note.tick, _ORDER_BASE, f"N {_LANE_NOTE[note.lane]} 0"))

    # The inversion: emit a cymbal flag IFF this colored gem is a cymbal.
    if note.is_cymbal:
        out.append((note.tick, _ORDER_CYMBAL, f"N {_CYMBAL_FLAG[note.lane]} 0"))

    if note.dynamic is Dynamic.ACCENT:
        out.append((note.tick, _ORDER_DYNAMIC, f"N {_ACCENT_FLAG[note.lane]} 0"))
    elif note.dynamic is Dynamic.GHOST:
        out.append((note.tick, _ORDER_DYNAMIC, f"N {_GHOST_FLAG[note.lane]} 0"))

    return out


def render_sync_track(tempo_map: TempoMap) -> str:
    """Render the ``[SyncTrack]`` section from the tempo map."""
    tm = tempo_map.normalized()
    rows: list[tuple[int, int, str]] = []
    # TS before B at a shared tick (Moonscraper convention).
    for ts in tm.time_sigs:
        if ts.denom_exp == 2:
            text = f"TS {ts.numerator}"
        else:
            text = f"TS {ts.numerator} {ts.denom_exp}"
        rows.append((ts.tick, 0, text))
    for b in tm.tempos:
        rows.append((b.tick, 1, f"B {b.chart_value}"))
    rows.sort(key=lambda r: (r[0], r[1]))
    body = "\n".join(f"{_INDENT}{tick} = {text}" for tick, _, text in rows)
    return f"[SyncTrack]\n{{\n{body}\n}}"


def render_song_section(
    *,
    resolution: int,
    offset_seconds: float,
    name: str,
    artist: str,
    charter: str,
) -> str:
    """Render the ``[Song]`` header. Sync is baked via ``Offset`` (never delay)."""
    lines = [
        f'{_INDENT}Name = "{name}"',
        f'{_INDENT}Artist = "{artist}"',
        f'{_INDENT}Charter = "{charter}"',
        f"{_INDENT}Offset = {offset_seconds:g}",
        f"{_INDENT}Resolution = {resolution}",
    ]
    return "[Song]\n{\n" + "\n".join(lines) + "\n}"


def render_difficulty_section(section_name: str, notes: list[DrumNote]) -> str:
    """Render one ``[<Difficulty>Drums]`` section, sorted by (tick, order)."""
    rows: list[tuple[int, int, str]] = []
    for note in notes:
        rows.extend(_note_lines(note))
    rows.sort(key=lambda r: (r[0], r[1]))
    body = "\n".join(f"{_INDENT}{tick} = {text}" for tick, _, text in rows)
    if body:
        return f"[{section_name}]\n{{\n{body}\n}}"
    return f"[{section_name}]\n{{\n}}"


def render_chart(
    *,
    tempo_map: TempoMap,
    tracks: dict[str, list[DrumNote]],
    name: str,
    artist: str,
    charter: str,
    offset_seconds: float = 0.0,
) -> str:
    """Render a full ``.chart`` file.

    ``tracks`` maps a ``[...]Drums`` section name to its notes. Only non-empty
    sections are emitted, in Expert->Hard->Medium->Easy order.
    """
    parts = [
        render_song_section(
            resolution=tempo_map.resolution,
            offset_seconds=offset_seconds,
            name=name,
            artist=artist,
            charter=charter,
        ),
        render_sync_track(tempo_map),
    ]
    order = ["ExpertDrums", "HardDrums", "MediumDrums", "EasyDrums"]
    for section in order:
        if section in tracks and tracks[section]:
            parts.append(render_difficulty_section(section, tracks[section]))
    # Newline-terminated, sections separated by a blank line.
    return "\n".join(parts) + "\n"
