// Side panels: move history, evaluation bar + graph, live search stats, candidates.

const MATE = 100000;
const el = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Centipawns (White's view) -> 0..1 share of the bar for White. */
export function whiteShare(cp) {
  if (cp === null || cp === undefined) return 0.5;
  if (Math.abs(cp) >= MATE - 200) return cp > 0 ? 1 : 0;
  return 1 / (1 + Math.exp(-cp / 250));
}

export function scoreText(cp) {
  if (cp === null || cp === undefined) return "–";
  if (Math.abs(cp) >= MATE - 200) {
    const plies = MATE - Math.abs(cp);
    if (plies === 0) return "#"; // the game has ended in checkmate
    const n = Math.ceil(plies / 2);
    return cp > 0 ? `#${n}` : `#-${n}`;
  }
  return (cp >= 0 ? "+" : "") + (cp / 100).toFixed(2);
}

// ---------------------------------------------------------------- eval bar

export function setEvalBar(cpWhite, flipped) {
  const share = whiteShare(cpWhite);
  const fill = el("evalbar-fill");
  fill.style.height = `${share * 100}%`;
  fill.style.bottom = flipped ? "auto" : "0";
  fill.style.top = flipped ? "0" : "auto";
  el("evalbar-text").textContent = cpWhite === null || cpWhite === undefined
    ? "–" : scoreText(cpWhite).replace("+", "");
}

// ---------------------------------------------------------------- history

/**
 * @param {object} state game state from the server
 * @param {number} viewPly ply being shown (history.length = live position)
 * @param {(ply:number)=>void} onPick
 */
export function renderHistory(state, viewPly, onPick) {
  const body = el("history-body");
  const history = state.game.history;
  el("history-empty").hidden = history.length > 0;
  const rows = [];
  const first = history[0];
  for (let i = 0; i < history.length; i++) {
    const rec = history[i];
    const rowIndex = rec.move_number - first.move_number;
    if (!rows[rowIndex]) rows[rowIndex] = { num: rec.move_number, white: null, black: null };
    rows[rowIndex][rec.color] = rec;
  }
  body.replaceChildren(...rows.filter(Boolean).map((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="num">${row.num}.</td>`;
    for (const color of ["white", "black"]) {
      const td = document.createElement("td");
      const rec = row[color];
      if (rec) td.append(moveButton(rec, state, viewPly, onPick));
      tr.append(td);
    }
    return tr;
  }));
  const current = body.querySelector(".mv.current");
  if (current) current.scrollIntoView({ block: "nearest" });
}

function moveButton(rec, state, viewPly, onPick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "mv" + (rec.ply === viewPly ? " current" : "");
  const ai = state.ai_moves[String(rec.ply)];
  let badge;
  if (rec.color === state.human_color) badge = `<i class="badge you">You</i>`;
  else if (ai && ai.source === "book") badge = `<i class="badge book">Book</i>`;
  else badge = `<i class="badge search">AI</i>`;
  if (ai && ai.weaker_on_purpose) badge += `<i class="badge weak" title="Weaker move on purpose (difficulty)">easy</i>`;
  const cp = state.evals[rec.ply - 1];
  b.innerHTML = `<span class="san">${esc(rec.san)}</span>${badge}` +
    `<span class="score">${cp === null || cp === undefined ? "" : scoreText(cp)}</span>`;
  b.title = `${rec.color} ${rec.piece} ${rec.from_square}→${rec.to_square}` +
    (rec.captured ? `, captures ${rec.captured}` : "") + (ai ? ` · ${ai.seconds}s` : "");
  b.addEventListener("click", () => onPick(rec.ply));
  return b;
}

// ---------------------------------------------------------------- graph

export function renderGraph(state, viewPly, onPick) {
  const svg = el("graph");
  const W = 300, H = 110, mid = H / 2;
  const evals = state.evals;
  const n = evals.length;
  const xs = (i) => (n <= 1 ? W / 2 : 6 + (i * (W - 12)) / (n - 1));
  const ys = (cp) => H - whiteShare(cp) * H;
  let pts = [], last = 0;
  evals.forEach((cp, i) => {
    if (cp !== null && cp !== undefined) last = cp;
    pts.push([xs(i), ys(last), i + 1, cp]);
  });
  let html = `<rect class="bg" x="0" y="0" width="${W}" height="${H}"/>`;
  if (pts.length) {
    const area = [`0,${H}`, `0,${pts[0][1]}`, ...pts.map(([x, y]) => `${x},${y}`),
      `${W},${pts[pts.length - 1][1]}`, `${W},${H}`].join(" ");
    html += `<polygon class="area" points="${area}"/>`;
    html += `<polyline class="line" points="${pts.map(([x, y]) => `${x},${y}`).join(" ")}"/>`;
  } else {
    html += `<rect class="area" x="0" y="${mid}" width="${W}" height="${mid}"/>`;
  }
  html += `<line class="mid" x1="0" x2="${W}" y1="${mid}" y2="${mid}"/>`;
  for (const [x, y, ply, cp] of pts) {
    if (cp === null || cp === undefined) continue;
    html += `<circle class="pt${ply === viewPly ? " current" : ""}" cx="${x}" cy="${y}" r="${ply === viewPly ? 3.5 : 2.2}" data-ply="${ply}"><title>Move ${ply}: ${scoreText(cp)}</title></circle>`;
  }
  svg.innerHTML = html;
  svg.querySelectorAll(".pt").forEach((c) => c.addEventListener("click", () => onPick(Number(c.dataset.ply))));
}

// ---------------------------------------------------------------- live search

export function resetSearch() {
  el("depth-log").replaceChildren();
  for (const id of ["st-depth", "st-score", "st-nodes", "st-nps", "st-time", "st-seldepth"]) el(id).textContent = "–";
  el("st-pv").textContent = "–";
}

export function showIteration(d) {
  el("st-depth").textContent = d.depth;
  el("st-score").textContent = d.score_text;
  el("st-nodes").textContent = d.nodes.toLocaleString();
  el("st-nps").textContent = d.nps.toLocaleString();
  el("st-time").textContent = `${d.seconds.toFixed(2)}s`;
  el("st-seldepth").textContent = `${d.seldepth} plies`;
  el("st-pv").textContent = (d.pv_san || []).join(" ") || "–";
  const li = document.createElement("li");
  li.innerHTML = `<b>depth ${d.depth}</b> ${esc(d.score_text)} · ${d.nodes.toLocaleString()} pos · ${esc((d.pv_san || []).slice(0, 5).join(" "))}`;
  el("depth-log").prepend(li);
}

/** Final numbers + candidates from a full AI move report. */
export function showReport(report) {
  const box = el("candidates");
  if (report.source === "book") {
    const opts = (report.book && report.book.options) || [];
    box.innerHTML = `<li class="empty">Opening book move (no search needed). Known moves here: ` +
      opts.map((o) => `<b>${esc(o.san)}</b> ${Math.round(o.share * 100)}%`).join(", ") + `</li>`;
    el("st-pv").textContent = "–";
    return;
  }
  const a = report.analysis;
  if (!a) return;
  const s = a.search;
  el("st-depth").textContent = s.depth;
  el("st-score").textContent = s.score_text;
  el("st-nodes").textContent = s.nodes.toLocaleString();
  el("st-nps").textContent = s.nps.toLocaleString();
  el("st-time").textContent = `${s.seconds.toFixed(2)}s`;
  el("st-seldepth").textContent = `${s.seldepth} plies`;
  el("st-pv").textContent = a.best.line_san.join(" ");
  box.replaceChildren(...a.candidates.map((c) => {
    const li = document.createElement("li");
    li.className = "cand" + (c.is_best ? " best" : "");
    const played = report.difficulty_choice && report.difficulty_choice.played_san === c.san;
    li.innerHTML = `<span class="c-san">${esc(c.san)}${c.is_best ? " ★" : ""}${played ? " ✓" : ""}</span>` +
      `<span class="c-score">${esc(c.score_text)}</span>` +
      `<span class="c-line" title="${esc(c.line_san.join(" "))}">${esc(c.line_san.slice(1, 6).join(" "))}</span>`;
    return li;
  }));
}

export function setThinking(on) {
  el("live-dot").hidden = !on;
}
