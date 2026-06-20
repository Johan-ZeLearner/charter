"""Unit tests for Stage 6: GM mapping, dynamics, collision resolver, 2x kick."""

from __future__ import annotations

from charter.drumnote import Dynamic, Lane
from charter.drumnote.tempo import TempoEvent, TempoMap
from charter.mapping import MapConfig, map_events
from charter.mapping.stage6 import RawDrumEvent


def _map(events, tempo_map=None):
    tm = tempo_map or TempoMap(tempos=[TempoEvent(0, 120.0)])
    return map_events(events, tm)


def test_basic_gm_lane_mapping():
    # Distinct ticks so each GM note maps in isolation (no same-color collisions).
    events = [
        RawDrumEvent(0, 36, 100),  # kick
        RawDrumEvent(48, 38, 100),  # snare -> red
        RawDrumEvent(96, 42, 100),  # closed hat -> yellow cymbal
        RawDrumEvent(144, 48, 100),  # high tom -> yellow tom
        RawDrumEvent(192, 49, 100),  # crash1 -> blue cymbal
        RawDrumEvent(240, 51, 100),  # ride -> green cymbal
        RawDrumEvent(288, 41, 100),  # floor tom -> green tom
    ]
    notes = {(n.lane, n.is_cymbal) for n in _map(events).notes}
    assert (Lane.KICK, False) in notes
    assert (Lane.RED, False) in notes
    assert (Lane.YELLOW, True) in notes  # hi-hat cymbal
    assert (Lane.YELLOW, False) in notes  # high tom
    assert (Lane.BLUE, True) in notes  # crash
    assert (Lane.GREEN, True) in notes  # ride
    assert (Lane.GREEN, False) in notes  # floor tom


def test_velocity_dynamics_gates():
    events = [
        RawDrumEvent(0, 38, 30),  # ghost snare
        RawDrumEvent(96, 38, 100),  # normal snare
        RawDrumEvent(192, 38, 127),  # accent snare
        RawDrumEvent(288, 36, 20),  # quiet kick -> still NORMAL (no kick dynamics)
    ]
    res = _map(events)
    by_tick = {n.tick: n for n in res.notes}
    assert by_tick[0].dynamic is Dynamic.GHOST
    assert by_tick[96].dynamic is Dynamic.NORMAL
    assert by_tick[192].dynamic is Dynamic.ACCENT
    assert by_tick[288].dynamic is Dynamic.NORMAL


def test_same_color_collision_moves_cymbal():
    # blue tom (45) + crash1 (49 -> blue cymbal) on the same tick.
    events = [RawDrumEvent(0, 45, 100), RawDrumEvent(0, 49, 100)]
    res = _map(events)
    toms = [(n.lane, n.is_cymbal) for n in res.notes if not n.is_cymbal]
    cymbals = [(n.lane, n.is_cymbal) for n in res.notes if n.is_cymbal]
    assert (Lane.BLUE, False) in toms  # the tom keeps blue
    assert (Lane.GREEN, True) in cymbals  # the cymbal was moved off blue
    assert (Lane.BLUE, True) not in cymbals  # no illegal same-color pair remains
    assert any("collision" in w for w in res.warnings)


def test_unknown_gm_note_dropped_with_warning():
    res = _map([RawDrumEvent(0, 99, 100)])  # 99 is not a GM percussion note we map
    assert res.notes == []
    assert any("not in mapping table" in w for w in res.warnings)


def test_double_kick_inference():
    # 200 BPM: a 16th note (48 chart ticks) is 0.075s apart -> under 150ms.
    tm = TempoMap(tempos=[TempoEvent(0, 200.0)])
    events = [RawDrumEvent(0, 36, 100), RawDrumEvent(48, 36, 100)]
    res = map_events(events, tm)
    kicks = sorted((n for n in res.notes if n.lane is Lane.KICK), key=lambda n: n.tick)
    assert kicks[0].is_kick2x is False  # first kick is the primary foot
    assert kicks[1].is_kick2x is True  # second is the inferred double-kick


def test_slow_kicks_not_marked_2x():
    # 120 BPM, kicks a full quarter (192 ticks = 0.5s) apart -> not 2x.
    tm = TempoMap(tempos=[TempoEvent(0, 120.0)])
    events = [RawDrumEvent(0, 36, 100), RawDrumEvent(192, 36, 100)]
    res = map_events(events, tm)
    assert all(n.is_kick2x is False for n in res.notes if n.lane is Lane.KICK)
