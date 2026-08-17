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
let tab = "team";
let period = "ALL";
let scope = "core";
let sort = "default";
let strongOnly = false;
let source = "form";      // "form" = recent matches, "h2h" = previous meetings

// A hit rate this far from an even split is worth your attention. Below it,
// ten matches simply cannot separate signal from noise.
const STRONG_HIGH = 80;
const STRONG_LOW = 20;

const CORE_STATS = [
  "Total shots", "Shots on target", "Corner kicks",
  "Offsides", "Fouls", "Yellow cards", "Throw-ins",
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

function filtered(records) {
  let rows = records;
  if (venue !== "all") rows = rows.filter(r => r.venue === venue);
  return rows.slice(-games);
}

function hasPlayers() {
  return Array.isArray(DATA.players) && DATA.players.some(r => r.length);
}

/* Team records store stats as {period: {name: value}}. Player records are
   flat, because SofaScore only reports player numbers for the whole match. */
function statValue(record, statName) {
  const bucket = record.stats[period] || record.stats;
  return bucket ? bucket[statName] : undefined;
}

function summarise(rows, statName, line) {
  const vals = rows.map(r => statValue(r, statName))
                   .filter(v => v !== undefined && v !== null);
  if (!vals.length) return null;
  const hits = vals.filter(v => v > line).length;
  return { vals, hits, pct: Math.round((hits / vals.length) * 100) };
}

function sparkline(rows, statName, line, colorVar, w) {
  const points = rows
    .map(r => ({ v: statValue(r, statName), r }))
    .filter(p => p.v !== undefined && p.v !== null);

  if (points.length < 2) return "";

  const W = w || 116, H = 38, PAD = 6;
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
    const tipText = `${p.r.date} ${p.r.venue === 'home' ? 'H' : 'A'} v ${p.r.opponent}`
      + ` &middot; ${p.v} &middot; ${hit ? 'over' : 'under'} ${line}`;
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
  const tag = `<span class="team-tag">
      <span class="swatch" style="background:var(${colorVar})"></span>
      ${DATA.teams[index].name}
    </span>`;

  const s = summarise(rows, statName, line);
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
    ${sparkline(rows, statName, line, colorVar)}
    <span class="seq">${seq}</span>
  </div>`;
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
    return Math.max(...teamRows.map(rows => {
      const s = summarise(rows, name, line);
      return s ? Math.abs(s.pct - 50) : 0;
    }));
  };

  if (strongOnly) {
    stats = stats.filter(n => {
      const line = lines[n];
      return teamRows.some(rows => {
        const s = summarise(rows, n, line);
        return s && (s.pct >= STRONG_HIGH || s.pct <= STRONG_LOW);
      });
    });
  }

  if (sort === "strongest") {
    stats = stats.slice().sort((a, b) => strength(b) - strength(a));
  }

  return stats;
}

function updateRow(row) {
  const name = row.dataset.stat;
  const line = activeLines()[name];
  const teamRows = activeRecords().map(filtered);

  row.querySelectorAll(".side").forEach(el => el.remove());
  const middle = row.querySelector(".middle");
  middle.insertAdjacentHTML("beforebegin", sideHtml(teamRows[0], name, line, 0));
  middle.insertAdjacentHTML("afterend", sideHtml(teamRows[1], name, line, 1));

  const strong = teamRows.some(rows => {
    const s = summarise(rows, name, line);
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
      </div>
    </div>`).join("");

  updateAll();
}

function updateSample() {
  const teamRows = activeRecords().map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
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

  document.getElementById("competition").textContent = DATA.fixture.competition;
  document.getElementById("title").textContent =
    `${DATA.fixture.home} v ${DATA.fixture.away}`;
  document.getElementById("kickoff").textContent = DATA.fixture.date || "";
  document.getElementById("legend-0").textContent = DATA.teams[0].name;
  document.getElementById("legend-1").textContent = DATA.teams[1].name;
  document.title = `${DATA.fixture.home} v ${DATA.fixture.away}: hit rates`;

  fillPlayerStats();
  render();
  if (tab === "players") playerView();
}

function switchTab(target) {
  tab = target;
  document.querySelectorAll("[data-tab]").forEach(b =>
    b.setAttribute("aria-selected", b.dataset.tab === target));
  document.querySelectorAll(".panel").forEach(p =>
    p.hidden = p.dataset.panel !== target);
  if (target === "players") playerView();
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

segment("games", v => { games = parseInt(v, 10); render(); if (tab === "players") playerView(); });
segment("venue", v => { venue = v; render(); if (tab === "players") playerView(); });
segment("period", v => { period = v; render(); });
segment("source", v => { source = v; render(); });
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

const fixtureSelect = document.getElementById("fixture");
if (ALL.fixtures.length > 1) {
  fixtureSelect.innerHTML = ALL.fixtures
    .map((f, i) => `<option value="${i}">${f.fixture.home} v ${f.fixture.away}</option>`)
    .join("");
  fixtureSelect.addEventListener("change", () => {
    DATA = ALL.fixtures[parseInt(fixtureSelect.value, 10)];
    applyFixture();
  });
} else {
  document.getElementById("fixture-group").hidden = true;
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

applyFixture();
"""


def build_html(payload: dict) -> str:
    first = payload["fixtures"][0]
    fixture = first["fixture"]
    names = [team["name"] for team in first["teams"]]

    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
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

<header>
  <div class="competition" id="competition">{fixture.get('competition', 'Football')}</div>
  <h1 id="title">{fixture['home']} v {fixture['away']}</h1>
  <div class="kickoff" id="kickoff">{fixture.get('date', '')}</div>
</header>

<div class="controls">
  <div class="control-group" id="fixture-group">
    <span class="control-label">Fixture</span>
    <select id="fixture"></select>
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
</div>

<div class="panel" data-panel="team">
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

<footer>
  <span id="sample"></span>
  Dashed line on each chart marks the quoted line. Numbers run oldest to newest,
  left to right. Shaded rows are 80% or above, or 20% or below.
  Built {generated} from SofaScore data, covering {scope}.
</footer>

</div>
<script>{JS.replace("__PAYLOAD__", json.dumps(payload))}</script>
</body>
</html>
"""


def write_report(payload: dict, path: Path) -> Path:
    path.write_text(build_html(payload), encoding="utf-8")
    return path
