// Board host: lets the page switch between board views (Plain, 3D, Battle) without the
// game logic noticing. app.js talks to the host exactly as it talked to the plain board;
// the host forwards every call to the active view and remembers the latest position,
// orientation and move permissions, so a newly created view starts in the same state.
//
// Every view implements the same small interface:
//   constructor(el, {onMove, mode})   destroy()
//   position (Map square -> piece letter)
//   setOrientation(color)   setPosition(fen, {animate, lastMove, check})
//   setInteractive(color, legalMoves)

import { ChessBoard } from "./board.js";

export const MODES = ["plain", "3d", "battle"];
const STORAGE_KEY = "boardMode";

/** True when the browser can draw WebGL (needed by the 3D and Battle views). */
export function webglAvailable() {
  try {
    const c = document.createElement("canvas");
    return !!(window.WebGLRenderingContext && (c.getContext("webgl2") || c.getContext("webgl")));
  } catch {
    return false;
  }
}

export function savedMode() {
  let mode = "plain";
  try { mode = localStorage.getItem(STORAGE_KEY) || "plain"; } catch { /* storage blocked */ }
  return MODES.includes(mode) ? mode : "plain";
}

export class BoardHost {
  /**
   * @param {HTMLElement} el container the views draw into
   * @param {{onMove: (uci: string) => void, onModeChange?: (mode: string) => void}} options
   */
  constructor(el, { onMove, onModeChange = () => {} }) {
    this.el = el;
    this.onMove = onMove;
    this.onModeChange = onModeChange;
    this.mode = "plain";
    this.view = new ChessBoard(el, { onMove });
    this.last = { orientation: "white", fen: null, lastMove: null, check: false,
                  color: null, legal: null };
    this.switching = null;
  }

  get position() { return this.view.position; }

  setOrientation(color) {
    this.last.orientation = color;
    this.view.setOrientation(color);
  }

  flip() { this.setOrientation(this.last.orientation === "white" ? "black" : "white"); }

  setPosition(fen, opts = {}) {
    Object.assign(this.last, { fen, lastMove: opts.lastMove ?? null, check: !!opts.check });
    this.view.setPosition(fen, opts);
  }

  setInteractive(color, legal) {
    Object.assign(this.last, { color, legal });
    this.view.setInteractive(color, legal);
  }

  /**
   * Switch to another view. The 3D code (and Three.js) is only downloaded the first
   * time a 3D mode is chosen, so the plain board stays fast.
   * @returns {Promise<string>} the mode actually in use (falls back to "plain")
   */
  async setMode(mode) {
    if (!MODES.includes(mode)) mode = "plain";
    if (mode !== "plain" && !webglAvailable()) mode = "plain";
    if (mode === this.mode && !this.switching) return mode;
    const ticket = (this.switching = Symbol(mode));
    let View = ChessBoard;
    if (mode !== "plain") {
      try {
        View = (await import("./board3d.js")).Board3D;
      } catch (err) {
        console.error("3D board failed to load", err);
        mode = "plain";
      }
    }
    if (this.switching !== ticket) return this.mode; // a newer switch won
    this.switching = null;

    this.view.destroy();
    this.el.classList.toggle("board-3d", mode !== "plain");
    this.el.dataset.mode = mode;
    try {
      this.view = new View(this.el, { onMove: this.onMove, mode });
    } catch (err) { // e.g. WebGL context refused
      console.error("board view failed", err);
      this.el.replaceChildren();
      this.el.classList.remove("board-3d");
      mode = "plain";
      this.view = new ChessBoard(this.el, { onMove: this.onMove });
    }
    this.mode = mode;
    this._replay();
    try { localStorage.setItem(STORAGE_KEY, mode); } catch { /* storage blocked */ }
    this.onModeChange(mode);
    return mode;
  }

  /** Opening animation of the 3D views (the plain board has none). */
  playIntro(options) {
    this.view.playIntro?.(options);
  }

  _replay() {
    const s = this.last;
    this.view.setOrientation(s.orientation);
    if (s.fen) this.view.setPosition(s.fen, { lastMove: s.lastMove, check: s.check });
    this.view.setInteractive(s.color, s.legal);
    this.view.playIntro?.({ drop: false });
  }
}
