"""A minimal, dependency-free Standard MIDI File reader/writer.

Scope is deliberately narrow — exactly what the symbolic MVP needs (docs/10
Phase 2): read/write type-1 SMF with note on/off, set-tempo, time-signature, and
end-of-track meta events. This keeps the symbolic backend installable with zero
third-party packages so the format/round-trip tests run offline.

When the audio frontend (Phase 3) needs to ingest arbitrary real-world MIDI from
a transcription model, swap this for ``mido`` behind :mod:`charter.mapping.midi_loader`;
the loader returns a normalized event list either way.

References: Standard MIDI File 1.0 spec (MThd/MTrk chunks, variable-length
quantities, running status, meta events).
"""

from __future__ import annotations

from dataclasses import dataclass

# Meta event sub-types we care about.
_META_TEMPO = 0x51
_META_TIME_SIG = 0x58
_META_END_OF_TRACK = 0x2F


@dataclass
class NoteOn:
    tick: int  # absolute tick
    channel: int
    note: int
    velocity: int


@dataclass
class SetTempo:
    tick: int
    us_per_quarter: int  # microseconds per quarter note

    @property
    def bpm(self) -> float:
        return 60_000_000.0 / self.us_per_quarter


@dataclass
class TimeSignature:
    tick: int
    numerator: int
    denom_exp: int  # denominator = 2 ** denom_exp


@dataclass
class MidiData:
    ticks_per_quarter: int
    note_ons: list[NoteOn]
    tempos: list[SetTempo]
    time_sigs: list[TimeSignature]


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read(self, n: int) -> bytes:
        b = self.data[self.pos : self.pos + n]
        if len(b) != n:
            raise ValueError("unexpected end of MIDI data")
        self.pos += n
        return b

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        b = self.read(2)
        return (b[0] << 8) | b[1]

    def u32(self) -> int:
        b = self.read(4)
        return int.from_bytes(b, "big")

    def varlen(self) -> int:
        """Read a MIDI variable-length quantity."""
        value = 0
        while True:
            byte = self.u8()
            value = (value << 7) | (byte & 0x7F)
            if not (byte & 0x80):
                return value


def read_midi(data: bytes) -> MidiData:
    """Parse SMF bytes into a normalized :class:`MidiData`."""
    r = _Reader(data)
    if r.read(4) != b"MThd":
        raise ValueError("not a Standard MIDI File (missing MThd)")
    header_len = r.u32()
    fmt = r.u16()
    ntracks = r.u16()
    division = r.u16()
    # Consume any extra header bytes (header_len is usually 6).
    if header_len > 6:
        r.read(header_len - 6)
    if division & 0x8000:
        raise ValueError("SMPTE time division is unsupported (CH needs ticks-per-quarter)")
    if fmt not in (0, 1):
        raise ValueError(f"unsupported MIDI format type {fmt} (need 0 or 1)")
    ticks_per_quarter = division

    note_ons: list[NoteOn] = []
    tempos: list[SetTempo] = []
    time_sigs: list[TimeSignature] = []

    for _ in range(ntracks):
        if r.read(4) != b"MTrk":
            raise ValueError("expected MTrk chunk")
        length = r.u32()
        end = r.pos + length
        abs_tick = 0
        running_status = None
        while r.pos < end:
            delta = r.varlen()
            abs_tick += delta
            status = r.u8()
            if status < 0x80:
                # Running status: reuse previous status, rewind one byte.
                if running_status is None:
                    raise ValueError("running status with no prior status byte")
                r.pos -= 1
                status = running_status
            else:
                running_status = status if status < 0xF0 else running_status

            if status == 0xFF:  # meta
                meta_type = r.u8()
                meta_len = r.varlen()
                payload = r.read(meta_len)
                if meta_type == _META_TEMPO and meta_len == 3:
                    tempos.append(SetTempo(abs_tick, int.from_bytes(payload, "big")))
                elif meta_type == _META_TIME_SIG and meta_len >= 2:
                    time_sigs.append(TimeSignature(abs_tick, payload[0], payload[1]))
                elif meta_type == _META_END_OF_TRACK:
                    break
            elif status in (0xF0, 0xF7):  # sysex
                sysex_len = r.varlen()
                r.read(sysex_len)
            else:
                high = status & 0xF0
                channel = status & 0x0F
                if high in (0x80, 0x90, 0xA0, 0xB0, 0xE0):  # 2 data bytes
                    d1 = r.u8()
                    d2 = r.u8()
                    if high == 0x90 and d2 > 0:
                        note_ons.append(NoteOn(abs_tick, channel, d1, d2))
                    # note-off (0x80) and note_on vel 0 are ignored: drums are
                    # one-shots and we only place onsets.
                elif high in (0xC0, 0xD0):  # 1 data byte
                    r.u8()
                else:
                    raise ValueError(f"unexpected status byte 0x{status:02X}")
        r.pos = end  # be robust to a missing end-of-track meta

    return MidiData(ticks_per_quarter, note_ons, tempos, time_sigs)


# --------------------------------------------------------------------------- #
# Writing (used to build hand-made test fixtures)
# --------------------------------------------------------------------------- #
def _varlen(value: int) -> bytes:
    if value < 0:
        raise ValueError("varlen cannot encode a negative number")
    buf = [value & 0x7F]
    value >>= 7
    while value:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(buf))


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + len(body).to_bytes(4, "big") + body


@dataclass
class DrumHit:
    """A drum onset for the fixture writer: ``note`` at ``tick`` with ``velocity``."""

    tick: int
    note: int
    velocity: int
    duration: int = 1  # ticks until note-off (drums are short one-shots)


def write_drum_midi(
    *,
    ticks_per_quarter: int,
    hits: list[DrumHit],
    tempos: list[SetTempo] | None = None,
    time_sigs: list[TimeSignature] | None = None,
    channel: int = 9,  # GM drums = MIDI channel 10 (0-indexed 9)
) -> bytes:
    """Serialize a clean type-1 SMF: a conductor track + one drum track."""
    tempos = tempos or [SetTempo(0, 500_000)]  # default 120 BPM
    time_sigs = time_sigs or [TimeSignature(0, 4, 2)]

    # --- Track 0: tempo + time-signature conductor track ---
    meta_events: list[tuple[int, bytes]] = []
    for ts in time_sigs:
        # cc (clocks per metronome click) = 24, bb (32nds per quarter) = 8.
        body = bytes([0xFF, _META_TIME_SIG, 4, ts.numerator, ts.denom_exp, 24, 8])
        meta_events.append((ts.tick, body))
    for tp in tempos:
        body = bytes([0xFF, _META_TEMPO, 3]) + tp.us_per_quarter.to_bytes(3, "big")
        meta_events.append((tp.tick, body))
    track0 = _encode_track(meta_events)

    # --- Track 1: drum note on/off pairs ---
    note_events: list[tuple[int, bytes]] = []
    for h in hits:
        note_events.append((h.tick, bytes([0x90 | channel, h.note, h.velocity])))
        note_events.append((h.tick + h.duration, bytes([0x80 | channel, h.note, 0])))
    track1 = _encode_track(note_events)

    header = (1).to_bytes(2, "big")  # format type 1
    header += (2).to_bytes(2, "big")  # 2 tracks
    header += ticks_per_quarter.to_bytes(2, "big")
    return _chunk(b"MThd", header) + _chunk(b"MTrk", track0) + _chunk(b"MTrk", track1)


def _encode_track(events: list[tuple[int, bytes]]) -> bytes:
    """Encode (abs_tick, raw_event_bytes) pairs into MTrk body with delta times."""
    # Stable sort by tick keeps note-on before its later note-off and preserves
    # insertion order for same-tick events.
    events = sorted(events, key=lambda e: e[0])
    out = bytearray()
    last_tick = 0
    for tick, ev in events:
        out += _varlen(tick - last_tick)
        out += ev
        last_tick = tick
    out += _varlen(0) + bytes([0xFF, _META_END_OF_TRACK, 0])
    return bytes(out)
