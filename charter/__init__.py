"""charter — mp3 -> playable Clone Hero drums.

This package is the symbolic backend (Stages 6-8 of the pipeline): it converts
GM-drum MIDI into a Clone Hero 4-lane Pro Drums ``.chart`` and validates it
against Clone Hero's own parser via scan-chart.

See ``docs/`` for the design. The format firewall lives in :mod:`charter.drumnote`;
the GM->CH mapping in :mod:`charter.mapping`.
"""

__version__ = "0.1.0"
