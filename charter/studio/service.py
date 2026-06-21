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

from ..audio import dsp
from ..audio.beats import choose_beat_tracker
from ..audio.ingest import decode_audio, read_tags
from ..audio.interfaces import AudioBuffer
from ..audio.drumsep import drumsep_available
from ..audio.quantize import build_tempo_map, quantize_onsets, resample_grid
from ..mapping import map_events
from ..patterns import LIBRARY, apply_pattern, list_patterns, pattern_by_name
from .presets import build_engine, resolve_settings


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
    """Preview the window ``[start_s, start_s+length_s)``.

    Two modes (``settings['mode']``): ``detect`` runs ADT; ``pattern`` tiles a
    genre pattern from the library across the window's bars (optionally with the
    kick taken from the audio). Both share the beat grid + response shape.
    """
    settings = resolve_settings(raw_settings)
    audio = decode_audio(path, start_seconds=start_s, max_seconds=length_s)
    beat_tracker = choose_beat_tracker()

    # Beat grid (shared). Always from a percussive signal; apply tempo correction.
    perc = AudioBuffer(dsp.hpss_percussive(audio.samples, audio.sr), audio.sr)
    grid = beat_tracker.track(perc)
    grid = resample_grid(grid, float(settings.get("tempo_mult", 1.0)))
    tempo_map = build_tempo_map(grid)

    if settings.get("mode") == "pattern":
        drum_notes, diag = _pattern_notes(audio, grid, tempo_map, settings)
        drum_rms = float(perc.rms())
    else:
        drum_notes, diag, drum_rms = _detect_notes(audio, grid, tempo_map, settings)

    # chart tick-0 == first tracked beat, so shift note times into audio time.
    beat0 = float(grid.beat_times[0]) if len(grid.beat_times) else 0.0
    notes = sorted(
        (
            {
                "t": round(beat0 + tempo_map.tick_to_seconds(n.tick), 4),
                "tick": n.tick,
                "lane": n.lane.value,
                "cymbal": bool(n.is_cymbal),
                "kick2x": bool(n.is_kick2x),
                "dyn": n.dynamic.value,
                "vel": n.velocity or 0,
            }
            for n in drum_notes
        ),
        key=lambda d: d["t"],
    )

    diag.update(
        drum_rms=round(drum_rms, 5),
        gate=_gate(drum_rms),
        bpm=round(float(grid.bpm or 0.0), 1),
        beats=int(len(grid.beat_times)),
        notes=int(len(notes)),
    )
    return {
        "window": {"start_s": start_s, "length_s": length_s},
        "audioUrl": f"/api/audio?start_s={start_s:g}&length_s={length_s:g}",
        "mode": settings.get("mode", "detect"),
        "bpm": round(float(grid.bpm or 0.0), 1),
        "beatsPerBar": int(grid.beats_per_bar),
        "beats": [round(float(b), 4) for b in grid.beat_times],
        "downbeats": [round(float(b), 4) for b in grid.downbeat_times],
        "notes": notes,
        "settings": {k: v for k, v in settings.items() if not k.startswith("_")},
        "genre": settings.get("_genre", "Default"),
        "engine": diag.get("transcriber", "pattern"),
        "drumsepAvailable": settings.get("_drumsep_available", False),
        "patterns": list_patterns(),
        "diagnostics": diag,
    }


def _detect_notes(audio, grid, tempo_map, settings):
    """ADT path: separate -> transcribe -> quantize -> map. Returns (notes, diag, rms)."""
    sep, transcriber, mcfg, subdiv = build_engine(settings)
    is_drumsep = transcriber.name == "drumsep"
    drums = sep.separate(audio)
    onsets = transcriber.transcribe(audio if is_drumsep else drums)
    events = quantize_onsets(onsets, grid, subdivisions=subdiv)
    mapped = map_events(events, tempo_map, mcfg)
    diag = {
        "onsets": int(len(onsets)),
        "separator": sep.name,
        "transcriber": transcriber.name,
        "warnings": list(mapped.warnings)[:12],
    }
    return mapped.notes, diag, float(drums.rms())


def _pattern_notes(audio, grid, tempo_map, settings):
    """Template path: tile a genre pattern across the window's bars.

    With ``kick_from_audio``, the template kick is replaced by detected kick
    onsets (drumsep kick stem) quantized to the grid — the song's real double
    bass under a conventional voicing. Returns (notes, diag)."""
    bpb = int(grid.beats_per_bar) or 4
    n_bars = len(grid.beat_times) // bpb
    pat = pattern_by_name(settings.get("pattern") or "") or (LIBRARY[0] if LIBRARY else None)
    warnings: list[str] = []

    kick_ticks = None
    if settings.get("kick_from_audio") and drumsep_available():
        try:
            from ..audio.drumsep import GM_KICK, DrumSepConfig, DrumSepTranscriber

            kt = DrumSepTranscriber(DrumSepConfig(device=settings.get("device")))
            kick_onsets = [o for o in kt.transcribe(audio) if o.gm_note == GM_KICK]
            events = quantize_onsets(kick_onsets, grid, subdivisions=int(settings["subdivisions"]))
            kick_ticks = sorted({e.tick for e in events})
            warnings.append(f"kick from audio: {len(kick_ticks)} hits (drumsep kick stem)")
        except Exception as exc:  # pragma: no cover
            warnings.append(f"kick-from-audio failed ({exc}); using template kick")
    elif settings.get("kick_from_audio"):
        warnings.append("kick-from-audio needs drumsep weights; using template kick")

    notes = apply_pattern(pat, n_bars, beats_per_bar=bpb, resolution=tempo_map.resolution,
                          kick_ticks=kick_ticks) if pat else []
    diag = {
        "onsets": len(kick_ticks) if kick_ticks is not None else 0,
        "separator": "—",
        "transcriber": f"pattern:{pat.name}" if pat else "pattern:none",
        "warnings": ([f"{n_bars} bars × '{pat.name}'" if pat else "no pattern"] + warnings)[:12],
    }
    return notes, diag


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
