// Learn page: animated minimax / alpha-beta on a small tree, move ordering comparison,
// live evaluation breakdowns and the horizon-effect example. All written for this project.

import { ChessBoard } from "./board.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const INF = Infinity;
const fmt = (v) => (v === INF ? "+∞" : v === -INF ? "−∞" : v === undefined || v === null ? "" : String(v));

// ====================================================================== theme

function applyTheme(t) { if (t) document.documentElement.dataset.theme = t; }
try { applyTheme(localStorage.getItem("theme")); } catch { /* ignore */ }
$("btn-theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme;
  const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("theme", next); } catch { /* ignore */ }
});

// ====================================================================== lesson 1: growth

(function growth() {
  const units = [[60 * 60 * 24 * 365, "years"], [60 * 60 * 24, "days"], [3600, "hours"], [60, "minutes"], [1, "seconds"]];
  const rows = [];
  for (let d = 1; d <= 8; d++) {
    const leaves = 35 ** d;
    const sec = leaves / 15000;
    let time = sec < 1 ? "under a second" : "";
    if (!time) {
      const [size, name] = units.find(([s]) => sec >= s);
      time = `${(sec / size).toLocaleString(undefined, { maximumFractionDigits: 1 })} ${name}`;
    }
    rows.push(`<tr><td>${d}</td><td>${leaves.toLocaleString()}</td><td>${time}</td></tr>`);
  }
  $("growth-body").innerHTML = rows.join("");
})();

// ====================================================================== trees

/** Small seeded random generator so the default tree is always the same. */
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

function makeTree(seed, depth = 3, branching = 3) {
  const rand = rng(seed);
  let leafCount = 0;
  function build(d) {
    if (d === depth) return { value: Math.floor(rand() * 19) - 9, children: [], leafNo: leafCount++ };
    return { children: Array.from({ length: branching }, () => build(d + 1)) };
  }
  return build(0);
}

function minimaxValue(n, max) {
  if (!n.children.length) return n.value;
  const vals = n.children.map((c) => minimaxValue(c, !max));
  return max ? Math.max(...vals) : Math.min(...vals);
}

/** Copy of the tree with children sorted best-first or worst-first for the side to move. */
function reorder(n, max, mode) {
  if (!n.children.length) return { ...n };
  const kids = n.children.map((c) => reorder(c, !max, mode));
  if (mode !== "random") {
    const score = (c) => minimaxValue(c, !max);
    kids.sort((a, b) => (max ? score(b) - score(a) : score(a) - score(b)));
    if (mode === "worst") kids.reverse();
  }
  return { ...n, children: kids };
}

/** Number the nodes in pre-order, give internal nodes letters, record parents/depths. */
function index(root) {
  const nodes = [];
  let letter = 0;
  (function walk(n, parent, depth) {
    n.i = nodes.length;
    n.parent = parent;
    n.depth = depth;
    n.max = depth % 2 === 0;
    n.label = n.children.length ? String.fromCharCode(65 + letter++) : `leaf ${n.value}`;
    nodes.push(n);
    n.children.forEach((c) => walk(c, n, depth + 1));
  })(root, null, 0);
  return nodes;
}

/** Record every step of minimax or alpha-beta: node states + an explanation. */
function trace(root, alphaBeta) {
  const nodes = index(root);
  const totalLeaves = nodes.filter((n) => !n.children.length).length;
  const state = nodes.map(() => ({ s: "idle" }));
  const steps = [];
  let leaves = 0;
  const push = (active, msg, cut = null) =>
    steps.push({ state: state.map((o) => ({ ...o })), active, msg, leaves, cut });

  const markPruned = (n) => { state[n.i].s = "pruned"; n.children.forEach(markPruned); };
  const who = (n) => (n.max ? "MAX (the AI picks the highest)" : "MIN (the opponent picks the lowest)");

  push(-1, alphaBeta
    ? "Alpha-beta starts at the root A with α = −∞ and β = +∞: nothing is guaranteed yet."
    : "Minimax starts at the root A and explores the moves from left to right.");

  function search(n, a, b) {
    const st = state[n.i];
    st.s = "active";
    if (alphaBeta) { st.a = a; st.b = b; }
    if (!n.children.length) {
      leaves++;
      st.v = n.value;
      st.s = "done";
      push(n.i, `A leaf: the evaluation function scores this position ${n.value}.`);
      return n.value;
    }
    push(n.i, `Visit ${n.label}: a ${who(n)}.` + (alphaBeta ? ` It receives α = ${fmt(a)}, β = ${fmt(b)}.` : ""));
    let best = n.max ? -INF : INF;
    for (let k = 0; k < n.children.length; k++) {
      const c = n.children[k];
      const v = search(c, a, b);
      best = n.max ? Math.max(best, v) : Math.min(best, v);
      st.v = best;
      st.s = "active";
      let msg = `Back at ${n.label}: that move is worth ${v}. ${n.label} now has ${best} ` +
        `(the ${n.max ? "highest" : "lowest"} so far).`;
      if (alphaBeta) {
        if (n.max) a = Math.max(a, best); else b = Math.min(b, best);
        st.a = a; st.b = b;
        msg += n.max ? ` α = max(α, ${best}) = ${fmt(a)}.` : ` β = min(β, ${best}) = ${fmt(b)}.`;
      }
      push(n.i, msg);
      if (alphaBeta && a >= b && k < n.children.length - 1) {
        const rest = n.children.slice(k + 1);
        rest.forEach(markPruned);
        const why = n.max
          ? `${n.label} already gives MAX ${best}, at least β = ${fmt(b)}, which MIN can get elsewhere. ` +
            `MIN will never let the game reach ${n.label}, so its other moves cannot matter.`
          : `${n.label} holds MAX to ${best}, no more than α = ${fmt(a)}, which MAX can get elsewhere. ` +
            `MAX will never play into ${n.label}, so its other replies cannot matter.`;
        push(n.i, `✂ Cutoff (α ≥ β): ${why} Skip ${rest.length} move${rest.length > 1 ? "s" : ""}.`, n.i);
        break;
      }
    }
    st.s = "done";
    push(n.i, `${n.label} is finished: value ${best}.`);
    return best;
  }

  const value = search(root, -INF, INF);
  const bestChild = root.children.find((c) => state[c.i].v === value && state[c.i].s === "done");
  push(-1, `Done: the root is worth ${value}, so the AI plays the move to ${bestChild ? bestChild.label : "?"}. ` +
    (alphaBeta ? `Alpha-beta evaluated ${leaves} of ${totalLeaves} leaves and got the same answer as minimax.`
      : `Minimax evaluated all ${leaves} leaves.`));
  return { nodes, steps, totalLeaves, value };
}

// ---------------------------------------------------------------------- drawing

const LEAF_GAP = 34, ROW = 78, PAD = 24, R = 15;

function layoutXY(nodes) {
  const leaves = nodes.filter((n) => !n.children.length);
  leaves.forEach((n, k) => { n.x = PAD + R + k * LEAF_GAP; });
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    if (n.children.length) n.x = (n.children[0].x + n.children[n.children.length - 1].x) / 2;
    n.y = PAD + R + n.depth * ROW;
  }
  const depth = Math.max(...nodes.map((n) => n.depth));
  return { w: PAD * 2 + R * 2 + (leaves.length - 1) * LEAF_GAP, h: PAD * 2 + R * 2 + depth * ROW + 20 };
}

function shape(n) {
  const { x, y } = n;
  if (!n.children.length) return `<rect x="${x - 12}" y="${y - 12}" width="24" height="24" rx="4"/>`;
  return n.max
    ? `<polygon points="${x},${y - 17} ${x + 17},${y + 12} ${x - 17},${y + 12}"/>`
    : `<polygon points="${x},${y + 17} ${x + 17},${y - 12} ${x - 17},${y - 12}"/>`;
}

function drawStep(svgHost, t, step, alphaBeta) {
  const { w, h } = t.size;
  let svg = `<svg class="lt-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="Game tree">`;
  for (const n of t.nodes) {
    for (const c of n.children) {
      const cls = step.state[c.i].s === "pruned" ? "pruned" : step.state[c.i].s === "idle" ? "idle" : "seen";
      svg += `<line class="lt-edge ${cls}" x1="${n.x}" y1="${n.y + 12}" x2="${c.x}" y2="${c.y - 12}"/>`;
    }
  }
  for (const n of t.nodes) {
    const st = step.state[n.i];
    const kind = !n.children.length ? "leaf" : n.max ? "max" : "min";
    const active = step.active === n.i ? " active" : "";
    const cut = step.cut === n.i ? " cut" : "";
    svg += `<g class="lt-node ${kind} ${st.s}${active}${cut}">${shape(n)}`;
    const shown = !n.children.length ? n.value : st.v;
    if (shown !== undefined) {
      svg += `<text class="lt-val" x="${n.x}" y="${n.y + (n.children.length ? (n.max ? 7 : 1) : 4)}">${fmt(shown)}</text>`;
    }
    if (n.children.length) svg += `<text class="lt-label" x="${n.x - 22}" y="${n.y - 8}">${n.label}</text>`;
    if (alphaBeta && n.children.length && st.a !== undefined && st.s !== "pruned") {
      svg += `<text class="lt-ab" x="${n.x}" y="${n.y + 30}">α ${fmt(st.a)} · β ${fmt(st.b)}</text>`;
    }
    svg += `</g>`;
  }
  svg += `</svg>`;
  svgHost.innerHTML = svg;
}

// ---------------------------------------------------------------------- player widget

class TreePlayer {
  constructor(host, alphaBeta) {
    this.host = host;
    this.alphaBeta = alphaBeta;
    this.timer = null;
    host.innerHTML = `
      <div class="lt-scroll"><div class="lt-svg-host"></div></div>
      <p class="lt-msg" aria-live="polite"></p>
      <div class="lt-controls">
        <button class="btn icon" data-act="reset" title="Back to the start">⏮</button>
        <button class="btn icon" data-act="back" title="Previous step">◀</button>
        <button class="btn primary" data-act="play">▶ Play</button>
        <button class="btn icon" data-act="step" title="Next step">▶|</button>
        <button class="btn" data-act="new" title="Random leaf values">🎲 New tree</button>
        <span class="lt-count"></span>
      </div>`;
    this.svgHost = host.querySelector(".lt-svg-host");
    this.msg = host.querySelector(".lt-msg");
    this.count = host.querySelector(".lt-count");
    this.playBtn = host.querySelector('[data-act="play"]');
    host.querySelector(".lt-controls").addEventListener("click", (e) => {
      const act = e.target.closest("button")?.dataset.act;
      if (act === "reset") this.go(0);
      else if (act === "back") this.go(this.k - 1);
      else if (act === "step") this.go(this.k + 1);
      else if (act === "play") this.toggle();
      else if (act === "new") newTree();
    });
  }

  load(root) {
    this.stop();
    this.t = trace(root, this.alphaBeta);
    this.t.size = layoutXY(this.t.nodes);
    this.go(0);
  }

  go(k) {
    const steps = this.t.steps;
    this.k = Math.max(0, Math.min(steps.length - 1, k));
    const step = steps[this.k];
    drawStep(this.svgHost, this.t, step, this.alphaBeta);
    this.msg.innerHTML = `<b>Step ${this.k + 1} / ${steps.length}.</b> ${esc(step.msg)}`;
    this.count.textContent = `Leaves evaluated: ${step.leaves} / ${this.t.totalLeaves}`;
    if (this.k === steps.length - 1) this.stop();
  }

  toggle() { this.timer ? this.stop() : this.play(); }

  play() {
    if (this.k === this.t.steps.length - 1) this.go(0);
    this.playBtn.textContent = "⏸ Pause";
    this.timer = setInterval(() => this.go(this.k + 1), 900);
  }

  stop() {
    clearInterval(this.timer);
    this.timer = null;
    this.playBtn.textContent = "▶ Play";
  }
}

// ---------------------------------------------------------------------- shared tree + ordering

let seed = 7;
let baseTree = makeTree(seed);
const playerMM = new TreePlayer($("player-minimax"), false);
const playerAB = new TreePlayer($("player-alphabeta"), true);
const ordering = () => document.querySelector('input[name="ordering"]:checked').value;

function refresh() {
  playerMM.load(reorder(baseTree, true, "random"));
  playerAB.load(reorder(baseTree, true, ordering()));
  orderingTable();
}

function newTree() {
  seed = Math.floor(Math.random() * 1e9);
  baseTree = makeTree(seed);
  refresh();
}

function countLeaves(root) {
  return trace(root, true).steps.at(-1).leaves;
}

function orderingTable() {
  const total = trace(baseTree, false).totalLeaves;
  const rows = [
    ["Minimax (any ordering)", total],
    ["Alpha-beta, worst move first", countLeaves(reorder(baseTree, true, "worst"))],
    ["Alpha-beta, as generated", countLeaves(reorder(baseTree, true, "random"))],
    ["Alpha-beta, best move first", countLeaves(reorder(baseTree, true, "best"))],
  ];
  const ideal = 3 ** 2 + 3 ** 1 - 1; // Knuth & Moore minimum for b = 3, d = 3
  $("ordering-table").innerHTML = `<thead><tr><th>Search</th><th>Leaves evaluated</th><th></th></tr></thead><tbody>` +
    rows.map(([name, n]) => `<tr><td>${name}</td><td>${n} / ${total}</td>` +
      `<td><span class="bar" style="--w:${(n / total) * 100}%"></span></td></tr>`).join("") +
    `<tr class="muted-row"><td>Theoretical best (b<sup>⌈d/2⌉</sup> + b<sup>⌊d/2⌋</sup> − 1)</td><td>${ideal}</td><td></td></tr></tbody>`;
}

document.querySelectorAll('input[name="ordering"]').forEach((r) => r.addEventListener("change", () => {
  playerAB.load(reorder(baseTree, true, ordering()));
  orderingTable();
  $("alphabeta").scrollIntoView({ behavior: "smooth", block: "start" });
}));

refresh();

// ====================================================================== lesson 5: evaluation lab

const EVAL_POSITIONS = [
  ["Start", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"],
  ["Italian Game", "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"],
  ["Knight up", "r1bqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"],
  ["Exposed king", "r2q1rk1/ppp2ppp/2n5/8/8/2N5/PPP5/R2Q1RK1 w - - 0 15"],
  ["Passed pawn", "8/5k2/8/3P4/8/8/5K2/8 w - - 0 50"],
  ["Bishop pair", "r1bqk2r/pppp1ppp/2n2n2/8/8/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 0 6"],
];

const evalBoard = new ChessBoard($("eval-board"), { onMove: () => {} });

async function evaluate(fen) {
  const res = await fetch("/api/evaluate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fen }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
  return res.json();
}

const pawns = (cp) => (cp >= 0 ? "+" : "−") + (Math.abs(cp) / 100).toFixed(2);

async function showEval(fen) {
  evalBoard.setPosition(fen);
  try {
    const e = await evaluate(fen);
    const max = Math.max(50, ...Object.values(e.terms).map((t) => Math.abs(t.net)).filter((v) => v < 2000));
    $("eval-total").innerHTML = `Total <b>${pawns(e.total)}</b> for White · game phase ${e.phase}/24 ` +
      `(${e.phase > 16 ? "middlegame" : e.phase > 6 ? "late middlegame" : "endgame"})`;
    $("eval-table").innerHTML = `<thead><tr><th>Term</th><th>White</th><th>Black</th><th>Net</th><th></th></tr></thead><tbody>` +
      Object.values(e.terms).map((t) => {
        const w = Math.min(100, (Math.abs(t.net) / max) * 100);
        return `<tr><td>${esc(t.label)}</td><td>${t.white}</td><td>${t.black}</td>` +
          `<td class="${t.net > 0 ? "up" : t.net < 0 ? "down" : ""}">${t.net > 0 ? "+" : ""}${t.net}</td>` +
          `<td class="netbar"><span class="${t.net >= 0 ? "pos" : "neg"}" style="--w:${w / 2}%"></span></td></tr>`;
      }).join("") + `</tbody>`;
  } catch (err) {
    $("eval-total").textContent = `Start the server to see live numbers (${err.message}).`;
  }
}

$("eval-positions").innerHTML = EVAL_POSITIONS.map(([name], i) =>
  `<label><input type="radio" name="evalpos" value="${i}" ${i === 1 ? "checked" : ""}><span>${name}</span></label>`).join("");
$("eval-positions").addEventListener("change", (e) => showEval(EVAL_POSITIONS[Number(e.target.value)][1]));
showEval(EVAL_POSITIONS[1][1]);

// ====================================================================== lesson 6: horizon

// Texts use the live evaluations: s[0] before, s[1] after Qxd5, s[2] after ...exd5.
const HORIZON = [
  { fen: "4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1", move: null,
    text: (s) => `White to move, with a queen against two pawns (${s[0]}). The d5 pawn looks ` +
      "like it can simply be taken by the queen." },
  { fen: "4k3/8/4p3/3Q4/8/8/8/4K3 b - - 0 1", move: "d1d5",
    text: (s) => `If the search stops right here (its horizon), the score rises from ${s[0]} to ` +
      `${s[1]}: Qxd5 seems to win a pawn for free. But it is Black's move, and the queen can be taken.` },
  { fen: "4k3/8/8/3p4/8/8/8/4K3 w - - 0 2", move: "e6d5",
    text: (s) => `One capture further: …exd5 and White has lost the queen. The score drops from ` +
      `${s[1]} to ${s[2]}. Quiescence search follows captures like this automatically, so the AI ` +
      "sees the real score and never plays Qxd5." },
];
const horizonBoard = new ChessBoard($("horizon-board"), { onMove: () => {} });
let horizonAt = 0;
let horizonScores = null;

async function showHorizon(k) {
  const step = HORIZON[k];
  const forward = k === horizonAt + 1;
  horizonBoard.setPosition(step.fen, { animate: forward ? step.move : null, lastMove: step.move });
  horizonAt = k;
  try {
    horizonScores = horizonScores ||
      (await Promise.all(HORIZON.map((h) => evaluate(h.fen)))).map((e) => pawns(e.total));
    $("horizon-score").innerHTML = `Static evaluation: <b>${horizonScores[k]}</b> for White`;
    $("horizon-text").textContent = step.text(horizonScores);
  } catch {
    $("horizon-score").textContent = "Start the server to see live numbers.";
    $("horizon-text").textContent = step.text(["?", "?", "?"]);
  }
}
$("horizon-steps").addEventListener("change", (e) => showHorizon(Number(e.target.value)));
showHorizon(0);
