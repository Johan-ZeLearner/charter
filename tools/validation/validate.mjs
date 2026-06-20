#!/usr/bin/env node
// The canonical Clone Hero acceptance gate (docs/03 §10, docs/09).
//
// Runs Geomitron/scan-chart (which byte-matches CH's own parser, validated on
// 40k charts) over a song folder and prints a compact JSON report on stdout.
// The Python side (charter/validate.py) decides pass/fail; this just reports.
//
// Usage: node validate.mjs <songFolder>
// Requires Node >= 24.

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { scanChartFolder, drumTypes } from 'scan-chart';

const folder = process.argv[2];
if (!folder) {
  console.error('usage: node validate.mjs <songFolder>');
  process.exit(2);
}

function drumTypeName(value) {
  if (value == null) return null;
  const entry = Object.entries(drumTypes).find(([, v]) => v === value);
  return entry ? entry[0] : String(value);
}

try {
  const files = readdirSync(folder)
    .filter((name) => statSync(join(folder, name)).isFile())
    .map((fileName) => ({
      fileName,
      data: new Uint8Array(readFileSync(join(folder, fileName))),
    }));

  const result = scanChartFolder(files, { includeBTrack: false });
  const nd = result.notesData;

  const report = {
    playable: result.playable,
    chartHash: result.chartHash ?? null,
    drumType: nd ? nd.drumType : null,
    drumTypeName: nd ? drumTypeName(nd.drumType) : null,
    fourLaneProValue: drumTypes.fourLanePro,
    instruments: nd ? nd.instruments : [],
    has2xKick: nd ? nd.has2xKick : false,
    noteCounts: nd ? nd.noteCounts : [],
    chartIssues: nd ? nd.chartIssues : [],
    folderIssues: result.folderIssues ?? [],
    metadataIssues: result.metadataIssues ?? [],
  };

  process.stdout.write(JSON.stringify(report, null, 2));
  process.exit(0);
} catch (err) {
  console.error('scan-chart failed:', err && err.stack ? err.stack : String(err));
  process.exit(1);
}
