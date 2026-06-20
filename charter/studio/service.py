"""The preview service: a clip + settings -> notes-with-times JSON (+ clip WAV).

Mirrors ``charter.audio.pipeline.transcribe_buffer`` but inlines the stages so we
can return the *beat grid* — the highway needs the real beat times, and note
times must be offset by ``beat_times[0]`` because chart tick-0 maps to the first
tracked beat, not to audio t=0. Without that offset the highway drifts against
the music.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import numpy as np

from ..audio.beats import choose_beat_tracker
from ..audio.ingest import decode_audio, read_tags
from ..audio.quantize import build_tempo_map, quantize_onsets
from ..audio.adt import BaselineDrumTranscriber
from ..mapping import map_events
from .presets import build_configs, resolve_settings


def song_meta(path: str | Path) -> dict[str, Any]:
    """Title/artist/duration for the loaded song (best-effort via ffprobe)."""
    tags = read_tags(path)
    return {
        "name": tags.title or Path(path).stem,
        "artist": tags.artist or "Unknown Artist",
        "duration_s": (tags.duration_ms or 0) / 1000.0,
    }


def run_preview(
    path: str | Path,
    start_s: float,
    length_s: float,
    raw_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    """Transcribe the window ``[start_s, start_s+length_s)`` and return preview JSON."""
    settings = resolve_settings(raw_settings)
    audio = decode_audio(path, start_seconds=start_s, max_seconds=length_s)

    sep, bcfg, mcfg, subdiv = build_configs(settings)
    transcriber = BaselineDrumTranscriber(bcfg)
    beat_tracker = choose_beat_tracker()

    drums = sep.separate(audio)
    grid = beat_tracker.track(drums)
    onsets = transcriber.transcribe(drums)
    tempo_map = build_tempo_map(grid)
    events = quantize_onsets(onsets, grid, subdivisions=subdiv)
    mapped = map_events(events, tempo_map, mcfg)

    # chart tick-0 == first tracked beat, so shift note times into audio time.
    beat0 = float(grid.beat_times[0]) if len(grid.beat_times) else 0.0

    notes = [
        {
            "t": round(beat0 + tempo_map.tick_to_seconds(n.tick), 4),
            "tick": n.tick,
            "lane": n.lane.value,            # kick|red|yellow|blue|green
            "cymbal": bool(n.is_cymbal),
            "kick2x": bool(n.is_kick2x),
            "dyn": n.dynamic.value,          # ghost|normal|accent
            "vel": n.velocity or 0,
        }
        for n in mapped.notes
    ]
    notes.sort(key=lambda d: d["t"])

    return {
        "window": {"start_s": start_s, "length_s": length_s},
        "audioUrl": f"/api/audio?start_s={start_s:g}&length_s={length_s:g}",
        "bpm": round(float(grid.bpm or 0.0), 1),
        "beatsPerBar": int(grid.beats_per_bar),
        "beats": [round(float(b), 4) for b in grid.beat_times],
        "downbeats": [round(float(b), 4) for b in grid.downbeat_times],
        "notes": notes,
        "settings": {k: v for k, v in settings.items() if not k.startswith("_")},
        "genre": settings.get("_genre", "Default"),
        "diagnostics": {
            "drum_rms": round(float(drums.rms()), 5),
            "gate": _gate(float(drums.rms())),
            "bpm": round(float(grid.bpm or 0.0), 1),
            "beats": int(len(grid.beat_times)),
            "onsets": int(len(onsets)),
            "notes": int(len(notes)),
            "separator": sep.name,
            "transcriber": transcriber.name,
            "warnings": list(mapped.warnings)[:12],
        },
    }


def _gate(rms: float) -> str:
    if rms < 0.012:
        return "REFUSE"
    if rms < 0.018:
        return "CAUTION"
    return "GO"


def clip_wav_bytes(path: str | Path, start_s: float, length_s: float) -> bytes:
    """Decode the window and return it as 16-bit mono PCM WAV (stdlib only)."""
    audio = decode_audio(path, start_seconds=start_s, max_seconds=length_s)
    pcm = np.clip(audio.samples, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sr)
        w.writeframes(pcm16.tobytes())
    return buf.getvalue()
