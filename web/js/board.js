// Chess board component, written from scratch (no chess or UI libraries).
//
// The board is 64 square <div>s plus one absolutely positioned <div> per piece. A piece
// moves by changing its CSS transform, so moves animate smoothly; captured pieces fade out.
// Squares are numbered like the engine: a1 = 0, b1 = 1, ... h8 = 63.

const GLYPHS = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
const TEXT = "︎"; // ask for the text (not emoji) form of the glyph
const FILES = "abcdefgh";

export const squareName = (sq) => FILES[sq % 8] + (Math.floor(sq / 8) + 1);
export const parseSquare = (name) => FILES.indexOf(name[0]) + 8 * (Number(name[1]) - 1);

/** FEN board part -> Map(square -> piece letter, uppercase = white). */
export function parseFen(fen) {
  const map = new Map();
  const rows = fen.split(" ")[0].split("/");
  rows.forEach((row, i) => {
    let file = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) file += Number(ch);
      else { map.set((7 - i) * 8 + file, ch); file++; }
    }
  });
  return map;
}

const colorOf = (letter) => (letter === letter.toUpperCase() ? "white" : "black");

export class ChessBoard {
  /**
   * @param {HTMLElement} el container
   * @param {{onMove: (uci: string) => void}} options
   */
  constructor(el, { onMove }) {
    this.el = el;
    this.onMove = onMove;
    this.orientation = "white";
    this.pieces = new Map(); // square -> element
    this.position = new Map(); // square -> letter
    this.interactive = null; // {color, legal: {from: [to]}}
    this.selected = null;
    this.drag = null;
    this.lastMove = null;
    this.checkSquare = null;
    this.promo = null;

    this.squaresLayer = document.createElement("div");
    this.el.append(this.squaresLayer);
    this._buildSquares();

    new ResizeObserver(() => this._resize()).observe(this.el);
    this._resize();
    this.el.addEventListener("pointerdown", (e) => this._pointerDown(e));
    this.el.addEventListener("pointermove", (e) => this._pointerMove(e));
    this.el.addEventListener("pointerup", (e) => this._pointerUp(e));
    this.el.addEventListener("pointercancel", () => this._cancelDrag());
    this.el.addEventListener("contextmenu", (e) => e.preventDefault());
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this._closePromo(); this._select(null); }
    });
  }

  // ------------------------------------------------------------ geometry

  _resize() {
    this.sq = this.el.clientWidth / 8;
    this.el.style.setProperty("--sq", `${this.sq}px`);
  }

  _xy(sq) {
    const file = sq % 8, rank = Math.floor(sq / 8);
    return this.orientation === "white" ? [file, 7 - rank] : [7 - file, rank];
  }

  _place(el, sq) {
    const [x, y] = this._xy(sq);
    const t = `translate(${x * 100}%, ${y * 100}%)`;
    el.style.transform = t;
    el.style.setProperty("--at", t);
  }

  _squareAt(clientX, clientY) {
    const r = this.el.getBoundingClientRect();
    const x = Math.floor(((clientX - r.left) / r.width) * 8);
    const y = Math.floor(((clientY - r.top) / r.height) * 8);
    if (x < 0 || x > 7 || y < 0 || y > 7) return null;
    return this.orientation === "white" ? (7 - y) * 8 + x : y * 8 + (7 - x);
  }

  // ------------------------------------------------------------ squares

  _buildSquares() {
    this.squaresLayer.replaceChildren();
    this.squareEls = new Array(64);
    for (let sq = 0; sq < 64; sq++) {
      const d = document.createElement("div");
      const file = sq % 8, rank = Math.floor(sq / 8);
      d.className = `square ${(file + rank) % 2 ? "light" : "dark"}`;
      const [x, y] = this._xy(sq);
      d.style.left = `${x * 12.5}%`;
      d.style.top = `${y * 12.5}%`;
      if (y === 7) d.insertAdjacentHTML("beforeend", `<span class="coord file">${FILES[file]}</span>`);
      if (x === 0) d.insertAdjacentHTML("beforeend", `<span class="coord rank">${rank + 1}</span>`);
      this.squareEls[sq] = d;
      this.squaresLayer.append(d);
    }
    this._paintHighlights();
  }

  _paintHighlights() {
    const legal = this.selected !== null && this.interactive
      ? (this.interactive.legal[squareName(this.selected)] || []).map(parseSquare) : [];
    this.squareEls.forEach((d, sq) => {
      d.classList.toggle("last", !!this.lastMove && this.lastMove.includes(sq));
      d.classList.toggle("selected", sq === this.selected);
      d.classList.toggle("check", sq === this.checkSquare);
      d.classList.toggle("target", legal.includes(sq));
      d.classList.toggle("occupied", this.position.has(sq));
    });
  }

  setOrientation(color) {
    if (color === this.orientation) return;
    this.orientation = color;
    this._buildSquares();
    for (const [sq, el] of this.pieces) this._place(el, sq);
  }

  flip() { this.setOrientation(this.orientation === "white" ? "black" : "white"); }

  // ------------------------------------------------------------ pieces

  _makePiece(letter, sq) {
    const el = document.createElement("div");
    el.className = `piece ${letter === letter.toUpperCase() ? "w" : "b"}`;
    el.dataset.piece = letter;
    el.textContent = GLYPHS[letter.toLowerCase()] + TEXT;
    el.setAttribute("aria-label", `${colorOf(letter)} ${letter.toLowerCase()} on ${squareName(sq)}`);
    this._place(el, sq);
    this.el.append(el);
    return el;
  }

  _setLetter(el, letter) {
    el.dataset.piece = letter;
    el.className = `piece ${letter === letter.toUpperCase() ? "w" : "b"}`;
    el.textContent = GLYPHS[letter.toLowerCase()] + TEXT;
  }

  _removePiece(sq, fade) {
    const el = this.pieces.get(sq);
    if (!el) return;
    this.pieces.delete(sq);
    if (fade) {
      el.classList.add("captured-out");
      setTimeout(() => el.remove(), 230);
    } else el.remove();
  }

  /** Move piece elements for ``uci`` (handles captures, castling, en passant). */
  _animateMove(uci, instant = false) {
    const from = parseSquare(uci.slice(0, 2)), to = parseSquare(uci.slice(2, 4));
    const el = this.pieces.get(from);
    if (!el) return;
    const letter = el.dataset.piece;
    if (this.pieces.has(to)) this._removePiece(to, true);
    // en passant: a pawn moving diagonally to an empty square captures behind it
    if (letter.toLowerCase() === "p" && from % 8 !== to % 8 && !this.position.has(to)) {
      this._removePiece(letter === "P" ? to - 8 : to + 8, true);
    }
    // castling: the king moves two files, so move the rook too
    if (letter.toLowerCase() === "k" && Math.abs((from % 8) - (to % 8)) === 2) {
      const rookFrom = to > from ? from + 3 : from - 4;
      const rookTo = to > from ? from + 1 : from - 1;
      const rook = this.pieces.get(rookFrom);
      if (rook) {
        this.pieces.delete(rookFrom);
        this.pieces.set(rookTo, rook);
        this._place(rook, rookTo);
      }
    }
    if (instant) el.style.transition = "none";
    this.pieces.delete(from);
    this.pieces.set(to, el);
    this._place(el, to);
    if (uci.length === 5) {
      const promo = letter === "P" ? uci[4].toUpperCase() : uci[4];
      setTimeout(() => this._setLetter(el, promo), instant ? 0 : 200);
    }
    if (instant) requestAnimationFrame(() => (el.style.transition = ""));
    // keep `position` in step so further logic (dots, en passant) sees the new board
    this.position.delete(from);
    this.position.set(to, uci.length === 5 ? (letter === "P" ? uci[4].toUpperCase() : uci[4]) : letter);
  }

  /**
   * Show a position.
   * @param {string} fen
   * @param {{animate?: string|null, lastMove?: string|null, check?: boolean}} opts
   *   animate: UCI of the move that led here (animated); lastMove: highlight it;
   *   check: highlight the king of the side to move.
   */
  setPosition(fen, { animate = null, lastMove = null, check = false } = {}) {
    this._closePromo();
    if (animate) this._animateMove(animate);
    const target = parseFen(fen);
    // reconcile: whatever does not match the FEN is fixed without animation
    for (const [sq, el] of [...this.pieces]) {
      const want = target.get(sq);
      if (!want) this._removePiece(sq, !!animate);
      else if (el.dataset.piece !== want) this._setLetter(el, want);
    }
    for (const [sq, letter] of target) {
      if (!this.pieces.has(sq)) this.pieces.set(sq, this._makePiece(letter, sq));
    }
    this.position = target;
    this.lastMove = lastMove
      ? [parseSquare(lastMove.slice(0, 2)), parseSquare(lastMove.slice(2, 4))] : null;
    const turnWhite = fen.split(" ")[1] === "w";
    this.checkSquare = null;
    if (check) {
      for (const [sq, letter] of target) if (letter === (turnWhite ? "K" : "k")) this.checkSquare = sq;
    }
    this._select(null);
  }

  /** Allow the human to move pieces of ``color`` (null = no moves allowed). */
  setInteractive(color, legal) {
    this.interactive = color ? { color, legal: legal || {} } : null;
    for (const [sq, el] of this.pieces) {
      el.classList.toggle("movable", !!this.interactive && this._canMoveFrom(sq));
    }
    if (!this.interactive) this._select(null);
    else this._paintHighlights();
  }

  _canMoveFrom(sq) {
    if (!this.interactive) return false;
    const letter = this.position.get(sq);
    return !!letter && colorOf(letter) === this.interactive.color &&
      (this.interactive.legal[squareName(sq)] || []).length > 0;
  }

  _targets(from) {
    if (!this.interactive || from === null) return [];
    return (this.interactive.legal[squareName(from)] || []).map(parseSquare);
  }

  _select(sq) {
    this.selected = sq;
    this._paintHighlights();
  }

  // ------------------------------------------------------------ input

  _pointerDown(e) {
    if (e.button !== 0 || this.promo) return;
    const sq = this._squareAt(e.clientX, e.clientY);
    if (sq === null) return;
    if (this.selected !== null && this._targets(this.selected).includes(sq)) {
      this._tryMove(this.selected, sq, false);
      return;
    }
    if (!this._canMoveFrom(sq)) { this._select(null); return; }
    this._select(sq);
    const el = this.pieces.get(sq);
    this.drag = { from: sq, el, x: e.clientX, y: e.clientY, moved: false };
    this.el.setPointerCapture(e.pointerId);
  }

  _pointerMove(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4) return;
    d.moved = true;
    d.el.classList.add("dragging");
    const r = this.el.getBoundingClientRect();
    const px = e.clientX - r.left - this.sq / 2, py = e.clientY - r.top - this.sq / 2;
    d.el.style.transform = `translate(${px}px, ${py}px)`;
    const over = this._squareAt(e.clientX, e.clientY);
    this.squareEls.forEach((s, i) => s.classList.toggle("drop", i === over && this._targets(d.from).includes(i)));
  }

  _pointerUp(e) {
    const d = this.drag;
    this.drag = null;
    if (!d) return;
    this.squareEls.forEach((s) => s.classList.remove("drop"));
    d.el.classList.remove("dragging");
    if (!d.moved) return; // a click: keep the piece selected
    const to = this._squareAt(e.clientX, e.clientY);
    if (to !== null && this._targets(d.from).includes(to)) {
      this._tryMove(d.from, to, true);
    } else {
      d.el.style.transition = "none";
      this._place(d.el, d.from); // snap back
      requestAnimationFrame(() => (d.el.style.transition = ""));
      if (to !== d.from) this._select(null);
    }
  }

  _cancelDrag() {
    if (!this.drag) return;
    this._place(this.drag.el, this.drag.from);
    this.drag.el.classList.remove("dragging");
    this.drag = null;
  }

  _tryMove(from, to, dropped) {
    const letter = this.position.get(from);
    const rank = Math.floor(to / 8);
    const isPromotion = letter && letter.toLowerCase() === "p" && (rank === 7 || rank === 0);
    const uci = squareName(from) + squareName(to);
    if (isPromotion) {
      if (dropped) this._place(this.pieces.get(from), from);
      this._showPromo(from, to, letter === "P" ? "white" : "black");
      return;
    }
    this._commit(uci, dropped);
  }

  _commit(uci, instant) {
    this._animateMove(uci, instant);
    this.lastMove = [parseSquare(uci.slice(0, 2)), parseSquare(uci.slice(2, 4))];
    this.checkSquare = null;
    this.setInteractive(null);
    this.onMove(uci);
  }

  _showPromo(from, to, color) {
    this._closePromo();
    const [x, y] = this._xy(to);
    const box = document.createElement("div");
    box.className = "promo";
    box.style.left = `${x * 12.5}%`;
    const fromTop = y === 0;
    box.style[fromTop ? "top" : "bottom"] = "0";
    for (const p of ["q", "r", "b", "n"]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = `piece-btn ${color === "white" ? "w" : "b"}`;
      b.textContent = GLYPHS[p] + TEXT;
      b.style.color = color === "white" ? "#fbfaf7" : "#26221e";
      b.style.webkitTextStroke = color === "white" ? "1px #2a2622" : "0";
      b.setAttribute("aria-label", { q: "Queen", r: "Rook", b: "Bishop", n: "Knight" }[p]);
      b.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        this._closePromo();
        this._commit(squareName(from) + squareName(to) + p, false);
      });
      box.append(b);
    }
    this.el.append(box);
    this.promo = box;
  }

  _closePromo() {
    if (this.promo) { this.promo.remove(); this.promo = null; }
  }
}
