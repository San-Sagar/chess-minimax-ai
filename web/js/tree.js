// Search tree viewer: draws the recorded alpha-beta tree as an SVG.
//
// Root at the top (MAX = the AI chooses the highest value), next row MIN (the opponent
// chooses the lowest), and so on. Pruned branches are dashed and grey; the edge into a
// node that caused a cutoff is red; the best line is drawn thick.

const NODE_W = 78, NODE_H = 46, GAP_X = 10, GAP_Y = 64, LEFT = 12, TOP = 16;
const INF_TEXT = { "+inf": "+∞", "-inf": "−∞" };

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function cp(v) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "string") return INF_TEXT[v] || v;
  if (Math.abs(v) >= 99000) return v > 0 ? "mate" : "−mate";
  return (v >= 0 ? "+" : "−") + (Math.abs(v) / 100).toFixed(2);
}

/** Lay the tree out: leaves left to right, parents centred over their children. */
function layout(root) {
  const nodes = [], edges = [];
  let leafX = 0, maxPly = 0;
  (function walk(node, parent) {
    node.parent = parent;
    maxPly = Math.max(maxPly, node.ply);
    if (!node.children.length) {
      node.x = leafX++;
    } else {
      node.children.forEach((c) => walk(c, node));
      node.x = (node.children[0].x + node.children[node.children.length - 1].x) / 2;
    }
    nodes.push(node);
    if (parent) edges.push([parent, node]);
  })(root, null);
  // best line: follow best_child from the root
  const best = new Set();
  for (let n = root; n; n = n.children.find((c) => c.id === n.best_child)) best.add(n.id);
  return { nodes, edges, best, width: leafX, depth: maxPly };
}

const px = (n) => LEFT + n.x * (NODE_W + GAP_X);
const py = (n) => TOP + n.ply * (NODE_H + GAP_Y);

/**
 * @param {HTMLElement} host scrolling element to draw the tree into
 * @param {HTMLElement} rowsHost fixed column for the MAX / MIN row labels
 * @param {object} tree from GET /api/games/{id}/tree
 * @param {(node) => void} onSelect
 */
export function drawTree(host, rowsHost, tree, onSelect) {
  const { nodes, edges, best, width, depth } = layout(tree.root);
  const W = LEFT + width * (NODE_W + GAP_X) + 10;
  const H = TOP + (depth + 1) * (NODE_H + GAP_Y);
  let svg = `<svg class="tree-svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Alpha-beta search tree">`;

  // row labels (in their own column, so they stay visible while the tree scrolls)
  let rows = `<svg class="tree-svg" width="92" height="${H}" aria-hidden="true">`;
  for (let ply = 0; ply <= depth; ply++) {
    const y = TOP + ply * (NODE_H + GAP_Y) + NODE_H / 2;
    const max = ply % 2 === 0;
    rows += `<text class="row-label ${max ? "max" : "min"}" x="8" y="${y - 4}">${max ? "▲ MAX" : "▼ MIN"}</text>` +
      `<text class="row-sub" x="8" y="${y + 11}">${ply === 0 ? "AI to move" : max ? "AI picks highest" : "opponent: lowest"}</text>`;
  }
  rowsHost.innerHTML = rows + "</svg>";

  // edges
  for (const [p, c] of edges) {
    const x1 = px(p) + NODE_W / 2, y1 = py(p) + NODE_H, x2 = px(c) + NODE_W / 2, y2 = py(c);
    const cls = c.status === "pruned" ? "pruned" : best.has(c.id) && best.has(p.id) ? "best" : "";
    const ym = (y1 + y2) / 2;
    svg += `<path class="edge ${cls}" d="M${x1},${y1} C${x1},${ym} ${x2},${ym} ${x2},${y2}"/>`;
    if (c.caused_cutoff) {
      svg += `<text class="cut-label" x="${x2 + 6}" y="${y2 - 8}">✂ cutoff</text>`;
    }
  }

  // nodes
  for (const n of nodes) {
    const x = px(n), y = py(n);
    const cls = [
      "node", n.player, n.status === "pruned" ? "pruned" : "",
      best.has(n.id) ? "best" : "", n.caused_cutoff ? "cutter" : "",
    ].join(" ");
    const label = n.ply === 0 ? "start" : n.san;
    const value = n.status === "pruned" ? "skipped" : cp(n.value);
    svg += `<g class="${cls}" data-id="${n.id}" tabindex="0">` +
      `<rect x="${x}" y="${y}" width="${NODE_W}" height="${NODE_H}" rx="8"/>` +
      `<text class="n-san" x="${x + NODE_W / 2}" y="${y + 19}">${esc(label)}</text>` +
      `<text class="n-val" x="${x + NODE_W / 2}" y="${y + 36}">${esc(value)}</text></g>`;
  }
  svg += "</svg>";
  host.innerHTML = svg;

  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  host.querySelectorAll("g.node").forEach((g) => {
    const pick = () => {
      host.querySelectorAll("g.node.selected").forEach((s) => s.classList.remove("selected"));
      g.classList.add("selected");
      onSelect(byId.get(g.dataset.id));
    };
    g.addEventListener("click", pick);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") pick(); });
  });
  // select the root initially
  const rootG = host.querySelector(`g.node[data-id="${tree.root.id}"]`);
  if (rootG) { rootG.classList.add("selected"); onSelect(tree.root); }
  // scroll so the root and the start of the best line are both in view if possible
  const bestChild = nodes.find((n) => n.ply === 1 && best.has(n.id));
  const rootX = px(tree.root);
  const left = bestChild ? Math.min(px(bestChild), rootX) : rootX;
  const right = bestChild ? Math.max(px(bestChild), rootX) + NODE_W : rootX + NODE_W;
  const view = host.clientWidth;
  host.scrollLeft = right - left + 40 <= view
    ? Math.max(0, (left + right) / 2 - view / 2)
    : Math.max(0, rootX + NODE_W / 2 - view / 2);
  host.scrollTop = 0;
}

/** Plain-language description of one node. */
export function describeNode(n) {
  const path = [];
  for (let m = n; m && m.parent; m = m.parent) path.unshift(m.san);
  const who = n.player === "max" ? "the AI is to move, so it takes the <b>highest</b> value"
    : "the opponent is to move, so it takes the <b>lowest</b> value";
  let html = `<p class="tree-path">${path.length ? esc(path.join(" ")) : "Starting position"}</p>`;

  if (n.status === "pruned") {
    const cutter = n.parent.children.find((c) => c.caused_cutoff);
    html += `<p><b>Never searched.</b> Its parent was cut off after <b>${esc(cutter ? cutter.san : "an earlier move")}</b>, ` +
      `so this move could not change the result. Alpha-beta skips it, and everything below it.</p>`;
    return html;
  }
  html += `<p>At this position ${who}.</p>`;
  html += `<div class="tree-ab"><span>α (AI is already sure of) <b>${cp(n.alpha)}</b></span>` +
    `<span>β (opponent is already sure of) <b>${cp(n.beta)}</b></span>` +
    `<span>value <b>${cp(n.value)}</b></span></div>`;
  if (n.is_leaf) {
    html += `<p>This is a leaf: its value comes from the evaluation function (after captures settle).</p>`;
  } else {
    const best = n.children.find((c) => c.id === n.best_child);
    if (best) html += `<p>Best choice here: <b>${esc(best.san)}</b> (${cp(best.value)}).</p>`;
  }
  if (n.caused_cutoff && n.parent) {
    const p = n.parent;
    if (p.player === "max") {
      html += `<p class="cut-text">✂ <b>β-cutoff.</b> Here the AI already gets ${cp(n.value)}, at least as much as ` +
        `β = ${cp(p.beta)}, the most the opponent allows elsewhere. The opponent will avoid this position, ` +
        `so the AI's remaining moves here are skipped.</p>`;
    } else {
      html += `<p class="cut-text">✂ <b>α-cutoff.</b> This reply holds the AI to ${cp(n.value)}, no more than ` +
        `α = ${cp(p.alpha)}, which the AI can already get with another move. The AI will not play into this ` +
        `position, so the opponent's remaining replies are skipped.</p>`;
    }
  }
  return html;
}
