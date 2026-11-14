// AI Thinking panel: shows the explanation the server built for an AI move.

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/**
 * @param {HTMLElement} box
 * @param {object|null} report full AI move report (with .explanation)
 * @param {{onTree: (ply:number) => void, moveLabel: string}} opts
 */
export function renderThinking(box, report, { onTree, moveLabel }) {
  if (!report) {
    box.innerHTML = `<p class="empty">The AI's explanation of each move appears here after it moves.</p>`;
    return;
  }
  const e = report.explanation;
  if (!e) {
    box.innerHTML = `<p class="empty">No explanation recorded for this move.</p>`;
    return;
  }
  let html = `<div class="th-head"><span class="th-label">${esc(moveLabel)}</span>` +
    `<h3>${esc(e.headline)}</h3><p class="th-assess">${esc(e.assessment)}</p></div>`;

  if (e.difficulty_note) html += `<p class="th-note">${esc(e.difficulty_note)}</p>`;

  if (e.ideas && e.ideas.length) {
    html += section("Why this move", `<ul class="th-ideas">${e.ideas.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`);
  }

  if (e.kind === "book" && e.book) {
    html += section("Opening book", `<p>Known moves here: <b>${esc(e.book.known_moves)}</b>.</p>` +
      `<p class="muted">The move was ${esc(e.book.choice)}.</p>`);
  }

  if (e.expected) {
    const x = e.expected;
    let body = `<p class="th-line">${esc(x.line)}</p>`;
    if (x.reply_san) {
      body += `<p>The opponent's best reply is <b>${esc(x.reply_san)}</b>` +
        (x.reply_idea ? `, which ${esc(x.reply_idea)}` : "") + `.</p>`;
    }
    html += section("What it expects", body);
  }

  if ((e.alternatives && e.alternatives.length) || (e.refuted && e.refuted.length)) {
    let body = "";
    for (const a of e.alternatives || []) {
      body += `<div class="th-alt"><div class="th-alt-top"><b>${esc(a.san)}</b>` +
        `<span class="th-score">${esc(a.score_text)}</span><span class="th-diff">${esc(a.diff_text)}</span></div>` +
        (a.reply_san ? `<p>Reply <b>${esc(a.reply_san)}</b>${a.reply_idea ? ` ${esc(a.reply_idea)}` : ""}.</p>` : "") +
        `<p class="muted">${esc(a.line)}</p></div>`;
    }
    for (const r of e.refuted || []) {
      body += `<div class="th-alt refuted"><div class="th-alt-top"><b>${esc(r.san)}?</b>` +
        `<span class="th-score">≤ ${esc(r.bound_text)}</span><span class="th-diff">tempting, refuted</span></div>` +
        `<p>${esc(r.why)}${r.reply_idea ? ` (${esc(r.refutation_san)} ${esc(r.reply_idea)}.)` : ""}</p></div>`;
    }
    html += section("Why not the alternatives", body);
  }

  if (e.eval_changes && e.eval_changes.length) {
    const max = Math.max(...e.eval_changes.map((c) => Math.abs(c.delta)), 50);
    html += section("What changes in the evaluation", e.eval_changes.map((c) => {
      const w = Math.round((Math.abs(c.delta) / max) * 100);
      return `<div class="th-term"><span>${esc(c.label)}</span>` +
        `<div class="th-bar"><i class="${c.delta > 0 ? "up" : "down"}" style="width:${w}%"></i></div>` +
        `<b class="${c.delta > 0 ? "up" : "down"}">${c.delta > 0 ? "+" : "−"}${(Math.abs(c.delta) / 100).toFixed(2)}</b></div>`;
    }).join("") + `<p class="muted">Along the expected line, from the AI's point of view.</p>`);
  }

  if (e.search && e.search.length) {
    let body = e.search.map((s) => `<p>${esc(s)}</p>`).join("");
    if (e.depth_story && e.depth_story.length) {
      body += `<ol class="th-depths">${e.depth_story.map((d) => `<li>${esc(d)}</li>`).join("")}</ol>`;
    }
    body += `<button class="btn" type="button" id="btn-tree">🌳 Show the search tree</button>`;
    html += section("How minimax &amp; alpha-beta found it", body);
  }

  box.innerHTML = html;
  const btn = box.querySelector("#btn-tree");
  if (btn) btn.addEventListener("click", () => onTree(report.ply));
}

function section(title, body) {
  return `<section class="th-sec"><h4>${title}</h4>${body}</section>`;
}
