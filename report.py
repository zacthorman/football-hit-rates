"""
Render a fixture's hit-rate data as a single self-contained HTML file.

Everything is inlined, so the file works offline, opens anywhere, and can be
emailed. The match data is embedded as JSON and the filtering happens in the
browser, so switching fixture, period, venue or sample size is instant.

Layout is head to head: each stat is one row with the two teams facing each
other around the stat name, so the comparison you actually care about is a
single glance rather than a scan across two distant columns. On a narrow
screen the same row stacks into a card.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import markets

CSS = """
:root {
  color-scheme: light;
  --surface-1: #fcfcfb;
  --page: #f9f9f7;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --muted: #898781;
  --grid: #e1e0d9;
  --baseline: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --tint: rgba(11,11,11,0.035);
  --track: #e8e7e1;
  --team-1: #2a78d6;
  --team-2: #eb6834;
  --control-bg: #ffffff;
  --control-active: #0b0b0b;
  --control-active-text: #ffffff;
  /* Status pair, fixed in both modes. Both clear 3:1 on either surface. */
  --hit: #0ca30c;
  --miss: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --surface-1: #1a1a19;
    --page: #0d0d0d;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --baseline: #383835;
    --border: rgba(255,255,255,0.10);
    --tint: rgba(255,255,255,0.045);
    --track: #2c2c2a;
    --team-1: #3987e5;
    --team-2: #d95926;
    --control-bg: #222220;
    --control-active: #ffffff;
    --control-active-text: #0b0b0b;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1: #1a1a19;
  --page: #0d0d0d;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --muted: #898781;
  --grid: #2c2c2a;
  --baseline: #383835;
  --border: rgba(255,255,255,0.10);
  --tint: rgba(255,255,255,0.045);
  --track: #2c2c2a;
  --team-1: #3987e5;
  --team-2: #d95926;
  --control-bg: #222220;
  --control-active: #ffffff;
  --control-active-text: #0b0b0b;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 28px 18px 72px;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px;
  line-height: 1.5;
  -webkit-text-size-adjust: 100%;
}

.wrap { max-width: 1180px; margin: 0 auto; }

/* ------------------------------------------------------------- header */

header { margin-bottom: 18px; }

.competition {
  font-size: 12px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 6px;
}
h1 { font-size: 30px; font-weight: 680; margin: 0 0 5px; letter-spacing: -0.015em; }
.kickoff { color: var(--text-secondary); font-size: 14px; }
/* Sticky, not just placed at the top. A report runs to thousands of rows, so
   a back link that scrolls away is a back link you do not have. On a phone
   that meant reaching for the browser's own back button every time.

   It sits as a direct child of .wrap rather than inside <header>, because a
   sticky element only sticks while its own parent is still on screen. Inside
   the header it unstuck the instant the title scrolled past, which looked
   exactly like sticky not working at all. */
.back-bar {
  position: sticky; top: 0; z-index: 20;
  background: var(--page); padding: 10px 0 10px;
  margin: -10px 0 12px;
}
.back {
  display: inline-flex; align-items: center; gap: 7px;
  color: var(--text-primary); text-decoration: none;
  font-size: 15px; font-weight: 640;
  border: 1px solid var(--border); background: var(--surface-1);
  border-radius: 9px; padding: 9px 15px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.07);
}
.back:hover { background: var(--tint); }
.back:active { transform: translateY(1px); }

/* ----------------------------------------------------------- controls */

.controls {
  display: flex; flex-wrap: wrap; gap: 14px 22px; align-items: center;
  padding: 13px 16px; margin-bottom: 8px;
  background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px;
}
.controls + .controls { margin-bottom: 20px; }

.control-group { display: flex; align-items: center; gap: 8px; }

.control-label {
  font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase;
  color: var(--muted); white-space: nowrap;
}

.seg { display: flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button {
  border: 0; background: var(--control-bg); color: var(--text-secondary);
  font: inherit; font-size: 13px; padding: 6px 13px; cursor: pointer;
  white-space: nowrap;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button:disabled { opacity: 0.4; cursor: not-allowed; }
.seg button[aria-pressed="true"] {
  background: var(--control-active); color: var(--control-active-text); font-weight: 620;
}

.legend { display: flex; gap: 18px; margin-left: auto; align-items: center; }
.legend-item {
  display: flex; align-items: center; gap: 7px;
  font-size: 14px; font-weight: 600; color: var(--text-primary);
}
.swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }

select, .num-input {
  height: 32px; border: 1px solid var(--border);
  background: var(--control-bg); color: var(--text-primary);
  border-radius: 8px; font: inherit; font-size: 14px; padding: 0 8px;
}
.num-input {
  width: 60px; text-align: center; font-variant-numeric: tabular-nums;
}

/* --------------------------------------------------------------- tabs */

.tabs { display: flex; gap: 5px; margin-bottom: 16px; }
.tabs button {
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary);
  font: inherit; font-size: 15px; font-weight: 600;
  padding: 9px 20px; border-radius: 9px; cursor: pointer;
}
.tabs button[aria-selected="true"] {
  background: var(--control-active); color: var(--control-active-text);
  border-color: var(--control-active);
}
.panel[hidden] { display: none; }

/* ----------------------------------------------------- head to head */

.board {
  background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 12px; overflow: hidden;
}

.stat-row {
  display: grid;
  grid-template-columns: 1fr 210px 1fr;
  gap: 20px;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--grid);
}
.stat-row:last-child { border-bottom: 0; }
.stat-row.strong { background: var(--tint); }

/* One team at a time: the middle column leads, the single side gets the rest
   of the width, and everything reads left to right like a normal table. */
.stat-row.solo { grid-template-columns: 230px 1fr; }
.stat-row.solo .middle { order: 1; text-align: left; }
.stat-row.solo .stepper { justify-content: flex-start; }
.stat-row.solo .side { order: 2; flex-direction: row; }
.stat-row.solo .side.a .figure { text-align: left; }
.stat-row.solo .side.a .bar { justify-content: flex-start; }

.middle { text-align: center; order: 2; }
.stat-label {
  font-size: 15px; font-weight: 620; margin-bottom: 6px; line-height: 1.25;
}
.stepper { display: flex; align-items: center; justify-content: center; gap: 4px; }
.stepper button {
  width: 28px; height: 28px;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary); border-radius: 7px;
  font: inherit; font-size: 16px; line-height: 1; cursor: pointer; padding: 0;
}
.stepper button:hover { color: var(--text-primary); }
.stepper input {
  width: 62px; height: 28px;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-primary); border-radius: 7px;
  font: inherit; font-size: 14px; font-variant-numeric: tabular-nums;
  text-align: center; padding: 0 2px;
}
.stepper input.edited { border-color: var(--text-primary); font-weight: 660; }
.stepper input::-webkit-outer-spin-button,
.stepper input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.stepper input[type=number] { -moz-appearance: textfield; }

.side { display: flex; align-items: center; gap: 14px; min-width: 0; }
.side.a { order: 1; flex-direction: row-reverse; }
.side.b { order: 3; }

.team-tag {
  display: none;
  align-items: center; gap: 7px;
  font-size: 13px; font-weight: 620; color: var(--text-secondary);
}

.figure { flex: none; min-width: 96px; }
.side.a .figure { text-align: right; }

.pct {
  font-size: 24px; font-weight: 700; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; line-height: 1.1;
}
.stat-row.strong .pct { font-size: 26px; }
.frac { font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }

.bar { height: 7px; border-radius: 4px; background: var(--track);
       margin-top: 7px; overflow: hidden; display: flex; }
.side.a .bar { justify-content: flex-end; }
.fill { height: 100%; border-radius: 4px; }

.spark { flex: none; }
.seq {
  font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums; white-space: nowrap; min-width: 0;
  overflow: hidden; text-overflow: ellipsis;
}

.empty { color: var(--muted); font-size: 14px; }

/* ------------------------------------------------------------ players */

.team-block { margin-bottom: 26px; }
.team-title {
  display: flex; align-items: center; gap: 9px;
  font-size: 17px; font-weight: 680; margin: 0 0 10px;
}

.ptable { width: 100%; border-collapse: collapse; }
.ptable thead th {
  text-align: left; font-size: 11px; letter-spacing: 0.07em;
  text-transform: uppercase; color: var(--muted); font-weight: 620;
  padding: 12px 16px; border-bottom: 1px solid var(--grid); white-space: nowrap;
}
.ptable tbody td {
  padding: 13px 16px; border-bottom: 1px solid var(--grid); vertical-align: middle;
}
.ptable tbody tr:last-child td { border-bottom: 0; }
.ptable tbody tr.strong { background: var(--tint); }
.player-name { font-weight: 620; white-space: nowrap; font-size: 15px; }
.pos { color: var(--muted); font-size: 12px; margin-left: 7px; font-weight: 500; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--text-secondary); }
.pcell { display: flex; align-items: center; gap: 14px; }

.note { color: var(--muted); font-size: 13.5px; margin: 0 0 14px; }
.caution {
  border: 1px solid var(--border); border-left: 3px solid var(--miss);
  background: var(--surface-1); border-radius: 10px;
  padding: 13px 16px; margin: 0 0 16px;
  font-size: 13.5px; color: var(--text-secondary);
}
.caution strong { color: var(--text-primary); }
.warn {
  border: 1px solid var(--border); border-left: 3px solid var(--miss);
  background: var(--surface-1); border-radius: 10px;
  padding: 12px 15px; margin: 0 0 14px;
  font-size: 13.5px; color: var(--text-secondary);
}
.warn strong { color: var(--text-primary); }
.pill {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 11.5px; font-weight: 620; letter-spacing: 0.02em;
  border: 1px solid var(--border); color: var(--text-secondary);
  white-space: nowrap;
}
.dir { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.odds { font-variant-numeric: tabular-nums; font-weight: 620; white-space: nowrap; }
.odds-min { font-size: 17px; }
.price-input {
  width: 72px; height: 30px; text-align: center;
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-primary); border-radius: 7px;
  font: inherit; font-size: 14px; font-variant-numeric: tabular-nums;
}
.price-input::-webkit-outer-spin-button,
.price-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.verdict { font-weight: 660; white-space: nowrap; font-size: 14px; }
.verdict.yes { color: var(--hit); }
.verdict.thin { color: var(--text-secondary); }
.verdict.no { color: var(--miss); }
.sub-line { color: var(--muted); font-size: 12px; font-weight: 500; display: block; }
.score { font-size: 26px; font-weight: 720; font-variant-numeric: tabular-nums; line-height: 1; }
.score.good { color: var(--hit); }
.score.poor { color: var(--miss); }
.breakdown { font-size: 12px; color: var(--muted); margin-top: 5px; }
.breakdown span { white-space: nowrap; margin-right: 10px; }
.add-btn {
  border: 1px solid var(--border); background: var(--control-bg);
  color: var(--text-secondary); border-radius: 7px;
  font: inherit; font-size: 12.5px; padding: 5px 10px; cursor: pointer;
  white-space: nowrap;
}
.add-btn:hover { color: var(--text-primary); }
.add-btn[data-in="1"] { background: var(--control-active); color: var(--control-active-text); }
.totals {
  display: flex; flex-wrap: wrap; gap: 26px;
  padding: 16px 18px; margin-bottom: 16px;
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
}
.total-item .k {
  font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--muted);
}
.total-item .v { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
.proj {
  margin-top: 7px; font-size: 12.5px; color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.proj b { font-weight: 680; color: var(--text-primary); }
.proj.conflict { color: var(--miss); }
/* Dotted underline on an estimate, so it never reads as the fitted number.
   Hover gives the matches it came from. */
.proj.est { border-bottom: 1px dotted var(--border); display: inline-block; }
.proj.est b { font-weight: 600; }
.chance { font-variant-numeric: tabular-nums; color: var(--muted); white-space: nowrap; }

/* ---------------------------------------------------------- best bets */
.comp-head {
  margin: 20px 0 10px; font-size: 13px; font-weight: 640;
  letter-spacing: 0.05em; text-transform: uppercase; color: var(--text-secondary);
}
.comp-head .pos { text-transform: none; letter-spacing: 0; }

.pick {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; margin-bottom: 10px;
}
.pick-line { font-size: 17px; font-weight: 640; letter-spacing: -0.01em; }
.pick-fixture { color: var(--muted); font-size: 13px; margin-top: 1px; }

.pick-halves {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0 10px;
}
@media (max-width: 620px) { .pick-halves { grid-template-columns: 1fr; } }

.half {
  background: var(--tint); border-radius: 9px; padding: 9px 11px;
  display: grid; grid-template-columns: 1fr auto; gap: 2px 8px; align-items: baseline;
}
.half-label { font-size: 12.5px; color: var(--text-secondary); }
.half-num {
  font-variant-numeric: tabular-nums; font-weight: 660; font-size: 15px;
  justify-self: end;
}
.half .bar { grid-column: 1 / -1; margin: 3px 0 1px; }
.half .seq {
  grid-column: 1 / -1; font-size: 11.5px; color: var(--muted);
  font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap;
}

.pick-foot {
  display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center;
  font-size: 13px; color: var(--text-secondary);
  border-top: 1px solid var(--grid); padding-top: 10px;
}
.pick-foot b { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.pick-foot .add-btn { margin-left: auto; }
.need-cell { display: inline-flex; align-items: baseline; gap: 5px; }
.src {
  font-size: 10.5px; font-weight: 600; color: var(--muted);
  border: 1px solid var(--border); border-radius: 5px; padding: 0 5px;
  white-space: nowrap;
}
.src.warnsrc { color: var(--miss); border-color: var(--miss); }
.agree { font-size: 12.5px; }
.agree.yes { color: var(--hit); }
.agree.no  { color: var(--miss); }

.tooltip {
  position: fixed; pointer-events: none;
  background: var(--text-primary); color: var(--surface-1);
  padding: 7px 10px; border-radius: 7px;
  font-size: 12.5px; line-height: 1.4;
  opacity: 0; transition: opacity 0.1s; z-index: 10; white-space: nowrap;
}

footer { margin-top: 22px; color: var(--muted); font-size: 13px; }

/* -------------------------------------------------------------- narrow */

@media (max-width: 900px) {
  .seq { display: none; }
  .stat-row { grid-template-columns: 1fr 170px 1fr; gap: 12px; padding: 14px; }
  .figure { min-width: 78px; }
}

@media (max-width: 660px) {
  body { padding: 20px 12px 60px; font-size: 16px; }
  h1 { font-size: 24px; }
  .legend { display: none; }

  .stat-row { grid-template-columns: 1fr; gap: 12px; padding: 16px 14px; }
  .middle {
    order: 0; text-align: left;
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
  }
  .stat-label { margin-bottom: 0; font-size: 16px; }

  .side.a, .side.b { order: 1; flex-direction: row; gap: 12px; }
  .side.a .figure { text-align: left; }
  .side.a .bar { justify-content: flex-start; }

  .team-tag { display: flex; flex: none; min-width: 84px; }
  .figure { min-width: 74px; }
  .pct { font-size: 22px; }

  .ptable thead { display: none; }
  .ptable tbody td { display: block; padding: 4px 14px; border: 0; }
  .ptable tbody td:first-child { padding-top: 14px; }
  .ptable tbody td:last-child { padding-bottom: 14px; border-bottom: 1px solid var(--grid); }
  .ptable .num::before { content: attr(data-label) ": "; color: var(--muted); }
}
"""

JS = """
const ALL = __PAYLOAD__;

let DATA = ALL.fixtures[0];
let SUGGESTED = {};
let SUGGESTED_H2H = {};

let games = 10;
let venue = "all";
let tier  = "all";
let tab = "team";
let period = "ALL";
let scope = "core";
let sort = "default";
let strongOnly = false;
let source = "form";      // "form" = recent matches, "h2h" = previous meetings
let measure = "for";      // "for" | "against" | "matchup"
let showPast = false;
let includeMismatched = false;
let focus = "both";   // "both" | "0" | "1"

// A hit rate this far from an even split is worth your attention. Below it,
// ten matches simply cannot separate signal from noise.
const STRONG_HIGH = 80;
const STRONG_LOW = 20;

/* The markets worth leading with. "All" still shows everything that came
   through, which is now only the bettable set unless the report was built
   with --all-stats. */
const CORE_STATS = [
  "Goals", "Total shots", "Shots on target", "Corner kicks",
  "Fouls", "Tackles", "Offsides", "Throw-ins", "Yellow cards",
];

const VARS = ["--team-1", "--team-2"];
const boardEl = document.getElementById("board");

const tip = document.createElement("div");
tip.className = "tooltip";
document.body.appendChild(tip);

/* Lines are always quoted at .5 so a match can never land exactly on one.
   Stepping moves a whole unit: 13.5 to 14.5, not 13.5 to 14. */
function snapLine(value) {
  return Math.max(0.5, Math.round(value - 0.5) + 0.5);
}

function hasH2H() {
  return Array.isArray(DATA.h2h) && DATA.h2h.some(r => r.length);
}

/* Head to head reuses the whole rendering path: same record shape, same
   filters, just a different set of matches and its own lines. Two teams
   meeting each other produce different numbers from their form against
   everyone else, so the suggested lines cannot be shared. */
function activeRecords() {
  return source === "h2h" && hasH2H() ? DATA.h2h : DATA.records;
}

function activeLines() {
  const bucket = source === "h2h" && hasH2H() ? DATA.h2hLines : DATA.lines;
  return (bucket || {})[period] || {};
}

function activeStats() {
  const bucket = source === "h2h" && hasH2H() ? DATA.h2hStats : DATA.stats;
  return (bucket || {})[period] || [];
}

/* Standard of opposition. A club missing from last season's tables came up
   from a lower division, so it counts as bottom rather than unknown: putting
   it in mid-table by accident is the mistake this whole feature exists to
   stop. */
function tierOf(opponentId) {
  const map = (DATA.tiers || {}).map || {};
  return map[String(opponentId)] || "bottom";
}

function filtered(records) {
  let rows = records;
  if (venue !== "all") rows = rows.filter(r => r.venue === venue);
  if (tier !== "all" && DATA.tiers) {
    rows = rows.filter(r => tierOf(r.opponent_id) === tier);
  }
  return rows.slice(-games);
}

function hasPlayers() {
  return Array.isArray(DATA.players) && DATA.players.some(r => r.length);
}

/* Team records store stats as {period: {name: value}}. Player records are
   flat, because SofaScore only reports player numbers for the whole match.

   Every record also carries an `against` block: what the opposition managed
   in that match. It comes from the same payload at no extra cost, and it is
   what lets you ask the question that actually matters, which is whether one
   team's attack meets the other team's leak. */
function bucketFor(index) {
  if (measure === "for") return "stats";
  if (measure === "against") return "against";
  return index === 0 ? "stats" : "against";   // matchup
}

function statValue(record, statName, which) {
  const key = which || "stats";
  const block = record[key];
  // No silent fallback. An older report has no `against` block, and quietly
  // showing the `for` numbers in its place would be indistinguishable from
  // real data, which is worse than showing nothing.
  if (!block) return undefined;
  const bucket = block[period] || block;
  return bucket ? bucket[statName] : undefined;
}

function hasAgainst() {
  return DATA.records.some(rows => rows.some(r => r.against));
}

/* A team promoted, relegated, or arriving from a cup run carries a record
   built against different opposition. Coventry putting up 12 shots a game in
   the Championship says very little about Coventry away at Arsenal, but the
   hit rate looks identical either way, which is how a 100% record turns into
   a losing bet. This does not adjust for it, because doing that honestly
   needs a model. It flags it, so the number is read with the right amount of
   suspicion. */
function sampleMix(teamIndex) {
  const rows = filtered(activeRecords()[teamIndex]);
  const counts = {};
  rows.forEach(r => {
    const c = r.competition || "?";
    counts[c] = (counts[c] || 0) + 1;
  });
  const fixtureComp = DATA.fixture.competition;
  const matching = counts[fixtureComp] || 0;
  return {
    total: rows.length,
    matching,
    counts,
    mismatched: rows.length > 0 && matching / rows.length < 0.6,
  };
}

function mismatchWarning() {
  const notes = [];
  DATA.records.forEach((rows, i) => {
    const mix = sampleMix(i);
    if (!mix.mismatched) return;
    const where = Object.entries(mix.counts)
      .sort((a, b) => b[1] - a[1])
      .map(([c, n]) => `${n} in ${c}`)
      .join(", ");
    notes.push(`<strong>${DATA.teams[i].name}</strong>: ${where}`);
  });

  if (!notes.length) return "";

  return `<div class="warn">
    <strong>Different opposition.</strong> These figures were not built against
    the standard of side they face here: ${notes.join("; ")}.
    A record set in another competition can be perfectly true and still a poor
    guide, because the hit rate carries no memory of who it was set against.
    Treat anything at 90% or 100% here with real suspicion.
  </div>`;
}

/* Why a projection is missing. The opponent-adjusted model can only rate a
   team against opponents it has also rated, so a promoted club with ten
   Championship matches on file has almost nothing usable. Left unsaid, that
   showed up as Coventry projected for more corners at the Emirates than
   Arsenal, off a single match. Saying it out loud is the fix. */
function ratingsWarning() {
  const notes = DATA.ratingNotes || [];
  if (!notes.length) return "";
  const tp = DATA.tierProjection;
  const fallback = tp
    ? ` Instead, the <b>est</b> figures come from ${DATA.tierProjectionFrom}'s
        own record against bottom-tier sides: ${tp.matches}
        match${tp.matches === 1 ? "" : "es"}${tp.venue ? ` at ${tp.venue}` : ""}
        against ${tp.opponents.join(", ")}. That uses no data at all from the
        promoted side, which is the point, because their data is the part
        that does not carry across divisions. Hover any estimate to see the
        matches behind it.`
    : "";

  return `<div class="warn">
    <strong>No adjusted projection.</strong> ${notes.join("; ")}.
    The raw hit rates below are still real, but nothing has corrected them
    for the standard of opposition, so read them as what happened rather
    than what to expect.${fallback}
  </div>`;
}

function summarise(rows, statName, line, which) {
  const vals = rows.map(r => statValue(r, statName, which))
                   .filter(v => v !== undefined && v !== null);
  if (!vals.length) return null;
  const hits = vals.filter(v => v > line).length;
  return { vals, hits, pct: Math.round((hits / vals.length) * 100) };
}

function sparkline(rows, statName, line, colorVar, which) {
  const points = rows
    .map(r => ({ v: statValue(r, statName, which), r }))
    .filter(p => p.v !== undefined && p.v !== null);

  if (points.length < 2) return "";

  const W = 116, H = 38, PAD = 6;
  const vals = points.map(p => p.v).concat([line]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = (hi - lo) || 1;

  const x = i => PAD + (i * (W - 2 * PAD)) / (points.length - 1);
  const y = v => H - PAD - ((v - lo) / span) * (H - 2 * PAD);

  const path = points.map((p, i) => `${x(i)},${y(p.v)}`).join(" ");

  /* Dots carry hit or miss against the line, so you can count them without
     doing arithmetic. Colour is not doing that job alone: a hit is a filled
     dot above the dashed line, a miss is a hollow one below it. That keeps
     it readable in greyscale and for red-green colour blindness, which this
     pair is exactly the wrong choice for on its own. The polyline stays in
     the team's colour, so identity is still carried. */
  const dots = points.map((p, i) => {
    const hit = p.v > line;
    const comp = p.r.competition ? ` &middot; ${p.r.competition}` : "";
    const tipText = `${p.r.date} ${p.r.venue === 'home' ? 'H' : 'A'} v ${p.r.opponent}`
      + ` &middot; ${p.v} &middot; ${hit ? 'over' : 'under'} ${line}${comp}`;
    return hit
      ? `<circle cx="${x(i)}" cy="${y(p.v)}" r="4" fill="var(--hit)"
           stroke="var(--surface-1)" stroke-width="1.5"
           data-tip="${tipText}"></circle>`
      : `<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" fill="var(--surface-1)"
           stroke="var(--miss)" stroke-width="2"
           data-tip="${tipText}"></circle>`;
  }).join("");

  return `<svg class="spark" width="${W}" height="${H}" role="img"
      aria-label="${statName}, oldest to newest">
    <line x1="0" y1="${y(line)}" x2="${W}" y2="${y(line)}"
      stroke="var(--baseline)" stroke-width="1" stroke-dasharray="3 3"></line>
    <polyline points="${path}" fill="none" stroke="var(${colorVar})"
      stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline>
    ${dots}
  </svg>`;
}

function sideHtml(rows, statName, line, index) {
  const letter = index === 0 ? "a" : "b";
  const colorVar = VARS[index];
  const which = bucketFor(index);
  const suffix = measure === "for" ? ""
    : (which === "against" ? " conceded" : " for");
  const tag = `<span class="team-tag">
      <span class="swatch" style="background:var(${colorVar})"></span>
      ${DATA.teams[index].name}${suffix}
    </span>`;

  const s = summarise(rows, statName, line, which);
  if (!s) {
    return `<div class="side ${letter}">${tag}
      <span class="empty">no data</span></div>`;
  }

  const seq = s.vals.map(v => (Number.isInteger(v) ? v : v.toFixed(1))).join(", ");

  return `<div class="side ${letter}">
    ${tag}
    <div class="figure">
      <div><span class="pct">${s.pct}%</span>
           <span class="frac">${s.hits}/${s.vals.length}</span></div>
      <div class="bar"><div class="fill"
        style="width:${s.pct}%;background:var(${colorVar})"></div></div>
    </div>
    ${sparkline(rows, statName, line, colorVar, which)}
    <span class="seq">${seq}</span>
  </div>`;
}

/* The projection answers the question a hit rate cannot: what should this
   team actually do in THIS fixture, against THIS opponent. It comes from the
   fitted attack and defence ratings, so a promoted side's flattering record
   gets discounted by the quality of who they are about to play.

   Flagged in red when the projection lands on the opposite side of the line
   from the record, because that is exactly the case worth catching: a true
   100% that the model expects to fail. */
function projectionHtml(name, line) {
  let proj = (DATA.projection || {})[period];
  let fromTier = false;

  // No fitted projection means one side could not be rated, which in
  // practice means they are promoted. Fall back to what the rated side does
  // to teams of that standard. Only the full match is available that way,
  // because the tier record is kept whole rather than split by half.
  if ((!proj || !proj[name]) && DATA.tierProjection && period === "ALL") {
    proj = DATA.tierProjection.stats;
    fromTier = true;
  }

  if (!proj || !proj[name] || line === undefined) return "";

  const values = proj[name];
  const teamRows = activeRecords().map(filtered);
  const shown = focusedIndexes();
  let conflict = false;

  shown.forEach(i => {
    const value = values[i];
    const s = summarise(teamRows[i], name, line, bucketFor(i));
    if (!s || value === undefined) return;
    const recordSaysOver = s.pct >= 60;
    const recordSaysUnder = s.pct <= 40;
    if ((recordSaysOver && value < line) || (recordSaysUnder && value > line)) {
      conflict = true;
    }
  });

  const text = shown.length === 1
    ? `<b>${values[shown[0]]}</b>`
    : `<b>${values[0]}</b> v <b>${values[1]}</b>`;

  const tp = DATA.tierProjection;
  const label = fromTier ? "est" : "proj";
  const why = fromTier
    ? `${DATA.tierProjectionFrom} against bottom-tier sides, `
      + `${tp.matches} match${tp.matches === 1 ? "" : "es"}`
      + (tp.venue ? ` at ${tp.venue}` : ", home and away")
      + `: ${tp.opponents.join(", ")}`
    : "Expected in this fixture, from opponent-adjusted ratings";

  return `<div class="proj${conflict ? " conflict" : ""}${fromTier ? " est" : ""}"
    title="${why}">
    ${label} ${text}${conflict ? " (record disagrees)" : ""}</div>`;
}

function visibleStats() {
  const lines = activeLines();
  let stats = activeStats().filter(n => lines[n] !== undefined);

  if (scope === "core") {
    const core = stats.filter(n => CORE_STATS.includes(n));
    if (core.length) stats = core;
  }

  const teamRows = activeRecords().map(filtered);

  const strength = name => {
    const line = lines[name];
    return Math.max(...teamRows.map((rows, i) => {
      const s = summarise(rows, name, line, bucketFor(i));
      return s ? Math.abs(s.pct - 50) : 0;
    }));
  };

  if (strongOnly) {
    stats = stats.filter(n => {
      const line = lines[n];
      return teamRows.some((rows, i) => {
        const s = summarise(rows, n, line, bucketFor(i));
        return s && (s.pct >= STRONG_HIGH || s.pct <= STRONG_LOW);
      });
    });
  }

  if (sort === "strongest") {
    stats = stats.slice().sort((a, b) => strength(b) - strength(a));
  }

  return stats;
}

function focusedIndexes() {
  return focus === "both" ? [0, 1] : [parseInt(focus, 10)];
}

function updateRow(row) {
  const name = row.dataset.stat;
  const line = activeLines()[name];
  const teamRows = activeRecords().map(filtered);
  const shown = focusedIndexes();

  row.querySelectorAll(".side").forEach(el => el.remove());
  row.classList.toggle("solo", shown.length === 1);
  const middle = row.querySelector(".middle");

  if (shown.length === 1) {
    middle.insertAdjacentHTML("afterend", sideHtml(teamRows[shown[0]], name, line, shown[0]));
  } else {
    middle.insertAdjacentHTML("beforebegin", sideHtml(teamRows[0], name, line, 0));
    middle.insertAdjacentHTML("afterend", sideHtml(teamRows[1], name, line, 1));
  }

  const strong = shown.some(i => {
    const s = summarise(teamRows[i], name, line, bucketFor(i));
    return s && (s.pct >= STRONG_HIGH || s.pct <= STRONG_LOW);
  });
  row.classList.toggle("strong", strong);

  const suggested = source === "h2h"
    ? (SUGGESTED_H2H[period] || {})[name]
    : (SUGGESTED[period] || {})[name];
  row.querySelector("input[data-line]").classList
    .toggle("edited", line !== suggested);
}

function updateAll() {
  boardEl.querySelectorAll(".stat-row").forEach(updateRow);
  const teamRows = activeRecords().map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
}

function setLine(row, value) {
  const clean = snapLine(value);
  activeLines()[row.dataset.stat] = clean;
  row.querySelector("input[data-line]").value = clean;
  updateRow(row);
}

function render() {
  const lines = activeLines();
  const stats = visibleStats();

  if (!stats.length) {
    boardEl.innerHTML =
      '<div class="stat-row"><div class="empty">Nothing matches these filters.</div></div>';
    updateSample();
    return;
  }

  boardEl.innerHTML = stats.map(name => `
    <div class="stat-row" data-stat="${name}">
      <div class="middle">
        <div class="stat-label">${name}</div>
        <div class="stepper">
          <button type="button" data-step="-1" title="Lower the line by 1">&minus;</button>
          <input type="number" step="1" min="0.5" value="${lines[name]}"
                 data-line aria-label="Line for ${name}">
          <button type="button" data-step="1" title="Raise the line by 1">+</button>
        </div>
        ${projectionHtml(name, lines[name])}
      </div>
    </div>`).join("");

  document.getElementById("mismatch").innerHTML =
    mismatchWarning() + ratingsWarning();
  updateAll();
}

function updateSample() {
  const teamRows = activeRecords().map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
}

/* --------------------------------------------------------------- standout

   Ranking by raw hit rate is the obvious approach and it is wrong, because
   5/5 outranks 18/20 while being far weaker evidence. These two functions
   fix that.

   wilsonLow gives the bottom of a 95% confidence interval, so a small
   sample is penalised for being small: 5/5 scores 0.57, 10/10 scores 0.72,
   20/20 scores 0.84. Ranking by it puts durable records above lucky ones.

   binomTail answers the question that actually matters: if this stat were a
   coin flip, how often would a record this good turn up anyway? Scanning
   1,400-odd combinations at ten matches each, roughly 15 will reach 9/10 by
   chance alone. Without that number on screen, a list of "strong" lines is
   indistinguishable from a list of flukes. */

function wilsonLow(k, n, z) {
  if (!n) return 0;
  z = z || 1.96;
  const p = k / n;
  const d = 1 + (z * z) / n;
  const centre = p + (z * z) / (2 * n);
  const margin = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return (centre - margin) / d;
}

function binomTail(n, k) {
  // P(X >= k) for n fair coin flips, computed in logs to stay accurate.
  const logFact = [0];
  for (let i = 1; i <= n; i++) logFact[i] = logFact[i - 1] + Math.log(i);
  let total = 0;
  for (let i = k; i <= n; i++) {
    total += Math.exp(
      logFact[n] - logFact[i] - logFact[n - i] + n * Math.log(0.5)
    );
  }
  return total;
}

/* Turning a hit rate into a price is one division, and that is exactly why
   it is dangerous. 8/10 implies a fair price of 1.25, which looks like free
   money, but ten matches cannot tell 80% from 55%. Run the interval and the
   evidence only supports 2.04 or better.

   So two numbers are quoted. `fair` is what the point estimate says, and it
   is the optimistic one. `minPrice` comes from the bottom of the confidence
   interval and is the number to actually bet off, because it is the price at
   which you are still ahead if your sample flattered the team.

   Neither includes the bookmaker's margin. A real market is priced so the
   implied probabilities sum to more than 100%, typically 105-108% on these,
   so the available price is always worse than fair by design. */
function fairOdds(p) { return p > 0 ? 1 / p : Infinity; }

function fmtOdds(o) {
  if (!isFinite(o)) return "n/a";
  return o >= 10 ? o.toFixed(0) : o.toFixed(2);
}

/* ------------------------------------------------------------ count model

   The old `need` price looked only at how many matches went over the line and
   how many did not. That throws away almost everything: 4,5,3,6,4 corners and
   2,2,2,2,2 corners are both "5 from 5 over 1.5", and one of them is far
   safer than the other. It also never looked at the opponent, so Arsenal at
   home to Coventry priced the same as Arsenal away at City.

   So the price now comes from a count model instead:

     1. Take the opponent-adjusted expectation for this team in this fixture.
        That is the projection already on the page: league average times this
        team's attack rating times this opponent's defence rating, off the
        right home or away base. This is where the mismatch enters.

     2. Fit the spread from the team's own matches. If the variance is close
        to the mean, counts behave like a Poisson process and Poisson is used.
        If the variance is bigger, which is normal for shots, the negative
        binomial handles the extra spread rather than pretending it is not
        there and quoting a price that is too short.

     3. Read the probability straight off that distribution: for a line of
        1.5, P(X >= 2).

     4. Haircut for the fact that the expectation is itself estimated, by
        recomputing at the bottom of a one-sided 95% interval on the mean.

   The result moves continuously with the matchup, which is the entire point.
   A dominant side against a poor one lands near 1.07; a coin flip lands near
   2.00; and two different 19-from-20 records no longer both come out at
   1.31. */

const LG_C = [676.5203681218851, -1259.1392167224028, 771.32342877765313,
              -176.61502916214059, 12.507343278686905, -0.13857109526572012,
              9.9843695780195716e-6, 1.5056327351493116e-7];

function logGamma(z) {
  if (z < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * z)) - logGamma(1 - z);
  z -= 1;
  let x = 0.99999999999980993;
  for (let i = 0; i < 8; i++) x += LG_C[i] / (z + i + 1);
  const t = z + 7.5;
  return 0.5 * Math.log(2 * Math.PI) + (z + 0.5) * Math.log(t) - t + Math.log(x);
}

function poissonCdf(k, mean) {
  if (mean <= 0) return 1;
  if (k < 0) return 0;
  let term = Math.exp(-mean), sum = term;
  for (let i = 1; i <= k; i++) { term *= mean / i; sum += term; }
  return Math.min(1, sum);
}

function negBinCdf(k, mean, size) {
  if (mean <= 0) return 1;
  if (k < 0) return 0;
  const p = size / (size + mean);
  let sum = 0;
  for (let i = 0; i <= k; i++) {
    sum += Math.exp(logGamma(i + size) - logGamma(i + 1) - logGamma(size)
                    + size * Math.log(p) + i * Math.log1p(-p));
  }
  return Math.min(1, sum);
}

/* P(count > line) for a half-integer line. A line of 1.5 means 2 or more, so
   the question is P(X <= 1), hence the floor. */
function probOver(line, mean, vals) {
  if (mean <= 0) return 0;
  const k = Math.floor(line);

  const n = vals.length;
  if (n >= 3) {
    const m = vals.reduce((s, v) => s + v, 0) / n;
    const v = vals.reduce((s, x) => s + (x - m) * (x - m), 0) / (n - 1);
    // Overdispersed: use the negative binomial, carrying the spread observed
    // in the sample over onto the projected mean.
    if (v > m * 1.05 && m > 0) {
      const size = (m * m) / (v - m);
      if (isFinite(size) && size > 0) return 1 - negBinCdf(k, mean, size);
    }
  }
  return 1 - poissonCdf(k, mean);
}

/* One place that turns a row into a price, so the slip, the best bets and the
   standout list cannot disagree with each other.

   `p` is the probability of the bet landing, `fair` is what that is worth, and
   `need` is what you should insist on before staking. When the fixture has an
   opponent-adjusted expectation the count model supplies all three. When it
   does not, which means one side could not be rated, it falls back to the old
   record-only interval and says so, because a made-up expectation would be
   worse than an honest blunt one. */
function priceRow(r) {
  const values = (r.forVals || r.vals || []);
  const expected = expectedFor(r);

  if (expected !== undefined && expected > 0 && values.length >= 3) {
    const n = values.length;
    const mean = values.reduce((s, v) => s + v, 0) / n;
    const variance = values.reduce((s, x) => s + (x - mean) * (x - mean), 0) / (n - 1);
    const se = Math.sqrt(Math.max(variance, 1e-9) / n);

    // One-sided 95% band on the expectation. The projection is an estimate,
    // and pricing off the point estimate assumes it is exact.
    //
    // The band is clipped to half and double the expectation. Ten matches of a
    // noisy stat can produce a standard error big enough to drag the lower
    // bound to nothing, and a bound of nothing prices everything at 20.0,
    // which is not caution, it is just noise wearing caution's clothes. A
    // fifty per cent haircut is already a severe one.
    const low = Math.max(expected * 0.5, expected - 1.645 * se);
    const highBand = Math.min(expected * 2, expected + 1.645 * se);

    let p = probOver(r.line, expected, values);
    let pLow = probOver(r.line, low, values);
    if (!r.over) { p = 1 - p; pLow = 1 - probOver(r.line, highBand, values); }

    // Both ends of the interval on the expectation, so a contradiction can be
    // detected rather than priced. If the record's own lower bound sits above
    // everything the model will allow even at its most generous, then one of
    // the two is wrong and neither should be trusted. That happens when a
    // ratings fit produces something absurd, like an expectation of 0.03
    // first-half offsides for a team that gets one nearly every half.
    const pHigh = r.over ? probOver(r.line, highBand, values)
                         : 1 - probOver(r.line, low, values);

    // A second, blunter sanity check on the expectation itself. An opponent
    // adjustment should move a team's average, that is its whole job, but it
    // should not halve it or double it. When it does, the ratings fit for that
    // stat and period has gone wrong rather than found something. The case
    // that exposed this was an expected 0.46 second-half offsides for a side
    // that had gone over 0.5 in thirteen of twenty, which then priced at 21.
    const absurd = expected < 0.5 * mean || expected > 2 * mean;

    const conflict = absurd || r.score > pHigh + 0.05;

    return {
      p, fair: fairOdds(p), need: fairOdds(Math.max(0.01, pLow)),
      expected, source: "model", conflict,
      recordFair: fairOdds(r.k / r.n), recordNeed: fairOdds(r.score),
    };
  }

  return {
    p: r.k / r.n, fair: fairOdds(r.k / r.n), need: fairOdds(r.score),
    expected: undefined, source: "record",
    recordFair: fairOdds(r.k / r.n), recordNeed: fairOdds(r.score),
  };
}

/* The opponent-adjusted expectation for the team this bet is on. Falls back to
   the cross-division estimate when the fitted one is missing. */
function expectedFor(r) {
  const fx = ALL.fixtures[r.fixtureIndex];
  if (!fx) return undefined;
  const idx = r.teamIndex;

  const fitted = ((fx.projection || {})[r.period] || {})[r.stat];
  if (fitted && fitted[idx] !== undefined) return fitted[idx];

  if (r.period === "ALL" && fx.tierProjection) {
    const est = (fx.tierProjection.stats || {})[r.stat];
    if (est && est[idx] !== undefined) return est[idx];
  }
  return undefined;
}

const VENUE_SPLITS = [
  { key: "all", label: "All matches" },
  { key: "home", label: "At home" },
  { key: "away", label: "Away" },
];

function scanLines(minSample) {
  const found = [];
  let combos = 0;
  let skipped = 0;

  ALL.fixtures.forEach((fx, fxIndex) => {
    Object.keys(fx.lines || {}).forEach(per => {
      const lines = fx.lines[per] || {};
      (fx.stats[per] || []).forEach(name => {
        if (!BETTABLE.has(name)) return;
        const line = lines[name];
        if (line === undefined) return;

        fx.records.forEach((records, teamIndex) => {
          // Skip teams whose record was built in another competition. This
          // is the Coventry case: a true 100% that will not survive contact
          // with the division they are actually playing in.
          if (!includeMismatched) {
            const sample = records.slice(-games);
            const matching = sample.filter(
              r => (r.competition || "?") === fx.fixture.competition
            ).length;
            if (sample.length && matching / sample.length < 0.6) { skipped++; return; }
          }

          // Best split per team/stat/period, so one pattern is one row
          // rather than three near-identical ones.
          let best = null;

          VENUE_SPLITS.forEach(split => {
            let rows = records;
            if (split.key !== "all") rows = rows.filter(r => r.venue === split.key);
            rows = rows.slice(-games);

            const vals = rows
              .map(r => (r.stats[per] || {})[name])
              .filter(v => v !== undefined && v !== null);

            if (vals.length < minSample) return;
            combos++;

            const over = vals.filter(v => v > line).length;
            const under = vals.length - over;
            const goingOver = over >= under;
            const k = goingOver ? over : under;

            const score = wilsonLow(k, vals.length);
            if (!best || score > best.score) {
              best = {
                score,
                k, n: vals.length,
                over: goingOver,
                chance: binomTail(vals.length, k),
                split: split.label,
                vals,
              };
            }
          });

          if (best) {
            found.push(Object.assign(best, {
              fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
              fixtureIndex: fxIndex,
              team: fx.teams[teamIndex].name,
              teamIndex,
              stat: name,
              period: per,
              line,
            }));
          }
        });
      });
    });
  });

  found.sort((a, b) => b.score - a.score);
  return { found, combos, skipped };
}

/* ------------------------------------------------------------- best bets

   The matchup scan. A hit rate on its own only tells you what one team did
   against whoever happened to be in front of them. The question worth asking
   is whether both halves of the fixture point the same way: Arsenal have gone
   over 5.5 corners in nine of their last ten at home, AND Coventry have
   conceded over 5.5 in eight of their last ten away. Two independent records
   agreeing is worth far more than one record twice as long, because they can
   fail independently.

   Venue is enforced on both sides. The home team's home record is matched
   against the away team's away record, never the pooled one, because that is
   the actual fixture.

   The two records are then pooled into one Wilson interval. That is the
   honest way to combine them: twenty observations at 85% supports a much
   shorter price than ten at 85%, and the interval says so by itself. It also
   refuses to let one side carry the other, because both halves must clear the
   bar individually before the pair is scored at all. */

const MATCHUP_FLOOR = 0.65;   // each side must clear this on its own

/* The markets that actually exist. Injected from hitrates.py so there is one
   list, not two that drift apart.

   The scans filter on this rather than trusting the payload, because a report
   built before the bettable filter existed still carries every stat SofaScore
   returns, and re-rendering the page cannot change what is baked into its
   data. That is how "under 0.5 hit woodwork" ended up in a list of bets. */
const BETTABLE = new Set(__BETTABLE__);

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

/* A tail probability of 0.03% printed as "0.0%" reads as impossible, which is
   the one impression this number must never give. */
function fmtChance(p) {
  const pct = p * 100;
  if (pct < 0.05) return "under 0.05%";
  return `${pct.toFixed(pct < 1 ? 2 : 1)}%`;
}

function scanMatchups(minSample) {
  const found = [];
  let combos = 0;
  let skipped = 0;

  ALL.fixtures.forEach((fx, fxIndex) => {
    const now = Date.now() / 1000;
    if (!showPast && (fx.fixture.kickoff || 0) <= now) return;

    Object.keys(fx.lines || {}).forEach(per => {
      const lines = fx.lines[per] || {};

      (fx.stats[per] || []).forEach(name => {
        if (!BETTABLE.has(name)) return;
        const suggested = lines[name];
        if (suggested === undefined) return;

        // Both directions: the home side's attack against the away side's
        // defence, then the reverse.
        [0, 1].forEach(side => {
          const attackVenue  = side === 0 ? "home" : "away";
          const defendVenue  = side === 0 ? "away" : "home";

          const attackRows = fx.records[side]
            .filter(r => r.venue === attackVenue).slice(-games);
          const defendRows = fx.records[1 - side]
            .filter(r => r.venue === defendVenue).slice(-games);

          // Same guard as the standout scan: a promoted club's record is
          // true and useless, and this is the exact fixture where pairing it
          // with a Premier League defence produces a beautiful wrong answer.
          if (!includeMismatched) {
            const bad = [fx.records[side], fx.records[1 - side]].some(recs => {
              const sample = recs.slice(-games);
              const ok = sample.filter(
                r => (r.competition || "?") === fx.fixture.competition).length;
              return sample.length && ok / sample.length < 0.6;
            });
            if (bad) { skipped++; return; }
          }

          const forVals = attackRows
            .map(r => (r.stats[per] || {})[name])
            .filter(v => v !== undefined && v !== null);
          const againstVals = defendRows
            .map(r => (r.against[per] || {})[name])
            .filter(v => v !== undefined && v !== null);

          if (forVals.length < minSample || againstVals.length < minSample) return;

          // A short ladder around the suggested line, which is the median and
          // so stands in for where a bookmaker would hang it.
          //
          // The ladder is deliberately one-sided per direction. An over bet
          // BELOW the median, or an under bet ABOVE it, is a bet on the easy
          // side of the market: it will hit almost every week and be priced
          // at 1.05, and it swamped this list when both sides were allowed.
          // "Newcastle over 0.5 yellow cards, 20 from 20" is true, useless,
          // and exactly what a scan like this produces if you let it. So an
          // over only looks at the median and above, an under at the median
          // and below. It also halves the combinations trawled, which makes
          // everything that survives a little more meaningful.
          [-1, 0, 1].forEach(step => {
            const line = suggested + step;
            if (line < 0.5) return;
            combos++;

            const forOver     = forVals.filter(v => v > line).length;
            const againstOver = againstVals.filter(v => v > line).length;

            [true, false].forEach(over => {
              if (over && step < 0) return;
              if (!over && step > 0) return;
              const kFor = over ? forOver : forVals.length - forOver;
              const kAgn = over ? againstOver : againstVals.length - againstOver;

              const pFor = kFor / forVals.length;
              const pAgn = kAgn / againstVals.length;
              if (pFor < MATCHUP_FLOOR || pAgn < MATCHUP_FLOOR) return;

              const k = kFor + kAgn;
              const n = forVals.length + againstVals.length;
              const score = wilsonLow(k, n);

              found.push({
                score, k, n, over, line,
                stat: name, period: per,
                fixture: `${fx.fixture.home} v ${fx.fixture.away}`,
                fixtureIndex: fxIndex,
                competition: fx.fixture.competition,
                kickoff: fx.fixture.kickoff || 0,
                team: fx.teams[side].name,
                teamIndex: side,
                opponent: fx.teams[1 - side].name,
                attackVenue, defendVenue,
                kFor, nFor: forVals.length, pFor,
                kAgn, nAgn: againstVals.length, pAgn,
                forVals, againstVals,
                chance: binomTail(n, k),
                // Does the opponent-adjusted projection agree? Not required,
                // but a disagreement is worth seeing before you stake.
                proj: ((fx.projection || {})[per] || {})[name],
                est: !(fx.projection || {})[per]
                     && fx.tierProjection ? (fx.tierProjection.stats || {})[name] : undefined,
              });
            });
          });
        });
      });
    });
  });

  // One row per team and stat: keep only that pairing's best line and
  // direction, otherwise the top three are the same bet at three prices.
  //
  // The tiebreak matters more than it looks. The score depends only on how
  // many of n went the right way, so "over 0.5 goals" and "over 2.5 goals"
  // both score identically at 10/10, and without a tiebreak the list fills
  // up with lines nobody would price. Among equal records, take the most
  // demanding line: the highest for an over, the lowest for an under.
  const demand = r => (r.over ? r.line : -r.line);

  const best = new Map();
  found.forEach(r => {
    const key = [r.fixtureIndex, r.teamIndex, r.stat, r.period].join("|");
    const held = best.get(key);
    if (!held
        || r.score > held.score
        || (r.score === held.score && demand(r) > demand(held))) {
      best.set(key, r);
    }
  });

  // Across stats, a tie on score is broken by how close the line sits to what
  // the teams actually average. A line the record clears by a mile is a line
  // the bookmaker will price at odds not worth taking.
  const tightness = r => {
    const all = r.forVals.concat(r.againstVals);
    const mean = all.reduce((s, v) => s + v, 0) / all.length;
    return -Math.abs(mean - r.line);
  };

  const list = [...best.values()].sort(
    (a, b) => (b.score - a.score) || (tightness(b) - tightness(a)));
  return { found: list, combos, skipped };
}

function bestBetsView() {
  const minSample = parseInt(document.getElementById("bmin").value, 10) || 4;
  const limit = parseInt(document.getElementById("btop").value, 10) || 10;
  let { found, combos, skipped } = scanMatchups(minSample);

  const periodName = p => (ALL.periods && ALL.periods[p]) || p;
  const target = document.getElementById("bestbets");

  if (!found.length) {
    target.innerHTML = `<p class="empty">No matchup had both halves at
      ${Math.round(MATCHUP_FLOOR * 100)}% or better on at least ${minSample}
      matches each. Lower the minimum, or build with more games.</p>`;
    window.__best = [];
    return;
  }

  // Now that prices actually vary, one ordering no longer suits. Evidence puts
  // the best-supported records first. Likely sorts by the model's probability,
  // which favours mismatches. Price sorts the other way, surfacing the ones
  // that pay something, which are the ones worth pricing up against a book.
  const order = document.querySelector("[data-border][aria-pressed='true']")
    ?.dataset.border || "evidence";

  found.forEach(r => { r.price = r.price || priceRow(r); });

  // Drop the ones where the count model and the record cannot both be right.
  const contradictory = found.filter(r => r.price.conflict).length;
  found = found.filter(r => !r.price.conflict);

  if (!found.length) {
    target.innerHTML = `<p class="empty">Everything that qualified was thrown
      out because the model and the record contradicted each other. That
      usually means the ratings fit is thin for this competition.</p>`;
    window.__best = [];
    return;
  }

  if (order !== "evidence") {
    found.sort((a, b) => order === "likely"
      ? a.price.need - b.price.need
      : b.price.need - a.price.need);
  }

  // Grouped by competition, because "top three this gameweek" means three
  // per division, not three across a file that happens to hold six leagues.
  const byComp = new Map();
  found.forEach(r => {
    if (!byComp.has(r.competition)) byComp.set(r.competition, []);
    byComp.get(r.competition).push(r);
  });

  const shown = [];
  const blocks = [...byComp.entries()].map(([comp, rows]) => {
    const picks = rows.slice(0, limit);
    const cards = picks.map(r => {
      const i = shown.push(r) - 1;
      const price = priceRow(r);
      r.price = price;                      // the slip reads this back
      const fair = price.fair;
      const need = price.need;
      const dir = r.over ? "over" : "under";

      // The projection, when there is one, is the only thing here that did
      // not come from the same matches as the record.
      let agree = "";
      const projValues = r.proj || r.est;
      if (projValues) {
        const expected = projValues[r.teamIndex];
        if (expected !== undefined) {
          const agrees = r.over ? expected > r.line : expected < r.line;
          agree = `<div class="agree ${agrees ? "yes" : "no"}">
            ${r.proj ? "Projected" : "Estimated"} ${expected}
            ${agrees ? "agrees" : "disagrees"}</div>`;
        }
      }

      return `<div class="pick" data-best="${i}">
        <div class="pick-head">
          <div class="pick-line">${escapeHtml(r.team)} ${dir} ${r.line}
            ${escapeHtml(r.stat.toLowerCase())}
            <span class="pos">${periodName(r.period)}</span></div>
          <div class="pick-fixture">${escapeHtml(r.fixture)}</div>
        </div>

        <div class="pick-halves">
          <div class="half">
            <span class="half-label">${escapeHtml(r.team)} ${r.attackVenue}</span>
            <span class="half-num">${r.kFor}/${r.nFor}</span>
            <div class="bar"><div class="fill" style="width:${r.pFor * 100}%;
                 background:var(${VARS[r.teamIndex]})"></div></div>
            <span class="seq">${r.forVals.join(", ")}</span>
          </div>
          <div class="half">
            <span class="half-label">${escapeHtml(r.opponent)} conceded, ${r.defendVenue}</span>
            <span class="half-num">${r.kAgn}/${r.nAgn}</span>
            <div class="bar"><div class="fill" style="width:${r.pAgn * 100}%;
                 background:var(${VARS[1 - r.teamIndex]})"></div></div>
            <span class="seq">${r.againstVals.join(", ")}</span>
          </div>
        </div>

        <div class="pick-foot">
          <span><b>${r.k}/${r.n}</b> combined</span>
          <span>fair <b>${fmtOdds(fair)}</b></span>
          <span class="need-cell">need <b>${fmtOdds(need)}</b>
            ${price.source === "model"
              ? `<span class="src" title="Priced from an expected ${price.expected} in this fixture, ` +
                `read off a fitted count distribution. The record on its own would have said ` +
                `${fmtOdds(price.recordNeed)}.">${price.expected}&nbsp;exp</span>`
              : `<span class="src warnsrc" title="No opponent-adjusted expectation for this fixture, ` +
                `so this is the blunt record-only interval.">record only</span>`}
          </span>
          <span class="chance">${fmtChance(r.chance)} by chance</span>
          ${agree}
          <button type="button" class="add-btn" data-badd="${i}"
            data-in="${SLIP.some(s => s.key === rowKey(r)) ? 1 : 0}">
            ${SLIP.some(s => s.key === rowKey(r)) ? "Added" : "Add"}</button>
        </div>
      </div>`;
    }).join("");

    return `<div class="comp-head">${escapeHtml(comp)}
      <span class="pos">${rows.length} qualified</span></div>${cards}`;
  }).join("");

  window.__best = shown;

  const weakest = shown[shown.length - 1];
  const expected = combos * binomTail(weakest.n, weakest.k);

  target.innerHTML = `
    <div class="caution">
      <strong>What this is.</strong> Both halves of the fixture pointing the
      same way: the team's own record at this venue, and what their opponent
      concedes at theirs. Two records agreeing is stronger evidence than one
      record twice as long, because they can fail independently. Both halves
      must clear ${Math.round(MATCHUP_FLOOR * 100)}% on their own before a
      pairing is scored at all, so a 10/10 cannot drag a 3/10 into the list.
      <br><br>
      <strong>What it is not.</strong> This scan looked at
      <strong>${combos}</strong> combinations, and
      ${expected < 1
        ? `fewer than <strong>one</strong> of them would`
        : `roughly <strong>${expected.toFixed(0)}</strong> of them would`}
      look this good with nothing behind them at all. Both records also come from the same matches
      the lines were derived from, which flatters them. <strong>Need</strong> is
      the price the evidence supports once the sample size is accounted for, and
      it is the only number here worth betting off. Nothing on this page knows
      what the bookmaker is offering, and the price is the entire bet.
      ${skipped ? `<br><br><strong>${skipped}</strong> pairings were left out
        because one side's record was built in a different competition.` : ""}
      ${contradictory ? `<br><br><strong>${contradictory}</strong> more were
        dropped because the count model and the raw record contradicted each
        other beyond what either one's uncertainty allows. When those two
        disagree that badly, one of them is wrong and there is no way to tell
        which from here.` : ""}
    </div>
    ${blocks}`;
}

function rowKey(r) {
  return [r.fixtureIndex, r.teamIndex, r.stat, r.period, r.line, r.over].join("|");
}

function standoutView() {
  const minSample = parseInt(document.getElementById("smin").value, 10) || 6;
  const limit = parseInt(document.getElementById("stop").value, 10) || 20;

  const { found, combos, skipped } = scanLines(minSample);
  const shown = found.slice(0, limit);
  window.__shown = shown;

  const periodName = p => (ALL.periods && ALL.periods[p]) || p;

  if (!shown.length) {
    document.getElementById("standout").innerHTML =
      '<p class="empty">Nothing met the minimum sample. Lower it, or build with more matches.</p>';
    return;
  }

  // How many of the scanned combinations would reach the weakest shown
  // record purely by chance? This is the number that keeps you honest.
  const weakest = shown[shown.length - 1];
  const expected = combos * binomTail(weakest.n, weakest.k);

  const rows = shown.map((r, i) => {
    const p = r.k / r.n;
    const price = priceRow(r);
    r.price = price;
    const fair = price.fair;
    const minPrice = price.need;
    return `
    <tr data-row="${i}" data-plow="${1 / minPrice}" data-fair="${fair}" data-min="${minPrice}">
      <td class="player-name">${r.stat}
        <span class="pos">${periodName(r.period)}</span>
        <span class="sub-line">${r.team} &middot; ${r.split} &middot; ${r.fixture}</span></td>
      <td class="dir">${r.over ? "Over" : "Under"} ${r.line}</td>
      <td data-label="Record">
        <div><span class="pct">${Math.round(p * 100)}%</span>
             <span class="frac">${r.k}/${r.n}</span></div>
        <div class="bar"><div class="fill" style="width:${p * 100}%;
             background:var(${VARS[r.teamIndex]})"></div></div>
      </td>
      <td class="odds" data-label="Fair">${fmtOdds(fair)}</td>
      <td class="odds odds-min" data-label="Need">${fmtOdds(minPrice)}</td>
      <td data-label="Your price">
        <input class="price-input" type="number" step="0.05" min="1.01"
               data-price aria-label="Bookmaker price for ${r.stat}"></td>
      <td class="verdict" data-verdict data-label="Verdict"></td>
      <td class="chance" data-label="By chance">${(r.chance * 100).toFixed(1)}%</td>
      <td><button type="button" class="add-btn" data-add="${i}"
            data-in="${SLIP.some(s => s.key === rowKey(r)) ? 1 : 0}">
            ${SLIP.some(s => s.key === rowKey(r)) ? "Added" : "Add"}</button></td>
    </tr>`;
  }).join("");

  document.getElementById("standout").innerHTML = `
    <div class="caution">
      <strong>Read this before using any of it.</strong>
      This scan looked at <strong>${combos}</strong> combinations of fixture, team,
      stat, period and venue. Of those, roughly <strong>${expected.toFixed(0)}</strong>
      would look at least this consistent even if every one of them were a coin flip.
      The list below is therefore a shortlist to price up, not a set of findings.
      A hit rate is not an edge: the only thing that makes a bet worth taking is the
      price being wrong, and there is no odds feed here to tell you that.
      The lines are also derived from these same matches, which flatters them.
      ${skipped ? `<br><br><strong>${skipped}</strong> team-stat combinations were
        left out because that side's record was built in a different competition
        from the one they are playing in. Use the toggle to include them, but a
        promoted side's numbers against weaker opposition are exactly the sort of
        true record that loses money.` : ""}
      <br><br>
      <strong>Fair</strong> is the price the hit rate implies on its own.
      <strong>Need</strong> is the price the <em>evidence</em> supports, taken from the
      bottom of a 95% interval, and it is the one to bet off. Ten matches cannot tell
      80% from 55%, so 8/10 reads as a fair 1.25 while only really justifying 2.04.
      Neither figure includes the bookmaker's margin, which is typically 5 to 8% on
      these markets and always works against you.
    </div>
    <div class="board"><table class="ptable">
      <thead><tr>
        <th>Stat</th><th>Line</th><th>Record</th>
        <th title="Price implied by the hit rate itself">Fair</th>
        <th title="Price implied by the bottom of the confidence interval">Need</th>
        <th>Your price</th><th>Verdict</th><th>By chance</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

/* ------------------------------------------------------------------ slip

   A score out of 100, built from four things that can each be justified
   rather than one number pulled out of the air. The breakdown is always
   shown, because a score you cannot interrogate is just an opinion with a
   number stuck on it.

   Value carries the most weight by a distance, and deliberately so. The
   record tells you what happened; only the price tells you whether the bet
   is worth making. A 10/10 record at 1.10 is a bad bet and a 6/10 record at
   4.00 may be a good one. */
const SLIP = [];

function scorePick(r, price) {
  const parts = {};

  // Value: how far the price beats what the evidence supports. Zero without
  // a price, because without one there is nothing to judge.
  if (!price || price <= 1) {
    parts.value = 0;
  } else {
    const need = (r.price || priceRow(r)).need;
    const ratio = price / need;
    parts.value = Math.max(0, Math.min(45, Math.round((ratio - 0.85) * 150)));
  }

  // Evidence: how much data sits behind it.
  parts.evidence = Math.max(0, Math.min(25, Math.round((r.n - 4) * 2.5)));

  // Agreement: does the opponent-adjusted projection point the same way?
  const proj = ((ALL.fixtures[r.fixtureIndex].projection || {})[r.period] || {})[r.stat];
  if (proj === undefined) {
    parts.agreement = 7;                      // unknown, so neither rewarded nor punished
  } else {
    const expected = proj[r.teamIndex];
    const agrees = r.over ? expected > r.line : expected < r.line;
    parts.agreement = agrees ? 15 : 0;
  }

  // Context: was the record built against the right standard of opposition?
  const fx = ALL.fixtures[r.fixtureIndex];
  const sample = fx.records[r.teamIndex].slice(-games);
  const matching = sample.filter(
    x => (x.competition || "?") === fx.fixture.competition
  ).length;
  parts.context = sample.length && matching / sample.length >= 0.6 ? 15 : 0;

  const total = parts.value + parts.evidence + parts.agreement + parts.context;
  return { total, parts };
}

function slipView() {
  const el = document.getElementById("slip");

  if (!SLIP.length) {
    el.innerHTML = `<p class="empty">
      Nothing added yet. Open Standout lines and press "Add" on any row.
    </p>`;
    return;
  }

  const rows = SLIP.map((entry, i) => {
    const r = entry.row;
    const { total, parts } = scorePick(r, entry.price);
    const cls = total >= 65 ? "good" : total < 40 ? "poor" : "";

    return `<tr data-slip="${i}">
      <td class="player-name">${r.stat}
        <span class="pos">${(ALL.periods || {})[r.period] || r.period}</span>
        <span class="sub-line">${r.team} &middot; ${r.over ? "Over" : "Under"} ${r.line}
          &middot; ${r.fixture}</span></td>
      <td class="num" data-label="Record">${r.k}/${r.n}</td>
      <td class="odds" data-label="Need">${fmtOdds((r.price || priceRow(r)).need)}</td>
      <td data-label="Your price">
        <input class="price-input" type="number" step="0.05" min="1.01"
               value="${entry.price || ""}" data-slip-price
               aria-label="Price for ${r.stat}"></td>
      <td data-label="Score">
        <div class="score ${cls}">${total}</div>
        <div class="breakdown">
          <span>value ${parts.value}/45</span>
          <span>evidence ${parts.evidence}/25</span>
          <span>model ${parts.agreement}/15</span>
          <span>context ${parts.context}/15</span>
        </div>
      </td>
      <td><button type="button" class="add-btn" data-remove="${i}">Remove</button></td>
    </tr>`;
  }).join("");

  // What happens if you put them together.
  const priced = SLIP.filter(s => s.price > 1);
  let combo = "";

  if (priced.length > 1) {
    const combined = priced.reduce((acc, s) => acc * s.price, 1);
    // Multiply the supported probabilities, not the raw records, so a long
    // shot leg is not flattered by a small sample that happened to be perfect.
    const chance = priced.reduce(
      (acc, s) => acc * Math.min(0.999, 1 / (s.row.price || priceRow(s.row)).need), 1);
    const fair = 1 / chance;
    const perLeg = Math.pow(fair / combined, 1 / priced.length);

    combo = `<div class="caution">
      <strong>Putting ${priced.length} of these together.</strong>
      Combined price <strong>${fmtOdds(combined)}</strong>, against a fair price of
      <strong>${fmtOdds(fair)}</strong> on the conservative estimates.
      ${combined >= fair
        ? "That clears, but only if the legs are genuinely independent, and they rarely are."
        : `You would need each leg to be about <strong>${((perLeg - 1) * 100).toFixed(1)}%</strong>
           better priced than it is for this to break even.`}
      <br><br>
      Worth knowing what multiples do. The bookmaker's margin compounds with every
      leg: at a typical 5% per market, a treble carries about 16% against you and a
      five-fold about 28%. Singles are where value survives. Accumulators are the
      most profitable product in the shop, and not for the person buying them.
    </div>`;
  }

  el.innerHTML = `${combo}
    <div class="board"><table class="ptable">
      <thead><tr>
        <th>Selection</th><th>Record</th><th>Need</th>
        <th>Your price</th><th>Score</th><th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

/* ---------------------------------------------------------------- players */

function playerView() {
  if (!hasPlayers()) return;

  const stat = document.getElementById("pstat").value;
  const line = parseFloat(document.getElementById("pline").value) || 0;
  const minApps = parseInt(document.getElementById("pmin").value, 10) || 1;

  const blocks = DATA.players.map((records, teamIndex) => {
    // Scope player rows to exactly the matches the team filters are showing,
    // so "last 5, home only" means the same thing on both tabs.
    const allowed = new Set(filtered(DATA.records[teamIndex]).map(m => m.id));
    const rows = records.filter(r => allowed.has(r.match_id));

    const byPlayer = new Map();
    for (const r of rows) {
      if (!byPlayer.has(r.player)) byPlayer.set(r.player, []);
      byPlayer.get(r.player).push(r);
    }

    const colorVar = VARS[teamIndex];
    const title = `<h2 class="team-title">
        <span class="swatch" style="background:var(${colorVar})"></span>
        ${DATA.teams[teamIndex].name}
      </h2>`;

    const built = [...byPlayer.entries()].map(([name, played]) => {
      const vals = played.map(g => g.stats[stat])
                         .filter(v => v !== undefined && v !== null);
      if (vals.length < minApps) return null;
      const hits = vals.filter(v => v > line).length;
      const pct = Math.round((hits / vals.length) * 100);
      const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
      return { name, pos: played[0].position || "", played, vals, hits, pct, avg };
    }).filter(Boolean);

    built.sort((a, b) => b.pct - a.pct || b.vals.length - a.vals.length);

    if (!built.length) {
      return `<div class="team-block">${title}
        <div class="board"><div class="stat-row">
          <span class="empty">No player met the minimum appearances.</span>
        </div></div></div>`;
    }

    const fmt = v => (Number.isInteger(v) ? v : v.toFixed(1));

    const body = built.map(p => {
      const fake = p.played.map(g => ({
        date: g.date, venue: g.venue, opponent: g.opponent,
        stats: { [stat]: g.stats[stat] },
      }));
      const strong = p.pct >= STRONG_HIGH || p.pct <= STRONG_LOW;
      return `<tr class="${strong ? "strong" : ""}">
        <td class="player-name">${p.name}<span class="pos">${p.pos}</span></td>
        <td class="num" data-label="Apps">${p.vals.length}</td>
        <td class="num" data-label="Avg">${p.avg.toFixed(1)}</td>
        <td>
          <div class="pcell">
            <div class="figure">
              <div><span class="pct">${p.pct}%</span>
                   <span class="frac">${p.hits}/${p.vals.length}</span></div>
              <div class="bar"><div class="fill"
                style="width:${p.pct}%;background:var(${colorVar})"></div></div>
            </div>
            ${sparkline(fake, stat, line, colorVar)}
            <span class="seq">${p.vals.map(fmt).join(", ")}</span>
          </div>
        </td>
      </tr>`;
    }).join("");

    return `<div class="team-block">${title}
      <div class="board"><table class="ptable">
        <thead><tr>
          <th>Player</th><th>Apps</th><th>Avg</th><th>${stat} over ${line}</th>
        </tr></thead>
        <tbody>${body}</tbody>
      </table></div>
    </div>`;
  });

  document.getElementById("players").innerHTML = blocks.join("");
}

function fillPlayerStats() {
  const select = document.getElementById("pstat");
  const tabs = document.querySelector(".tabs");

  if (!hasPlayers()) {
    tabs.hidden = true;
    if (tab === "players") switchTab("team");
    return;
  }

  tabs.hidden = false;
  const previous = select.value;
  select.innerHTML = DATA.playerStats
    .map(n => `<option value="${n}">${n}</option>`).join("");

  const wanted = DATA.playerStats.includes(previous)
    ? previous
    : (DATA.playerStats.includes("Shots") ? "Shots" : DATA.playerStats[0]);

  select.value = wanted;
  document.getElementById("pline").value = DATA.playerLines[wanted] ?? 0.5;
}

/* --------------------------------------------------------------- fixtures */

function applyFixture() {
  SUGGESTED = {};
  for (const [key, bucket] of Object.entries(DATA.lines)) {
    SUGGESTED[key] = Object.assign({}, bucket);
  }
  SUGGESTED_H2H = {};
  for (const [key, bucket] of Object.entries(DATA.h2hLines || {})) {
    SUGGESTED_H2H[key] = Object.assign({}, bucket);
  }

  // Reports built before "against" existed have no conceded numbers.
  if (!hasAgainst() && measure !== "for") measure = "for";
  document.querySelectorAll("[data-measure]").forEach(b => {
    b.disabled = b.dataset.measure !== "for" && !hasAgainst();
    b.setAttribute("aria-pressed", b.dataset.measure === measure);
  });

  // A fixture between newly promoted sides may have no previous meetings.
  if (!hasH2H() && source === "h2h") source = "form";
  document.querySelectorAll("[data-source]").forEach(b => {
    b.disabled = b.dataset.source === "h2h" && !hasH2H();
    b.setAttribute("aria-pressed", b.dataset.source === source);
  });

  // A fixture can be missing a half if SofaScore never published it.
  if (!DATA.lines[period]) period = "ALL";
  document.querySelectorAll("[data-period]").forEach(b => {
    b.disabled = !DATA.lines[b.dataset.period];
    b.setAttribute("aria-pressed", b.dataset.period === period);
  });

  // The opposition filter is only meaningful when last season's tables were
  // read, and only some fixtures are built with them.
  const tierGroup = document.getElementById("tier-group");
  if (tierGroup) {
    tierGroup.hidden = !DATA.tiers;
    if (!DATA.tiers && tier !== "all") {
      tier = "all";
      document.querySelectorAll("[data-tier]").forEach(b =>
        b.setAttribute("aria-pressed", b.dataset.tier === "all"));
    }
  }

  document.getElementById("competition").textContent = DATA.fixture.competition;
  document.getElementById("title").textContent =
    `${DATA.fixture.home} v ${DATA.fixture.away}`;
  document.getElementById("kickoff").textContent = DATA.fixture.date || "";
  document.getElementById("legend-0").textContent = DATA.teams[0].name;
  document.getElementById("legend-1").textContent = DATA.teams[1].name;
  document.getElementById("focus-0").textContent = DATA.teams[0].name;
  document.getElementById("focus-1").textContent = DATA.teams[1].name;
  document.title = `${DATA.fixture.home} v ${DATA.fixture.away}: hit rates`;

  fillPlayerStats();
  render();
  if (tab === "players") playerView();
  if (tab === "standout") standoutView();
  if (tab === "best") bestBetsView();
}

function switchTab(target) {
  tab = target;
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.setAttribute("aria-selected", b.dataset.tab === target));
  document.querySelectorAll(".panel").forEach(p =>
    p.hidden = p.dataset.panel !== target);
  if (target === "players") playerView();
  if (target === "standout") standoutView();
  if (target === "best") bestBetsView();
  if (target === "slip") slipView();
}

/* ---------------------------------------------------------------- wiring */

// Delegated to the board, so handlers survive every re-render.

boardEl.addEventListener("click", e => {
  const btn = e.target.closest("button[data-step]");
  if (!btn) return;
  const row = btn.closest(".stat-row");
  setLine(row, activeLines()[row.dataset.stat] + parseFloat(btn.dataset.step));
});

boardEl.addEventListener("input", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  const value = parseFloat(input.value);
  if (Number.isNaN(value)) return;          // half-typed, leave it alone
  const row = input.closest(".stat-row");
  activeLines()[row.dataset.stat] = Math.max(0, value);
  updateRow(row);
});

/* The guard matters. Clicking a stepper blurs the input, firing `change`
   with the value from before the click. Comparing against DATA.lines, the
   single source of truth, makes that stale event a no-op. */
boardEl.addEventListener("change", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  const row = input.closest(".stat-row");
  const current = activeLines()[row.dataset.stat];
  const typed = parseFloat(input.value);
  if (Number.isNaN(typed) || snapLine(typed) === current) {
    input.value = current;
    return;
  }
  setLine(row, typed);
});

function wireTooltips(el) {
  el.addEventListener("mouseover", e => {
    const dot = e.target.closest("circle[data-tip]");
    if (!dot) return;
    tip.innerHTML = dot.dataset.tip;
    tip.style.opacity = "1";
  });
  el.addEventListener("mousemove", e => {
    if (tip.style.opacity !== "1") return;
    tip.style.left = (e.clientX + 12) + "px";
    tip.style.top = (e.clientY - 36) + "px";
  });
  el.addEventListener("mouseout", e => {
    if (e.target.closest("circle[data-tip]")) tip.style.opacity = "0";
  });
}
wireTooltips(boardEl);
wireTooltips(document.getElementById("players"));

function segment(attr, apply) {
  document.querySelectorAll(`[data-${attr}]`).forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(`[data-${attr}]`).forEach(b =>
        b.setAttribute("aria-pressed", b === btn));
      apply(btn.dataset[attr]);
    });
  });
}

segment("games", v => {
  games = parseInt(v, 10);
  render();
  if (tab === "players") playerView();
  if (tab === "standout") standoutView();
  if (tab === "best") bestBetsView();
});
segment("border", () => bestBetsView());
segment("tier", v => { tier = v; render(); if (tab === "players") playerView(); });
segment("venue", v => { venue = v; render(); if (tab === "players") playerView(); });
segment("period", v => { period = v; render(); });
segment("source", v => { source = v; render(); });
segment("measure", v => { measure = v; render(); });
segment("focus", v => { focus = v; render(); });
segment("scope", v => { scope = v; render(); });
segment("sort", v => { sort = v; render(); });

document.getElementById("strong-only").addEventListener("click", e => {
  strongOnly = !strongOnly;
  e.currentTarget.setAttribute("aria-pressed", strongOnly);
  render();
});

document.querySelectorAll("[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.getElementById("reset").addEventListener("click", () => {
  for (const key of Object.keys(SUGGESTED)) {
    DATA.lines[key] = Object.assign({}, SUGGESTED[key]);
  }
  for (const key of Object.keys(SUGGESTED_H2H)) {
    DATA.h2hLines[key] = Object.assign({}, SUGGESTED_H2H[key]);
  }
  render();
});

document.getElementById("theme").addEventListener("click", () => {
  const now = document.documentElement.getAttribute("data-theme");
  document.documentElement.setAttribute(
    "data-theme", now === "dark" ? "light" : "dark");
});

/* The report is a static snapshot, but the browser knows the time, so it can
   drop fixtures that have already kicked off. That keeps a weekend card
   useful all weekend instead of going stale one match at a time. */
/* "Sat 23 Aug, 15:00" in the reader's own timezone. The payload stores a
   unix timestamp precisely so this can be local rather than UTC: a 20:00 UTC
   kick-off is a 21:00 one in most of Europe, and getting that wrong by an
   hour is the sort of thing that loses a bet. */
function shortWhen(kickoff) {
  if (!kickoff) return "";
  const d = new Date(kickoff * 1000);
  const day = d.toLocaleDateString(undefined,
    { weekday: "short", day: "numeric", month: "short" });
  const time = d.toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day}, ${time}`;
}

const fixtureSelect = document.getElementById("fixture");
const pastToggle = document.getElementById("show-past");

function upcomingIndexes() {
  const now = Date.now() / 1000;
  return ALL.fixtures
    .map((f, i) => i)
    .filter(i => showPast || (ALL.fixtures[i].fixture.kickoff || 0) > now);
}

function fillFixtures() {
  let indexes = upcomingIndexes();

  // If every fixture has been played, show them all rather than an empty page.
  const allPlayed = indexes.length === 0;
  if (allPlayed) indexes = ALL.fixtures.map((f, i) => i);

  const now = Date.now() / 1000;

  // Soonest first. A weekend card is read in kick-off order, not in whatever
  // order the clubs came back from the league table.
  indexes.sort((a, b) =>
    (ALL.fixtures[a].fixture.kickoff || 0) - (ALL.fixtures[b].fixture.kickoff || 0));

  fixtureSelect.innerHTML = indexes.map(i => {
    const f = ALL.fixtures[i].fixture;
    const played = (f.kickoff || 0) <= now;
    return `<option value="${i}">${shortWhen(f.kickoff)}  ${f.home} v ${f.away}`
         + `${played ? " (played)" : ""}</option>`;
  }).join("");

  const hidden = ALL.fixtures.length - indexes.length;
  pastToggle.hidden = ALL.fixtures.length < 2;
  pastToggle.textContent = hidden
    ? `Show ${hidden} played`
    : (showPast ? "Hide played" : "All upcoming");
  pastToggle.setAttribute("aria-pressed", showPast);

  // Keep the current fixture selected if it survived the filter.
  const current = ALL.fixtures.indexOf(DATA);
  if (indexes.includes(current)) {
    fixtureSelect.value = String(current);
  } else {
    DATA = ALL.fixtures[indexes[0]];
    fixtureSelect.value = String(indexes[0]);
    applyFixture();
  }

  document.getElementById("fixture-group").hidden = indexes.length < 2;
}

/* The index links straight to a fixture with #e<event id>. Matching on the
   event id rather than a position means the link survives a rebuild that
   reorders or drops fixtures, which happens every week. */
function applyDeepLink() {
  const match = /^#e(\d+)$/.exec(location.hash || "");
  if (!match) return false;

  const wanted = parseInt(match[1], 10);
  const found = ALL.fixtures.findIndex(f => f.fixture.id === wanted);
  if (found < 0) return false;

  DATA = ALL.fixtures[found];

  // A fixture that has already kicked off is filtered out of the dropdown by
  // default, so linking to one has to turn the filter off or the selection
  // gets thrown straight back to the first upcoming match.
  if ((DATA.fixture.kickoff || 0) <= Date.now() / 1000 && !showPast) {
    showPast = true;
    fillFixtures();
  }

  // The dropdown is the visible truth. Leaving it pointing at a different
  // fixture from the one on screen is worse than not linking at all.
  fixtureSelect.value = String(found);
  applyFixture();
  return true;
}

window.addEventListener("hashchange", applyDeepLink);

if (ALL.fixtures.length > 1) {
  fixtureSelect.addEventListener("change", () => {
    DATA = ALL.fixtures[parseInt(fixtureSelect.value, 10)];
    applyFixture();
  });
  pastToggle.addEventListener("click", () => {
    showPast = !showPast;
    fillFixtures();
  });
  fillFixtures();
  // After fillFixtures, never before. fillFixtures resets the selection to
  // the first upcoming fixture whenever the current one is not in its list,
  // so calling this first meant the deep link was silently overwritten and
  // the link landed on whatever happened to be at the top.
  applyDeepLink();
} else {
  document.getElementById("fixture-group").hidden = true;
  pastToggle.hidden = true;
}

/* Rebuilding both squad tables on every keystroke is laggy once a report
   holds a full league round, so wait for a pause in the typing. */
let playerTimer = null;
function playerViewSoon() {
  clearTimeout(playerTimer);
  playerTimer = setTimeout(playerView, 120);
}

const pstat = document.getElementById("pstat");
pstat.addEventListener("change", () => {
  document.getElementById("pline").value = DATA.playerLines[pstat.value] ?? 0.5;
  playerView();
});
document.getElementById("pline").addEventListener("input", playerViewSoon);
document.getElementById("pmin").addEventListener("input", playerViewSoon);

let standoutTimer = null;
function standoutSoon() {
  clearTimeout(standoutTimer);
  standoutTimer = setTimeout(standoutView, 140);
}
document.getElementById("include-mismatched").addEventListener("click", e => {
  includeMismatched = !includeMismatched;
  e.currentTarget.setAttribute("aria-pressed", includeMismatched);
  standoutView();
  bestBetsView();
});

// The best-bets controls and its own Add button. Picks added here have no
// price box beside them, because a matchup card is a shortlist entry rather
// than a priced bet: you type the price in on the slip.
["bmin", "btop"].forEach(id =>
  document.getElementById(id).addEventListener("input", () => {
    clearTimeout(standoutTimer);
    standoutTimer = setTimeout(bestBetsView, 140);
  }));

document.getElementById("bestbets").addEventListener("click", e => {
  const btn = e.target.closest("button[data-badd]");
  if (!btn) return;
  const r = (window.__best || [])[parseInt(btn.dataset.badd, 10)];
  if (!r) return;

  const key = rowKey(r);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) SLIP.splice(at, 1);
  else SLIP.push({ key, row: r, price: 0 });

  bestBetsView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("standout").addEventListener("click", e => {
  const btn = e.target.closest("button[data-add]");
  if (!btn) return;
  const r = (window.__shown || [])[parseInt(btn.dataset.add, 10)];
  if (!r) return;

  const key = rowKey(r);
  const at = SLIP.findIndex(s => s.key === key);
  if (at >= 0) {
    SLIP.splice(at, 1);
  } else {
    const priceInput = btn.closest("tr").querySelector("input[data-price]");
    SLIP.push({ key, row: r, price: parseFloat(priceInput?.value) || 0 });
  }
  standoutView();
  slipView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("slip").addEventListener("click", e => {
  const btn = e.target.closest("button[data-remove]");
  if (!btn) return;
  SLIP.splice(parseInt(btn.dataset.remove, 10), 1);
  slipView();
  standoutView();
  document.getElementById("slip-count").textContent = SLIP.length ? ` (${SLIP.length})` : "";
});

document.getElementById("slip").addEventListener("input", e => {
  const input = e.target.closest("input[data-slip-price]");
  if (!input) return;
  const i = parseInt(input.closest("tr").dataset.slip, 10);
  SLIP[i].price = parseFloat(input.value) || 0;
  clearTimeout(window.__slipTimer);
  window.__slipTimer = setTimeout(slipView, 200);
});

document.getElementById("smin").addEventListener("input", standoutSoon);
document.getElementById("stop").addEventListener("input", standoutSoon);

/* Type a bookmaker's price and the row says whether it clears the bar.
   The verdict uses the conservative estimate, not the point estimate: it
   should be hard to get a yes, because most of what a scan like this turns
   up is noise wearing a good record. */
document.getElementById("standout").addEventListener("input", e => {
  const input = e.target.closest("input[data-price]");
  if (!input) return;

  const row = input.closest("tr");
  const cell = row.querySelector("[data-verdict]");
  const price = parseFloat(input.value);

  if (!price || price <= 1) {
    cell.textContent = "";
    cell.className = "verdict";
    return;
  }

  const pLow = parseFloat(row.dataset.plow);
  const minPrice = parseFloat(row.dataset.min);
  const fair = parseFloat(row.dataset.fair);
  const edge = (price * pLow - 1) * 100;

  if (price >= minPrice) {
    cell.className = "verdict yes";
    cell.textContent = `Clears, +${edge.toFixed(1)}%`;
  } else if (price >= fair) {
    cell.className = "verdict thin";
    cell.textContent = "Thin, sample too small";
  } else {
    cell.className = "verdict no";
    cell.textContent = "Under fair value";
  }
});

applyFixture();
"""


def build_html(payload: dict) -> str:
    first = payload["fixtures"][0]
    fixture = first["fixture"]
    names = [team["name"] for team in first["teams"]]

    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    bettable = json.dumps(sorted(markets.BETTABLE_STATS))
    count = len(payload["fixtures"])
    scope = f"{count} fixtures" if count > 1 else "1 fixture"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{fixture['home']} v {fixture['away']}: hit rates</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<div class="back-bar"><a class="back" href="../index.html">&lsaquo;&nbsp; All fixtures</a></div>

<header>
  <div class="competition" id="competition">{fixture.get('competition', 'Football')}</div>
  <h1 id="title">{fixture['home']} v {fixture['away']}</h1>
  <div class="kickoff" id="kickoff">{fixture.get('date', '')}</div>
</header>

<div class="controls">
  <div class="control-group" id="fixture-group">
    <span class="control-label">Fixture</span>
    <select id="fixture"></select>
    <div class="seg"><button type="button" id="show-past" aria-pressed="false">All upcoming</button></div>
  </div>

  <div class="control-group">
    <span class="control-label">Matches</span>
    <div class="seg">
      <button type="button" data-games="5" aria-pressed="false">5</button>
      <button type="button" data-games="10" aria-pressed="true">10</button>
      <button type="button" data-games="99" aria-pressed="false">All</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Venue</span>
    <div class="seg">
      <button type="button" data-venue="all" aria-pressed="true">All</button>
      <button type="button" data-venue="home" aria-pressed="false">Home</button>
      <button type="button" data-venue="away" aria-pressed="false">Away</button>
    </div>
  </div>

  <div class="control-group" id="tier-group" hidden>
    <span class="control-label">Opposition</span>
    <div class="seg">
      <button type="button" data-tier="all" aria-pressed="true">All</button>
      <button type="button" data-tier="top" aria-pressed="false"
              title="Sides that finished in the top six last season">Top 6</button>
      <button type="button" data-tier="upper" aria-pressed="false"
              title="Finished 7th to 11th last season">Upper</button>
      <button type="button" data-tier="lower" aria-pressed="false"
              title="Finished 12th to 17th last season">Lower</button>
      <button type="button" data-tier="bottom" aria-pressed="false"
              title="Finished 18th or below, plus every promoted side">Bottom</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Period</span>
    <div class="seg">
      <button type="button" data-period="ALL" aria-pressed="true">Full</button>
      <button type="button" data-period="1ST" aria-pressed="false">1st</button>
      <button type="button" data-period="2ND" aria-pressed="false">2nd</button>
    </div>
  </div>

  <div class="legend">
    <span class="legend-item"><span class="swatch" style="background:var(--team-1)"></span><span id="legend-0">{names[0]}</span></span>
    <span class="legend-item"><span class="swatch" style="background:var(--team-2)"></span><span id="legend-1">{names[1]}</span></span>
  </div>
</div>

<div class="controls">
  <div class="control-group">
    <span class="control-label">Sample</span>
    <div class="seg">
      <button type="button" data-source="form" aria-pressed="true">Recent form</button>
      <button type="button" data-source="h2h" aria-pressed="false">Head to head</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Team</span>
    <div class="seg">
      <button type="button" data-focus="both" aria-pressed="true">Both</button>
      <button type="button" data-focus="0" aria-pressed="false" id="focus-0">Home</button>
      <button type="button" data-focus="1" aria-pressed="false" id="focus-1">Away</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Measure</span>
    <div class="seg">
      <button type="button" data-measure="for" aria-pressed="true">For</button>
      <button type="button" data-measure="against" aria-pressed="false">Against</button>
      <button type="button" data-measure="matchup" aria-pressed="false">Matchup</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Stats</span>
    <div class="seg">
      <button type="button" data-scope="core" aria-pressed="true">Main</button>
      <button type="button" data-scope="all" aria-pressed="false">All</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Order</span>
    <div class="seg">
      <button type="button" data-sort="default" aria-pressed="true">Standard</button>
      <button type="button" data-sort="strongest" aria-pressed="false">Strongest first</button>
    </div>
  </div>

  <div class="control-group">
    <div class="seg">
      <button type="button" id="strong-only" aria-pressed="false"
              title="Only stats where a team is at 80% or above, or 20% or below">Strong only</button>
      <button type="button" id="reset" title="Put every line back to its suggested value">Reset lines</button>
      <button type="button" id="theme">Theme</button>
    </div>
  </div>
</div>

<div class="tabs" role="tablist">
  <button type="button" data-tab="team" aria-selected="true">Team stats</button>
  <button type="button" data-tab="players" aria-selected="false">Players</button>
  <button type="button" data-tab="best" aria-selected="false">Best bets</button>
  <button type="button" data-tab="standout" aria-selected="false">Standout lines</button>
  <button type="button" data-tab="slip" aria-selected="false">My slip<span id="slip-count"></span></button>
</div>

<div class="panel" data-panel="team">
  <div id="mismatch"></div>
  <div class="board" id="board"></div>
</div>

<div class="panel" data-panel="players" hidden>
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Stat</span>
      <select id="pstat"></select>
    </div>
    <div class="control-group">
      <span class="control-label">Over</span>
      <input class="num-input" id="pline" type="number" step="1" min="0.5" value="0.5"
             aria-label="Player line">
    </div>
    <div class="control-group">
      <span class="control-label">Min apps</span>
      <input class="num-input" id="pmin" type="number" step="1" min="1" value="3"
             aria-label="Minimum appearances">
    </div>
  </div>
  <p class="note">
    Full match only: SofaScore does not publish player numbers by half.
    Players who have left the club are excluded.
  </p>
  <div id="players"></div>
</div>

<div class="panel" data-panel="best" hidden>
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Min matches each side</span>
      <input class="num-input" id="bmin" type="number" step="1" min="3" value="4"
             aria-label="Minimum matches on each side">
    </div>
    <div class="control-group">
      <span class="control-label">Per competition</span>
      <input class="num-input" id="btop" type="number" step="1" min="1" max="25" value="10"
             aria-label="How many per competition">
    </div>
    <div class="control-group">
      <span class="control-label">Order</span>
      <div class="seg">
        <button type="button" data-border="evidence" aria-pressed="true"
                title="Strongest combined record first">Evidence</button>
        <button type="button" data-border="likely" aria-pressed="false"
                title="Shortest price first: the biggest mismatches">Most likely</button>
        <button type="button" data-border="price" aria-pressed="false"
                title="Longest price first: the ones that actually pay">Best price</button>
      </div>
    </div>
  </div>
  <div id="bestbets"></div>
</div>

<div class="panel" data-panel="standout" hidden>
  <div class="controls">
    <div class="control-group">
      <span class="control-label">Min matches</span>
      <input class="num-input" id="smin" type="number" step="1" min="3" value="8"
             aria-label="Minimum matches">
    </div>
    <div class="control-group">
      <span class="control-label">Show</span>
      <input class="num-input" id="stop" type="number" step="5" min="5" value="20"
             aria-label="How many to show">
    </div>
    <div class="control-group">
      <div class="seg">
        <button type="button" id="include-mismatched" aria-pressed="false"
                title="Include teams whose record was built in another competition">
          Include other competitions</button>
      </div>
    </div>
  </div>
  <div id="standout"></div>
</div>

<div class="panel" data-panel="slip" hidden>
  <p class="note">
    Each selection scored out of 100 on four things: how far the price beats what
    the evidence supports (45), how much data sits behind it (25), whether the
    opponent-adjusted projection agrees (15), and whether the record was built
    against the right standard of opposition (15). The breakdown is always shown,
    because a score you cannot interrogate is just an opinion with a number on it.
  </p>
  <div id="slip"></div>
</div>

<footer>
  <span id="sample"></span>
  Dashed line on each chart marks the quoted line. Numbers run oldest to newest,
  left to right. Shaded rows are 80% or above, or 20% or below.
  Matchup puts the home side's own numbers against the away side's conceded ones,
  so you can see whether an attack meets a leak.
  Where shown, "proj" is what the fitted ratings expect in this fixture against
  this opponent, which is a different question from what the team has averaged.
  Built {generated} from SofaScore data, covering {scope}.
</footer>

</div>
<script>{JS.replace("__PAYLOAD__", json.dumps(payload)).replace("__BETTABLE__", bettable)}</script>
</body>
</html>
"""


def write_report(payload: dict, path: Path) -> Path:
    path.write_text(build_html(payload), encoding="utf-8")
    return path
