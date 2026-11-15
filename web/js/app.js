// Main page logic: talks to the server, keeps the board and panels in sync.

import { BoardHost, savedMode, webglAvailable } from "./boardhost.js";
import * as panels from "./panels.js";
import * as sound from "./sound.js";
import { renderThinking } from "./thinking.js";
import { describeNode, drawTree } from "./tree.js";

const $ = (id) => document.getElementById(id);
const GLYPH = { p: "♟", n: "♞", b: "♝", r: "♜", q: "♛", k: "♚" };
const VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 0 };
const REASONS = {
  checkmate: "by checkmate", stalemate: "by stalemate", insufficient_material: "insufficient material",
  seventyfive_moves: "75-move rule", fivefold_repetition: "fivefold repetition",
  fifty_moves: "50-move rule", threefold_repetition: "threefold repetition",
  resignation: "by resignation", draw_agreed: "by agreement", timeout: "on time",
  timeout_vs_insufficient_material: "time out vs insufficient material",
};

const app = {
  state: null,
  info: null,
  viewPly: null, // null = live position, otherwise the ply being reviewed
  flipped: false,
  thinking: false,
  ws: null,
  shownFen: null,
  clockFetchedAt: 0,
  wasOver: false,
  lastReport: null,
  reports: new Map(), // ply -> full AI move report (cached)
  thinkingPly: null, // AI ply currently shown in the AI Thinking panel
};

const board = new BoardHost($("board"), { onMove: humanMove, onModeChange: showMode });

// ---------------------------------------------------------------- board style (Plain / 3D / Battle)

function showMode(mode) {
  for (const b of document.querySelectorAll(".mode-btn")) {
    b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
  }
}

async function chooseMode(mode, clicked = false) {
  if (mode !== "plain" && !webglAvailable()) {
    toast("This browser can't show 3D graphics, so the plain board is used.");
    mode = "plain";
  }
  showMode(mode);
  const used = await board.setMode(mode);
  if (used !== mode) toast("The 3D board couldn't start here, so the plain board is used.");
  else if (mode === "battle" && clicked) toast("Battle armies are coming soon. For now Battle shows the 3D board.");
}

for (const b of document.querySelectorAll(".mode-btn")) {
  b.addEventListener("click", () => chooseMode(b.dataset.mode, true));
}
if (savedMode() !== "plain") chooseMode(savedMode());

// ---------------------------------------------------------------- server calls

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await res.text();
  const data = text && res.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
  if (!res.ok) {
    const detail = typeof data === "object" && data.detail ? data.detail : res.statusText;
    const err = new Error(Array.isArray(detail) ? detail.map((d) => d.msg).join("; ") : detail);
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(message, ms = 3500) {
  const t = $("toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), ms);
}

function setState(state) {
  app.state = state;
  app.clockFetchedAt = performance.now();
  try { localStorage.setItem("gameId", state.id); } catch { /* ignore */ }
}

// ---------------------------------------------------------------- game actions

async function startGame(options) {
  closeSocket();
  app.viewPly = null;
  app.shownFen = null;
  app.wasOver = false;
  app.lastReport = null;
  app.reports = new Map();
  app.thinkingPly = null;
  panels.resetSearch();
  $("candidates").innerHTML = `<li class="empty">Appears after the AI's first searched move.</li>`;
  setState(await api("/api/games", { method: "POST", body: options }));
  app.flipped = false;
  render();
  board.playIntro({ drop: true }); // 3D views: 360° spin while the pieces drop in
  if (app.state.ai_to_move) requestAiMove();
}

async function humanMove(uci) {
  const s = app.state;
  if (!s) return;
  sound.play(board.position.size < countPieces(s.game.fen) ? "capture" : "move");
  try {
    const res = await api(`/api/games/${s.id}/move`, { method: "POST", body: { move: uci } });
    setState(res.state);
    if (res.move.is_check) sound.play("check");
    render();
    if (app.state.ai_to_move) requestAiMove();
  } catch (err) {
    toast(err.message);
    render(true); // put the pieces back
  }
}

function countPieces(fen) {
  return fen.split(" ")[0].replace(/[^a-zA-Z]/g, "").length;
}

function openSocket() {
  return new Promise((resolve, reject) => {
    if (app.ws && app.ws.readyState === WebSocket.OPEN && app.ws.gameId === app.state.id) {
      resolve(app.ws);
      return;
    }
    closeSocket();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/games/${app.state.id}`);
    ws.gameId = app.state.id;
    ws.onopen = () => resolve(ws);
    ws.onerror = () => reject(new Error("WebSocket failed"));
    ws.onmessage = (e) => onSocketMessage(JSON.parse(e.data));
    ws.onclose = () => { if (app.ws === ws) app.ws = null; };
    app.ws = ws;
  });
}

function closeSocket() {
  if (app.ws) { app.ws.onclose = null; app.ws.close(); app.ws = null; }
}

async function requestAiMove() {
  if (app.thinking) return;
  app.thinking = true;
  panels.resetSearch();
  panels.setThinking(true);
  render();
  try {
    const ws = await openSocket();
    ws.send(JSON.stringify({ type: "ai_move" }));
  } catch {
    // no WebSocket: fall back to a plain request (no live updates)
    try {
      const res = await api(`/api/games/${app.state.id}/ai-move`, { method: "POST" });
      finishAiMove(res.report, res.state);
    } catch (err) {
      app.thinking = false;
      panels.setThinking(false);
      toast(err.message);
      render();
    }
  }
}

function onSocketMessage(msg) {
  if (msg.type === "iteration") {
    panels.showIteration(msg.data);
    const aiWhite = app.state.ai_color === "white";
    panels.setEvalBar(aiWhite ? msg.data.score : -msg.data.score, boardOrientation() === "black");
  } else if (msg.type === "ai_move") {
    finishAiMove(msg.report, msg.state);
  } else if (msg.type === "error") {
    app.thinking = false;
    panels.setThinking(false);
    toast(msg.message);
    refresh();
  }
}

function finishAiMove(report, state) {
  app.thinking = false;
  panels.setThinking(false);
  app.lastReport = report;
  app.reports.set(report.ply, report);
  app.thinkingPly = null; // force the panel to show this new report
  setState(state);
  const rec = state.game.history[state.game.history.length - 1];
  if (app.viewPly === null) sound.play(rec.is_check ? "check" : rec.captured ? "capture" : "move");
  panels.showReport(report);
  render();
}

async function refresh() {
  if (!app.state) return;
  try {
    setState(await api(`/api/games/${app.state.id}`));
    render();
  } catch (err) {
    toast(err.message);
  }
}

// ---------------------------------------------------------------- AI Thinking panel

/** Show the explanation of the latest AI move at or before the position on the board. */
async function updateThinking(shownPly) {
  const s = app.state;
  const plies = s.ai_plies.filter((p) => p <= shownPly);
  const ply = plies.length ? plies[plies.length - 1] : null;
  const box = $("thinking-body");
  if (ply === null) {
    app.thinkingPly = null;
    renderThinking(box, null, {});
    return;
  }
  if (ply === app.thinkingPly && box.dataset.ply === String(ply)) return;
  app.thinkingPly = ply;
  let report = app.reports.get(ply);
  if (!report) {
    box.innerHTML = `<p class="empty">Loading the explanation…</p>`;
    try {
      report = await api(`/api/games/${s.id}/analysis/${ply}`);
      app.reports.set(ply, report);
    } catch (err) {
      box.innerHTML = `<p class="empty">${err.message}</p>`;
      return;
    }
    if (app.thinkingPly !== ply) return; // the user moved on meanwhile
  }
  const rec = s.game.history[ply - 1];
  const label = rec ? `AI move ${rec.move_number}${rec.color === "white" ? "." : "…"} ${rec.san}` : "";
  renderThinking(box, report, { onTree: openTree, moveLabel: label });
  box.dataset.ply = String(ply);
}

// ---------------------------------------------------------------- search tree viewer

let treePly = null;

async function openTree(ply) {
  treePly = ply;
  const dlg = $("dlg-tree");
  if (!dlg.open) dlg.showModal();
  await loadTree();
}

async function loadTree() {
  const host = $("tree-host");
  const detail = $("tree-detail");
  host.innerHTML = `<p class="empty">Building the tree…</p>`;
  detail.innerHTML = "";
  const depth = $("tree-depth").value, breadth = $("tree-breadth").value;
  try {
    const t = await api(`/api/games/${app.state.id}/tree?ply=${treePly}&depth=${depth}&breadth=${breadth}`);
    $("tree-summary").innerHTML =
      `Best move <b>${t.best_san}</b> (${t.value_text}). Alpha-beta visited <b>${t.visited}</b> of ` +
      `${t.total} positions in this tree: <b>${t.pruned_pct}%</b> were skipped, with the same answer as plain minimax.`;
    drawTree(host, $("tree-rows"), t, (node) => { detail.innerHTML = describeNode(node); });
  } catch (err) {
    host.innerHTML = `<p class="empty">${err.message}</p>`;
  }
}

$("tree-depth").addEventListener("change", loadTree);
$("tree-breadth").addEventListener("change", loadTree);
$("btn-tree-close").addEventListener("click", () => $("dlg-tree").close());

// ---------------------------------------------------------------- rendering

function boardOrientation() {
  const human = app.state ? app.state.human_color : "white";
  const other = human === "white" ? "black" : "white";
  return app.flipped ? other : human;
}

function render(forceReset = false) {
  const s = app.state;
  if (!s) return;
  const g = s.game;
  const history = g.history;
  const live = app.viewPly === null || app.viewPly >= history.length;
  const ply = live ? history.length : app.viewPly;
  const rec = ply > 0 ? history[ply - 1] : null;
  const fen = ply === 0 ? g.start_fen : rec.fen_after;

  board.setOrientation(boardOrientation());
  if (forceReset) app.shownFen = null;
  // animate when stepping exactly one move forward from what is on the board
  const prevFen = ply === 0 ? null : ply === 1 ? g.start_fen : history[ply - 2].fen_after;
  const animate = rec && app.shownFen && app.shownFen === prevFen ? rec.uci : null;
  board.setPosition(fen, { animate, lastMove: rec ? rec.uci : null,
                           check: live ? g.is_check : !!rec?.is_check });
  app.shownFen = fen;

  const yourTurn = live && !g.status.is_over && g.turn === s.human_color && !app.thinking;
  board.setInteractive(yourTurn ? s.human_color : null, g.legal_moves);

  // eval bar: score after the shown ply (or the latest known one)
  let cp = null;
  for (let i = ply - 1; i >= 0 && cp === null; i--) cp = s.evals[i] ?? null;
  if (!app.thinking || !live) panels.setEvalBar(cp, boardOrientation() === "black");

  const pick = (p) => { app.viewPly = p >= history.length ? null : p; render(); };
  panels.renderHistory(s, ply, pick);
  panels.renderGraph(s, ply, pick);

  // players
  const bottom = boardOrientation(), top = bottom === "white" ? "black" : "white";
  const name = (color) => (color === s.human_color ? "You" : `AI · ${s.level.label}`);
  $("bottom-name").textContent = name(bottom);
  $("top-name").textContent = name(top);
  $("bottom-color").className = `dot-color ${bottom}`;
  $("top-color").className = `dot-color ${top}`;
  renderCaptured(g, bottom, "bottom-captured");
  renderCaptured(g, top, "top-captured");

  // opening
  $("opening-card").hidden = !s.opening;
  if (s.opening) {
    $("opening-eco").textContent = s.opening.eco;
    $("opening-name").textContent = s.opening.name;
  }

  // review banner
  $("review-banner").hidden = live;
  if (!live) $("review-label").textContent = ply === 0 ? "start" : `${rec.move_number}${rec.color === "white" ? "." : "…"} ${rec.san}`;

  // status
  $("status-line").innerHTML = statusText(s);

  // buttons
  const over = g.status.is_over;
  $("btn-undo").disabled = app.thinking || history.length === 0 || g.status.reason === "timeout";
  $("btn-resign").disabled = over || app.thinking;
  $("btn-draw").disabled = over || app.thinking;

  renderClocks();
  updateThinking(ply);

  if (over && !app.wasOver) {
    app.wasOver = true;
    sound.play("end");
    showGameOver(s);
  }
  if (!over) app.wasOver = false;
}

function renderCaptured(g, color, id) {
  // pieces this side has taken from the opponent
  const taken = g.captured[color].map((p) => p.toLowerCase()).sort((a, b) => VALUE[b] - VALUE[a]);
  const adv = color === "white" ? g.material_balance : -g.material_balance;
  $(id).innerHTML = taken.map((p) => GLYPH[p] + "︎").join("") +
    (adv > 0 ? `<span class="adv">+${adv}</span>` : "");
}

function statusText(s) {
  const g = s.game;
  if (g.status.is_over) {
    const reason = REASONS[g.status.reason] || g.status.reason;
    if (!g.status.winner) return `<b>Draw</b> · ${reason}`;
    return `<b>${g.status.winner === s.human_color ? "You win" : "The AI wins"}</b> ${reason}`;
  }
  if (app.thinking) return `<b>AI is thinking…</b> watch the Evaluation tab`;
  const check = g.is_check ? " · <b>Check!</b>" : "";
  return g.turn === s.human_color ? `<b>Your move</b>${check}` : `AI to move${check}`;
}

function showGameOver(s) {
  const g = s.game;
  const reason = REASONS[g.status.reason] || g.status.reason;
  $("over-title").textContent = !g.status.winner ? "Draw" :
    g.status.winner === s.human_color ? "You win! 🎉" : "The AI wins";
  const moves = Math.ceil(g.history.length / 2);
  $("over-text").textContent = `Result ${g.status.result}, ${reason}, after ${moves} move${moves === 1 ? "" : "s"}.`;
  $("dlg-over").showModal();
}

// ---------------------------------------------------------------- clocks

function fmt(sec) {
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return sec < 10 ? `${m}:${String(s).padStart(2, "0")}.${Math.floor((sec % 1) * 10)}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function renderClocks() {
  const s = app.state;
  const c = s && s.clock;
  $("clock-top").hidden = $("clock-bottom").hidden = !c;
  if (!c) return;
  const bottom = boardOrientation(), top = bottom === "white" ? "black" : "white";
  const elapsed = (performance.now() - app.clockFetchedAt) / 1000;
  for (const [color, id] of [[bottom, "clock-bottom"], [top, "clock-top"]]) {
    const running = c.running && c.turn === color && !s.game.status.is_over;
    const left = c[color] - (running ? elapsed : 0);
    const node = $(id);
    node.textContent = fmt(left);
    node.classList.toggle("running", running);
    node.classList.toggle("low", left < 20);
    if (running && left <= 0 && color === s.human_color && !renderClocks.flagging) {
      renderClocks.flagging = true;
      refresh().finally(() => (renderClocks.flagging = false));
    }
  }
}
setInterval(renderClocks, 200);

// ---------------------------------------------------------------- dialogs & controls

function buildLevelChoices() {
  const box = $("levels");
  box.replaceChildren(...app.info.levels.map((lv) => {
    const label = document.createElement("label");
    label.innerHTML = `<input type="radio" name="level" value="${lv.name}" ${lv.name === app.info.default_level ? "checked" : ""}>` +
      `<span><b>${lv.label}</b><small>${lv.description}</small></span>`;
    return label;
  }));
}

function openNewGame() {
  $("dlg-new").showModal();
}

$("form-new").addEventListener("submit", (e) => {
  const submitter = e.submitter;
  if (!submitter || submitter.value !== "start") return;
  e.preventDefault();
  const form = new FormData(e.target);
  const clock = form.get("clock");
  const body = { human_color: form.get("color"), level: form.get("level") };
  if (clock) {
    const [min, inc] = clock.split("+").map(Number);
    body.clock_minutes = min;
    body.increment_seconds = inc;
  }
  $("dlg-new").close();
  startGame(body).catch((err) => toast(err.message));
});

$("btn-new").addEventListener("click", openNewGame);
$("btn-again").addEventListener("click", () => { $("dlg-over").close(); openNewGame(); });
$("btn-review").addEventListener("click", () => $("dlg-over").close());

$("btn-flip").addEventListener("click", () => { app.flipped = !app.flipped; render(); });

$("btn-undo").addEventListener("click", async () => {
  try {
    const res = await api(`/api/games/${app.state.id}/undo`, { method: "POST" });
    app.viewPly = null;
    for (const rec of res.undone) app.reports.delete(rec.ply);
    app.thinkingPly = null;
    setState(res.state);
    render(true);
  } catch (err) { toast(err.message); }
});

$("btn-resign").addEventListener("click", async () => {
  if (!confirm("Resign this game?")) return;
  try {
    setState((await api(`/api/games/${app.state.id}/resign`, { method: "POST" })).state);
    render();
  } catch (err) { toast(err.message); }
});

$("btn-draw").addEventListener("click", async () => {
  $("btn-draw").disabled = true;
  try {
    const res = await api(`/api/games/${app.state.id}/draw`, { method: "POST" });
    toast(`${res.answer.accepted ? "Draw accepted." : "Draw declined."} ${res.answer.reason} (${res.answer.ai_score_text})`, 5000);
    setState(res.state);
    render();
  } catch (err) { toast(err.message); render(); }
});

$("btn-pgn").addEventListener("click", async () => {
  try {
    const text = await api(`/api/games/${app.state.id}/pgn`);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type: "application/x-chess-pgn" }));
    a.download = `chess-minimax-ai-${new Date().toISOString().slice(0, 10)}.pgn`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (err) { toast(err.message); }
});

$("btn-live").addEventListener("click", () => { app.viewPly = null; render(); });

function step(delta) {
  const n = app.state ? app.state.game.history.length : 0;
  const cur = app.viewPly === null ? n : app.viewPly;
  const next = Math.max(0, Math.min(n, cur + delta));
  app.viewPly = next >= n ? null : next;
  render();
}
$("nav-first").addEventListener("click", () => step(-1e9));
$("nav-prev").addEventListener("click", () => step(-1));
$("nav-next").addEventListener("click", () => step(1));
$("nav-last").addEventListener("click", () => step(1e9));

document.addEventListener("keydown", (e) => {
  if (e.target.closest("input, select, textarea, dialog")) return;
  if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
  else if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
  else if (e.key === "Home") step(-1e9);
  else if (e.key === "End") step(1e9);
  else if (e.key === "f" || e.key === "F") { app.flipped = !app.flipped; render(); }
});

// tabs
document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t === tab;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
    $(`panel-${t.dataset.tab}`).classList.toggle("active", on);
  });
}));

// theme & sound
function applyTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem("theme")); } catch { /* ignore */ }
$("btn-theme").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("theme", next); } catch { /* ignore */ }
});
const soundButton = $("btn-sound");
const showSound = () => { soundButton.style.opacity = sound.soundEnabled() ? "1" : "0.4"; };
soundButton.addEventListener("click", () => { sound.toggleSound(); showSound(); });
showSound();

// ---------------------------------------------------------------- start up

(async function init() {
  try {
    app.info = await api("/api/info");
  } catch {
    $("status-line").textContent = "Cannot reach the server. Start it with: python -m chess_ai.server";
    return;
  }
  buildLevelChoices();
  let saved = null;
  try { saved = localStorage.getItem("gameId"); } catch { /* ignore */ }
  if (saved) {
    try {
      setState(await api(`/api/games/${saved}`));
      app.wasOver = app.state.game.status.is_over;
      render();
      if (app.state.ai_to_move) requestAiMove();
      return;
    } catch { /* the server forgot that game: start a new one */ }
  }
  openNewGame();
})();
