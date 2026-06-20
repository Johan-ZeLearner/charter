"""``charter`` CLI — the symbolic-backend entry point (Phase 2, docs/10).

Subcommands:
  midi2chart <input.mid> <out_folder>   GM-drum MIDI -> Clone Hero song folder
  validate   <song_folder>              run the scan-chart gate, assert 4-lane Pro

Run as: ``python -m charter.cli ...``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .drumnote import Difficulty, Song, SongMeta
from .mapping import MapConfig, load_drum_midi, map_events
from .validate import ValidationUnavailable, assert_four_lane_pro


def _cmd_midi2chart(args: argparse.Namespace) -> int:
    events, tempo_map = load_drum_midi(args.input)
    if not events:
        print("warning: no drum notes found (is the MIDI on GM channel 10?)", file=sys.stderr)
    result = map_events(events, tempo_map, MapConfig())

    song_length_ms = 0
    if result.notes:
        last_tick = max(n.tick for n in result.notes)
        song_length_ms = int(tempo_map.tick_to_seconds(last_tick) * 1000)

    meta = SongMeta(
        name=args.name,
        artist=args.artist,
        charter=args.charter,
        song_length_ms=song_length_ms,
    )
    song = Song(
        meta=meta,
        tempo_map=tempo_map,
        tracks={Difficulty.EXPERT: result.notes},
    )
    folder = song.write_folder(args.out, audio_path=args.audio)

    print(f"wrote {folder}/notes.chart  ({len(result.notes)} expert notes)")
    if result.warnings:
        print(f"{len(result.warnings)} review note(s):")
        for w in result.warnings:
            print(f"  - {w}")
    if args.validate:
        return _validate(folder)
    return 0


def _cmd_mp3tochart(args: argparse.Namespace) -> int:
    from .audio.pipeline import mp3_to_chart_folder

    folder, diag = mp3_to_chart_folder(
        args.input,
        args.out,
        name=args.name,
        artist=args.artist,
        charter=args.charter,
        encode_audio=not args.no_audio,
    )
    print(
        f"wrote {folder}  [{diag.gate}]  "
        f"sep={diag.separator} beats={diag.beat_tracker} adt={diag.transcriber}"
    )
    print(
        f"  ~{diag.bpm:.1f} BPM, {diag.beats} beats, {diag.onsets} onsets "
        f"-> {diag.notes} notes  (drum RMS {diag.drum_rms:.4f})"
    )
    if diag.gate == "REFUSE":
        print("  REFUSE: drums too quiet/buried — output is likely unusable.")
    for w in diag.warnings[:8]:
        print(f"  - {w}")
    if args.validate:
        return _validate(folder)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    return _validate(args.folder)


def _validate(folder: str | Path) -> int:
    try:
        verdict = assert_four_lane_pro(folder)
    except ValidationUnavailable as e:
        print(f"validation unavailable: {e}", file=sys.stderr)
        return 3
    counts = ", ".join(
        f"{c['difficulty']}={c['count']}"
        for c in verdict.report.get("noteCounts", [])
        if c.get("instrument") == "drums"
    )
    print(f"drumType={verdict.report.get('drumTypeName')}  playable={verdict.report.get('playable')}  drums[{counts}]")
    if verdict.advisories:
        print(f"{len(verdict.advisories)} advisory(ies) (non-blocking):")
        for a in verdict.advisories:
            print(f"  · {a}")
    if verdict.ok:
        print("PASS: Clone Hero accepts this as 4-lane Pro.")
        return 0
    print("FAIL:")
    for r in verdict.reasons:
        print(f"  - {r}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="charter", description="mp3 -> Clone Hero drums (symbolic backend)")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("midi2chart", help="GM-drum MIDI -> Clone Hero song folder")
    m.add_argument("input", help="input GM-drum .mid file")
    m.add_argument("out", help="output song folder")
    m.add_argument("--name", default="Untitled")
    m.add_argument("--artist", default="Unknown Artist")
    m.add_argument("--charter", default="charter AI")
    m.add_argument("--audio", default=None, help="optional audio file to copy as song.<ext>")
    m.add_argument("--validate", action="store_true", help="run scan-chart after writing")
    m.set_defaults(func=_cmd_midi2chart)

    a = sub.add_parser("mp3tochart", help="audio file -> playable Clone Hero song folder")
    a.add_argument("input", help="input audio file (mp3/wav/flac/...)")
    a.add_argument("out", help="output song folder")
    a.add_argument("--name", default=None)
    a.add_argument("--artist", default=None)
    a.add_argument("--charter", default="charter AI")
    a.add_argument("--no-audio", action="store_true", help="skip song.opus encoding")
    a.add_argument("--validate", action="store_true", help="run scan-chart after writing")
    a.set_defaults(func=_cmd_mp3tochart)

    v = sub.add_parser("validate", help="run the scan-chart gate on a song folder")
    v.add_argument("folder", help="song folder to validate")
    v.set_defaults(func=_cmd_validate)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
