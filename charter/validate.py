"""Python bridge to the scan-chart validation gate (docs/09).

Shells out to the Node ``tools/validation/validate.mjs`` subprocess and turns its
JSON report into a pass/fail verdict. The Python side never parses charts itself
(docs/08 §6, service boundary 2) — scan-chart is the single source of truth for
"will Clone Hero accept this and detect 4-lane Pro".
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VALIDATOR = _REPO_ROOT / "tools" / "validation" / "validate.mjs"
_NODE_MODULES = _REPO_ROOT / "tools" / "validation" / "node_modules"


class ValidationUnavailable(RuntimeError):
    """Raised when Node or the scan-chart install is missing."""


# scan-chart reports many "issues" that are authoring-quality advisories which
# Clone Hero still loads and plays fine (no practice sections, a note within 2s
# of the start, no star power, no audio yet, missing album/year metadata, etc.).
# Only a curated set genuinely means "broken / won't parse correctly". The gate
# fails on those; everything else is surfaced as an advisory for REVIEW.md.
_BLOCKING_CHART_ISSUES = frozenset(
    {
        "noNotes",
        "noExpert",
        "misalignedTimeSignature",
        "badEndEvent",
        "difficultyForbiddenNote",
        "invalidChord",
        "brokenNote",
    }
)
_BLOCKING_FOLDER_ISSUES = frozenset(
    {"noChart", "invalidChart", "badChart", "noMetadata", "invalidIni", "invalidMetadata"}
)


@dataclass
class Verdict:
    ok: bool
    report: dict
    reasons: list[str]  # blocking — why the chart is NOT accepted
    advisories: list[str]  # non-blocking quality notes (feed REVIEW.md later)


def scan_unavailable_reason() -> str | None:
    """Return why validation can't run, or None if it can."""
    if shutil.which("node") is None:
        return "node executable not found on PATH (need Node >= 24)"
    if not _VALIDATOR.exists():
        return f"validator script missing: {_VALIDATOR}"
    if not _NODE_MODULES.exists():
        return "scan-chart not installed (run `npm install` in tools/validation)"
    return None


def scan_chart_folder(folder: str | Path) -> dict:
    """Run scan-chart on ``folder`` and return its JSON report."""
    reason = scan_unavailable_reason()
    if reason is not None:
        raise ValidationUnavailable(reason)
    proc = subprocess.run(
        ["node", str(_VALIDATOR), str(folder)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"scan-chart failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def assert_four_lane_pro(folder: str | Path) -> Verdict:
    """The Phase-1/2 gate: Clone Hero parses the chart and detects it as 4-lane Pro.

    Blocking: drumType != fourLanePro, no drums instrument, zero notes, or a
    genuinely-broken chart/folder issue. Authoring-quality advisories (no audio
    yet, no practice sections, etc.) are reported but do not fail the gate.
    """
    report = scan_chart_folder(folder)
    reasons: list[str] = []
    advisories: list[str] = []

    if report.get("drumType") != report.get("fourLaneProValue"):
        reasons.append(
            f"drumType is {report.get('drumTypeName')!r}, expected 'fourLanePro'"
        )
    if "drums" not in (report.get("instruments") or []):
        reasons.append("no 'drums' instrument detected")

    drum_counts = [
        c for c in report.get("noteCounts", []) if c.get("instrument") == "drums"
    ]
    if not any(c.get("count", 0) > 0 for c in drum_counts):
        reasons.append("zero drum notes counted")

    for issue in report.get("chartIssues", []):
        desc = issue.get("description", issue.get("noteIssue", "?"))
        if issue.get("noteIssue") in _BLOCKING_CHART_ISSUES:
            reasons.append(f"chart issue: {desc}")
        else:
            advisories.append(f"chart: {desc}")
    for issue in report.get("folderIssues", []):
        desc = issue.get("description", issue.get("folderIssue", "?"))
        if issue.get("folderIssue") in _BLOCKING_FOLDER_ISSUES:
            reasons.append(f"folder issue: {desc}")
        else:
            advisories.append(f"folder: {desc}")
    for issue in report.get("metadataIssues", []):
        advisories.append(f"metadata: {issue.get('description', '?')}")

    return Verdict(ok=not reasons, report=report, reasons=reasons, advisories=advisories)
