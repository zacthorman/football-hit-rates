"""
Render a fixture's hit-rate data as a single self-contained HTML file.

Everything is inlined, so the file works offline, opens anywhere, and can be
emailed. The match data is embedded as JSON and the filtering happens in the
browser, so switching between last 5 and last 10, or home and away, is
instant and needs no refetch.
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
  --team-1: #2a78d6;
  --team-2: #eb6834;
  --control-bg: #ffffff;
  --control-active: #0b0b0b;
  --control-active-text: #ffffff;
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
  --team-1: #3987e5;
  --team-2: #d95926;
  --control-bg: #222220;
  --control-active: #ffffff;
  --control-active-text: #0b0b0b;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 32px 20px 64px;
  background: var(--page);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 14px;
  line-height: 1.5;
}

.wrap { max-width: 1240px; margin: 0 auto; }

.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-1);
}

header { margin-bottom: 24px; }

.competition {
  font-size: 12px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 6px;
}

h1 { font-size: 26px; font-weight: 650; margin: 0 0 4px; letter-spacing: -0.01em; }

.kickoff { color: var(--text-secondary); font-size: 13px; }

.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: center;
  padding: 14px 16px;
  margin-bottom: 20px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.control-group { display: flex; align-items: center; gap: 8px; }

.control-label {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}

.seg { display: flex; border: 1px solid var(--border); border-radius: 7px; overflow: hidden; }

.seg button {
  border: 0;
  background: var(--control-bg);
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  padding: 5px 12px;
  cursor: pointer;
}
.seg button + button { border-left: 1px solid var(--border); }
.seg button:disabled { opacity: 0.4; cursor: not-allowed; }
.seg button[aria-pressed="true"] {
  background: var(--control-active);
  color: var(--control-active-text);
  font-weight: 600;
}

.legend { display: flex; gap: 18px; margin-left: auto; align-items: center; }
.legend-item { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--text-secondary); }
.swatch { width: 11px; height: 11px; border-radius: 3px; }

table { width: 100%; border-collapse: collapse; background: var(--surface-1); }

thead th {
  text-align: left;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 600;
  padding: 12px 14px;
  border-bottom: 1px solid var(--grid);
  white-space: nowrap;
}
thead th.team-head { color: var(--text-primary); font-size: 13px; text-transform: none; letter-spacing: 0; }

tbody td { padding: 11px 14px; border-bottom: 1px solid var(--grid); vertical-align: middle; }
tbody tr:last-child td { border-bottom: 0; }

.stat-name { font-weight: 550; white-space: nowrap; }

.stepper { display: flex; align-items: center; gap: 3px; }
.stepper button {
  width: 24px; height: 26px;
  border: 1px solid var(--border);
  background: var(--control-bg);
  color: var(--text-secondary);
  border-radius: 6px;
  font: inherit;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  padding: 0;
}
.stepper button:hover { color: var(--text-primary); }
.stepper input {
  width: 56px; height: 26px;
  border: 1px solid var(--border);
  background: var(--control-bg);
  color: var(--text-primary);
  border-radius: 6px;
  font: inherit;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  text-align: center;
  padding: 0 2px;
}
.stepper input.edited {
  border-color: var(--text-primary);
  font-weight: 650;
}
.stepper input::-webkit-outer-spin-button,
.stepper input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.stepper input[type=number] { -moz-appearance: textfield; }

.cell { display: flex; align-items: center; gap: 12px; }

.rate { min-width: 88px; }
.rate-top { display: flex; align-items: baseline; gap: 6px; }
.rate-pct { font-size: 16px; font-weight: 650; font-variant-numeric: tabular-nums; }
.rate-frac { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.rate-bar { height: 4px; border-radius: 2px; background: var(--grid); margin-top: 5px; overflow: hidden; }
.rate-fill { height: 100%; border-radius: 2px; }

.seq { font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums;
       letter-spacing: 0.02em; white-space: nowrap; }

.divider { border-left: 1px solid var(--grid); }

.empty { color: var(--muted); font-size: 13px; }

.tabs { display: flex; gap: 4px; margin-bottom: 14px; }
.tabs button {
  border: 1px solid var(--border);
  background: var(--control-bg);
  color: var(--text-secondary);
  font: inherit; font-size: 14px; font-weight: 550;
  padding: 7px 16px; border-radius: 8px; cursor: pointer;
}
.tabs button[aria-selected="true"] {
  background: var(--control-active);
  color: var(--control-active-text);
  border-color: var(--control-active);
}

.panel[hidden] { display: none; }

select {
  height: 30px;
  border: 1px solid var(--border);
  background: var(--control-bg);
  color: var(--text-primary);
  border-radius: 7px;
  font: inherit; font-size: 13px;
  padding: 0 8px;
}

.num-input {
  width: 52px; height: 30px;
  border: 1px solid var(--border);
  background: var(--control-bg);
  color: var(--text-primary);
  border-radius: 7px;
  font: inherit; font-size: 13px;
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.team-block { margin-bottom: 22px; }
.team-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 15px; font-weight: 650; margin: 0 0 8px;
}
.player-name { font-weight: 550; white-space: nowrap; }
.pos { color: var(--muted); font-size: 12px; margin-left: 6px; }
.num { font-variant-numeric: tabular-nums; white-space: nowrap; }

.tooltip {
  position: fixed;
  pointer-events: none;
  background: var(--text-primary);
  color: var(--surface-1);
  padding: 6px 9px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  opacity: 0;
  transition: opacity 0.1s;
  z-index: 10;
  white-space: nowrap;
}

footer { margin-top: 20px; color: var(--muted); font-size: 12px; }
footer code { font-size: 11px; }

@media (max-width: 820px) {
  .legend { margin-left: 0; }
  .seq { display: none; }
}
"""

JS = """
const ALL = __PAYLOAD__;

let DATA = ALL.fixtures[0];
let SUGGESTED = {};

let games = 10;
let venue = "all";
let tab = "team";
let period = "ALL";

const VARS = ["--team-1", "--team-2"];
const rowsEl = document.getElementById("rows");

const tip = document.createElement("div");
tip.className = "tooltip";
document.body.appendChild(tip);

/* Lines are always quoted at .5 so a match can never land exactly on one.
   Stepping moves by a whole goal/shot/corner, which is how you actually
   think about it: 13.5 to 14.5, not 13.5 to 14. */
function snapLine(value) {
  return Math.max(0.5, Math.round(value - 0.5) + 0.5);
}

function filtered(records) {
  let rows = records;
  if (venue !== "all") rows = rows.filter(r => r.venue === venue);
  return rows.slice(-games);
}

function hasPlayers() {
  return Array.isArray(DATA.players) && DATA.players.some(r => r.length);
}

/* Team records store stats as {period: {name: value}}. Players are flat,
   because SofaScore only reports player numbers for the whole match. */
function statValue(record, statName) {
  const bucket = record.stats[period] || record.stats;
  return bucket ? bucket[statName] : undefined;
}

function sparkline(rows, statName, line, colorVar) {
  const points = rows
    .map(r => ({ v: statValue(r, statName), r }))
    .filter(p => p.v !== undefined && p.v !== null);

  if (points.length < 2) return '<span class="empty">not enough data</span>';

  const W = 132, H = 34, PAD = 5;
  const vals = points.map(p => p.v).concat([line]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = (hi - lo) || 1;

  const x = i => PAD + (i * (W - 2 * PAD)) / (points.length - 1);
  const y = v => H - PAD - ((v - lo) / span) * (H - 2 * PAD);

  const path = points.map((p, i) => `${x(i)},${y(p.v)}`).join(" ");
  const lineY = y(line);

  const dots = points.map((p, i) =>
    `<circle cx="${x(i)}" cy="${y(p.v)}" r="3.5" fill="var(${colorVar})"
       stroke="var(--surface-1)" stroke-width="2"
       data-tip="${p.r.date} ${p.r.venue === 'home' ? 'H' : 'A'} v ${p.r.opponent} &middot; ${p.v}"
     ></circle>`
  ).join("");

  return `<svg width="${W}" height="${H}" role="img"
      aria-label="${statName} over the selected matches">
    <line x1="0" y1="${lineY}" x2="${W}" y2="${lineY}"
      stroke="var(--baseline)" stroke-width="1" stroke-dasharray="3 3"></line>
    <polyline points="${path}" fill="none" stroke="var(${colorVar})"
      stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline>
    ${dots}
  </svg>`;
}

function rateCell(rows, statName, line, colorVar) {
  const vals = rows.map(r => statValue(r, statName))
                   .filter(v => v !== undefined && v !== null);
  if (!vals.length) return '<span class="empty">no data</span>';

  const hits = vals.filter(v => v > line).length;
  const pct = Math.round((hits / vals.length) * 100);
  const seq = vals.map(v => (Number.isInteger(v) ? v : v.toFixed(1))).join(", ");

  return `<div class="cell">
    <div class="rate">
      <div class="rate-top">
        <span class="rate-pct">${pct}%</span>
        <span class="rate-frac">${hits}/${vals.length}</span>
      </div>
      <div class="rate-bar"><div class="rate-fill"
        style="width:${pct}%;background:var(${colorVar})"></div></div>
    </div>
    ${sparkline(rows, statName, line, colorVar)}
    <span class="seq">${seq}</span>
  </div>`;
}

/* Recompute one stat's two cells only. Leaves its input alone, so typing
   in the box doesn't destroy your own focus mid-keystroke. */
function updateRow(tr) {
  const name = tr.dataset.stat;
  const line = DATA.lines[period][name];
  const teamRows = DATA.records.map(filtered);

  tr.querySelectorAll("td.team-cell").forEach((td, i) => {
    td.innerHTML = rateCell(teamRows[i], name, line, VARS[i]);
  });

  tr.querySelector("input[data-line]").classList
    .toggle("edited", line !== SUGGESTED[period][name]);
}

function updateAll() {
  rowsEl.querySelectorAll("tr[data-stat]").forEach(updateRow);
  const teamRows = DATA.records.map(filtered);
  document.getElementById("sample").textContent =
    teamRows.map((r, i) => `${DATA.teams[i].name}: ${r.length} matches`)
            .join(" \\u00b7 ") + ".";
}

function setLine(tr, value) {
  const clean = snapLine(value);
  DATA.lines[period][tr.dataset.stat] = clean;
  tr.querySelector("input[data-line]").value = clean;
  updateRow(tr);
}

function render() {
  const lines = DATA.lines[period] || {};
  const stats = (DATA.stats[period] || []).filter(n => lines[n] !== undefined);

  if (!stats.length) {
    rowsEl.innerHTML =
      '<tr><td colspan="4" class="empty">No stats for this period.</td></tr>';
    return;
  }

  rowsEl.innerHTML = stats.map(name => `
    <tr data-stat="${name}">
      <td class="stat-name">${name}</td>
      <td>
        <div class="stepper">
          <button data-step="-1" title="Lower the line by 1">&minus;</button>
          <input type="number" step="1" min="0.5" value="${lines[name]}"
                 data-line aria-label="Line for ${name}">
          <button data-step="1" title="Raise the line by 1">+</button>
        </div>
      </td>
      <td class="team-cell"></td>
      <td class="team-cell divider"></td>
    </tr>`).join("");

  updateAll();
}

/* ---------------------------------------------------------------- players */

function playerView() {
  if (!hasPlayers()) return;

  const stat = document.getElementById("pstat").value;
  const line = parseFloat(document.getElementById("pline").value) || 0;
  const minApps = parseInt(document.getElementById("pmin").value, 10) || 1;

  const blocks = DATA.players.map((records, teamIndex) => {
    // Scope player rows to exactly the matches the team filter is showing,
    // so "last 5, home only" means the same thing in both tabs.
    const allowed = new Set(filtered(DATA.records[teamIndex]).map(m => m.id));
    const rows = records.filter(r => allowed.has(r.match_id));

    const byPlayer = new Map();
    for (const r of rows) {
      if (!byPlayer.has(r.player)) byPlayer.set(r.player, []);
      byPlayer.get(r.player).push(r);
    }

    const colorVar = VARS[teamIndex];

    const built = [...byPlayer.entries()].map(([name, gamesPlayed]) => {
      const vals = gamesPlayed
        .map(g => g.stats[stat])
        .filter(v => v !== undefined && v !== null);
      if (vals.length < minApps) return null;

      const hits = vals.filter(v => v > line).length;
      const pct = Math.round((hits / vals.length) * 100);
      const avg = vals.reduce((a, b) => a + b, 0) / vals.length;

      return { name, pos: gamesPlayed[0].position || "", gamesPlayed, vals, hits, pct, avg };
    }).filter(Boolean);

    built.sort((a, b) => b.pct - a.pct || b.vals.length - a.vals.length);

    const title = `<h2 class="team-title">
        <span class="swatch" style="background:var(${colorVar})"></span>
        ${DATA.teams[teamIndex].name}
      </h2>`;

    if (!built.length) {
      return `<div class="team-block">${title}
        <p class="empty">No player met the minimum appearances for this selection.</p>
      </div>`;
    }

    const fmt = v => (Number.isInteger(v) ? v : v.toFixed(1));

    const body = built.map(p => {
      const fakeRows = p.gamesPlayed.map(g => ({
        date: g.date, venue: g.venue, opponent: g.opponent,
        stats: { [stat]: g.stats[stat] },
      }));
      return `<tr>
        <td class="player-name">${p.name}<span class="pos">${p.pos}</span></td>
        <td class="num">${p.vals.length}</td>
        <td class="num">${p.avg.toFixed(1)}</td>
        <td>
          <div class="cell">
            <div class="rate">
              <div class="rate-top">
                <span class="rate-pct">${p.pct}%</span>
                <span class="rate-frac">${p.hits}/${p.vals.length}</span>
              </div>
              <div class="rate-bar"><div class="rate-fill"
                style="width:${p.pct}%;background:var(${colorVar})"></div></div>
            </div>
            ${sparkline(fakeRows, stat, line, colorVar)}
            <span class="seq">${p.vals.map(fmt).join(", ")}</span>
          </div>
        </td>
      </tr>`;
    }).join("");

    return `<div class="team-block">${title}
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Player</th><th>Apps</th><th>Avg</th>
          <th>${stat} over ${line}</th>
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

  // A fixture may be missing a half if SofaScore never published it.
  if (!DATA.lines[period]) period = "ALL";
  document.querySelectorAll("[data-period]").forEach(b => {
    b.disabled = !DATA.lines[b.dataset.period];
    b.setAttribute("aria-pressed", b.dataset.period === period);
  });

  document.getElementById("competition").textContent = DATA.fixture.competition;
  document.getElementById("title").textContent =
    `${DATA.fixture.home} v ${DATA.fixture.away}`;
  document.getElementById("kickoff").textContent = DATA.fixture.date || "";

  document.getElementById("head-0").textContent = DATA.teams[0].name;
  document.getElementById("head-1").textContent = DATA.teams[1].name;
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

// All row handlers are delegated to the table body, so they survive every
// re-render without needing to be re-attached.

rowsEl.addEventListener("click", e => {
  const btn = e.target.closest("button[data-step]");
  if (!btn) return;
  const tr = btn.closest("tr[data-stat]");
  setLine(tr, DATA.lines[tr.dataset.stat] + parseFloat(btn.dataset.step));
});

rowsEl.addEventListener("input", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  const value = parseFloat(input.value);
  if (Number.isNaN(value)) return;          // half-typed, leave it alone
  const tr = input.closest("tr[data-stat]");
  DATA.lines[period][tr.dataset.stat] = Math.max(0, value);
  updateRow(tr);
});

// Snap only once they've finished, so it doesn't fight them mid-type.
rowsEl.addEventListener("change", e => {
  const input = e.target.closest("input[data-line]");
  if (!input) return;
  setLine(input.closest("tr[data-stat]"), parseFloat(input.value) || 0.5);
});

rowsEl.addEventListener("mouseover", e => {
  const dot = e.target.closest("circle[data-tip]");
  if (!dot) return;
  tip.innerHTML = dot.dataset.tip;
  tip.style.opacity = "1";
});
rowsEl.addEventListener("mousemove", e => {
  if (tip.style.opacity !== "1") return;
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top = (e.clientY - 34) + "px";
});
rowsEl.addEventListener("mouseout", e => {
  if (e.target.closest("circle[data-tip]")) tip.style.opacity = "0";
});

const playersEl = document.getElementById("players");
playersEl.addEventListener("mouseover", e => {
  const dot = e.target.closest("circle[data-tip]");
  if (!dot) return;
  tip.innerHTML = dot.dataset.tip;
  tip.style.opacity = "1";
});
playersEl.addEventListener("mousemove", e => {
  if (tip.style.opacity !== "1") return;
  tip.style.left = (e.clientX + 12) + "px";
  tip.style.top = (e.clientY - 34) + "px";
});
playersEl.addEventListener("mouseout", e => {
  if (e.target.closest("circle[data-tip]")) tip.style.opacity = "0";
});

document.querySelectorAll("[data-games]").forEach(btn => {
  btn.addEventListener("click", () => {
    games = parseInt(btn.dataset.games, 10);
    document.querySelectorAll("[data-games]").forEach(b =>
      b.setAttribute("aria-pressed", b === btn));
    updateAll();
    if (tab === "players") playerView();
  });
});

document.querySelectorAll("[data-venue]").forEach(btn => {
  btn.addEventListener("click", () => {
    venue = btn.dataset.venue;
    document.querySelectorAll("[data-venue]").forEach(b =>
      b.setAttribute("aria-pressed", b === btn));
    updateAll();
    if (tab === "players") playerView();
  });
});

document.querySelectorAll("[data-tab]").forEach(btn => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

document.getElementById("reset").addEventListener("click", () => {
  for (const key of Object.keys(SUGGESTED)) {
    DATA.lines[key] = Object.assign({}, SUGGESTED[key]);
  }
  rowsEl.querySelectorAll("tr[data-stat]").forEach(tr => {
    tr.querySelector("input[data-line]").value = DATA.lines[period][tr.dataset.stat];
    updateRow(tr);
  });
});

document.querySelectorAll("[data-period]").forEach(btn => {
  btn.addEventListener("click", () => {
    period = btn.dataset.period;
    document.querySelectorAll("[data-period]").forEach(b =>
      b.setAttribute("aria-pressed", b === btn));
    render();
  });
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

const pstat = document.getElementById("pstat");
pstat.addEventListener("change", () => {
  document.getElementById("pline").value = DATA.playerLines[pstat.value] ?? 0.5;
  playerView();
});
document.getElementById("pline").addEventListener("input", playerView);
document.getElementById("pmin").addEventListener("input", playerView);

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
      <button data-games="5" aria-pressed="false">Last 5</button>
      <button data-games="10" aria-pressed="true">Last 10</button>
      <button data-games="99" aria-pressed="false">All</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Venue</span>
    <div class="seg">
      <button data-venue="all" aria-pressed="true">All</button>
      <button data-venue="home" aria-pressed="false">Home</button>
      <button data-venue="away" aria-pressed="false">Away</button>
    </div>
  </div>

  <div class="control-group">
    <span class="control-label">Period</span>
    <div class="seg">
      <button data-period="ALL" aria-pressed="true">Full</button>
      <button data-period="1ST" aria-pressed="false">1st half</button>
      <button data-period="2ND" aria-pressed="false">2nd half</button>
    </div>
  </div>

  <div class="control-group">
    <div class="seg">
      <button id="reset" title="Put every line back to its suggested value">Reset lines</button>
      <button id="theme">Theme</button>
    </div>
  </div>

  <div class="legend">
    <span class="legend-item"><span class="swatch" style="background:var(--team-1)"></span><span id="legend-0">{names[0]}</span></span>
    <span class="legend-item"><span class="swatch" style="background:var(--team-2)"></span><span id="legend-1">{names[1]}</span></span>
  </div>
</div>

<div class="tabs" role="tablist">
  <button data-tab="team" aria-selected="true">Team stats</button>
  <button data-tab="players" aria-selected="false">Players</button>
</div>

<div class="panel" data-panel="team">
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Stat</th>
        <th>Line</th>
        <th class="team-head" id="head-0">{names[0]}</th>
        <th class="team-head divider" id="head-1">{names[1]}</th>
      </tr>
    </thead>
    <tbody id="rows"></tbody>
  </table>
  </div>
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
  <p class="empty" style="margin:0 0 14px">
    Player numbers are full match only. SofaScore does not publish them by half.
  </p>
  <div id="players"></div>
</div>

<footer>
  <span id="sample"></span>
  Dashed line on each chart marks the quoted line. Numbers run oldest to newest, left to right.
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
