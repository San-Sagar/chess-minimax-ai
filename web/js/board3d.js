// 3D board view (Three.js). Same interface as the plain board (see boardhost.js).
//
// World layout: one board square = 1 unit. Square a1 is at x = -3.5, z = +3.5 and h8 at
// x = +3.5, z = -3.5, so White sits on the +z side. Pieces are built in code
// (pieces3d.js), nothing is downloaded.

import * as THREE from "three";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { parseFen, parseSquare, squareName } from "./board.js";
import { buildPiece } from "./pieces3d.js";

const colorOf = (letter) => (letter === letter.toUpperCase() ? "white" : "black");
const sqX = (sq) => (sq % 8) - 3.5;
const sqZ = (sq) => 3.5 - Math.floor(sq / 8);
const TILE_LIGHT = new THREE.Color("#e9d7b5");
const TILE_DARK = new THREE.Color("#a0714a");
const MARK = { last: new THREE.Color("#d8c34a"), selected: new THREE.Color("#5fb36a"),
               check: new THREE.Color("#e0503c") };
const MOVE_MS = 380;

const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

export class Board3D {
  constructor(el, { onMove, mode = "3d" }) {
    this.el = el;
    this.onMove = onMove;
    this.mode = mode;
    this.orientation = "white";
    this.position = new Map(); // square -> letter
    this.meshes = new Map(); // square -> piece Object3D
    this.interactive = null;
    this.selected = null;
    this.lastMove = null;
    this.checkSquare = null;
    this.tweens = [];
    this.promo = null;

    // renderer, scene, camera
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.className = "board3d-canvas";
    el.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enablePan: false, enableDamping: true, dampingFactor: 0.08,
                                   minDistance: 7, maxDistance: 20, maxPolarAngle: 1.35 });

    this._buildLights();
    this._buildBoard();
    this._resetCamera();

    // input: our handler runs first (capture phase on the container) so clicking a piece
    // selects it instead of rotating the camera
    this.raycaster = new THREE.Raycaster();
    this.listeners = [
      [el, "pointerdown", (e) => this._pointerDown(e), true],
      [el, "contextmenu", (e) => e.preventDefault(), false],
      [document, "keydown", (e) => { if (e.key === "Escape") { this._closePromo(); this._select(null); } }, false],
    ];
    for (const [t, type, fn, cap] of this.listeners) t.addEventListener(type, fn, cap);

    this.resizer = new ResizeObserver(() => this._resize());
    this.resizer.observe(el);
    this._resize();
    this.running = true;
    const loop = (now) => {
      if (!this.running) return;
      this._tick(now);
      this.frame = requestAnimationFrame(loop);
    };
    this.frame = requestAnimationFrame(loop);
  }

  destroy() {
    this.running = false;
    cancelAnimationFrame(this.frame);
    this.resizer.disconnect();
    for (const [t, type, fn, cap] of this.listeners) t.removeEventListener(type, fn, cap);
    this.controls.dispose();
    this.scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) [].concat(o.material).forEach((m) => m.dispose());
    });
    this.renderer.dispose();
    this.el.replaceChildren();
  }

  // ------------------------------------------------------------ scene

  _buildLights() {
    this.scene.add(new THREE.HemisphereLight("#fff6e8", "#3a3026", 1.1));
    const sun = new THREE.DirectionalLight("#ffffff", 2.2);
    sun.position.set(4, 10, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6, near: 1, far: 30 });
    sun.shadow.bias = -0.0005;
    this.scene.add(sun);
  }

  _buildBoard() {
    const frame = new THREE.Mesh(new THREE.BoxGeometry(9, 0.4, 9),
      new THREE.MeshStandardMaterial({ color: "#4a2f1d", roughness: 0.7 }));
    frame.position.y = -0.25;
    frame.receiveShadow = true;
    this.scene.add(frame);

    this.tiles = [];
    const geo = new THREE.BoxGeometry(1, 0.1, 1);
    for (let sq = 0; sq < 64; sq++) {
      const light = ((sq % 8) + Math.floor(sq / 8)) % 2 === 1;
      const tile = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
        color: light ? TILE_LIGHT : TILE_DARK, roughness: 0.55 }));
      tile.position.set(sqX(sq), -0.05, sqZ(sq));
      tile.receiveShadow = true;
      tile.userData = { sq, base: light ? TILE_LIGHT : TILE_DARK };
      this.tiles.push(tile);
      this.scene.add(tile);
    }

    // legal-move markers: one dot and one ring per square, shown as needed
    this.dots = [];
    const dotGeo = new THREE.CircleGeometry(0.16, 24);
    const ringGeo = new THREE.RingGeometry(0.38, 0.46, 32);
    const dotMat = new THREE.MeshBasicMaterial({ color: "#1d4d2b", transparent: true, opacity: 0.55 });
    for (let sq = 0; sq < 64; sq++) {
      const dot = new THREE.Mesh(dotGeo, dotMat);
      const ring = new THREE.Mesh(ringGeo, dotMat);
      for (const m of [dot, ring]) {
        m.rotation.x = -Math.PI / 2;
        m.position.set(sqX(sq), 0.011, sqZ(sq));
        m.visible = false;
        this.scene.add(m);
      }
      this.dots.push({ dot, ring });
    }
  }

  _resetCamera() {
    const side = this.orientation === "white" ? 1 : -1;
    this.camera.position.set(0, 12.2, 9.6 * side);
    this.controls.target.set(0, 0, 0.3 * side);
    this.controls.update();
  }

  _resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _tick(now) {
    this.tweens = this.tweens.filter((tw) => {
      const t = Math.min(1, (now - tw.start) / tw.ms);
      tw.step(easeInOut(t));
      if (t >= 1) { tw.done?.(); return false; }
      return true;
    });
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  _tween(ms, step, done) {
    this.tweens.push({ start: performance.now(), ms, step, done });
  }

  // ------------------------------------------------------------ pieces

  _addPiece(letter, sq) {
    const obj = buildPiece(letter.toLowerCase(), colorOf(letter));
    obj.position.set(sqX(sq), 0, sqZ(sq));
    obj.userData.letter = letter;
    this.scene.add(obj);
    this.meshes.set(sq, obj);
    return obj;
  }

  _removePiece(sq, fade) {
    const obj = this.meshes.get(sq);
    if (!obj) return;
    this.meshes.delete(sq);
    if (!fade) { this._dispose(obj); return; }
    const y0 = obj.position.y;
    this._tween(300, (t) => {
      obj.position.y = y0 - 0.9 * t;
      obj.scale.setScalar(1 - 0.6 * t);
    }, () => this._dispose(obj));
  }

  _dispose(obj) {
    this.scene.remove(obj);
    obj.traverse((o) => o.geometry?.dispose());
  }

  _slide(obj, to, ms = MOVE_MS, hop = 0.5) {
    const x0 = obj.position.x, z0 = obj.position.z, x1 = sqX(to), z1 = sqZ(to);
    this._tween(ms, (t) => {
      obj.position.x = x0 + (x1 - x0) * t;
      obj.position.z = z0 + (z1 - z0) * t;
      obj.position.y = Math.sin(Math.PI * t) * hop;
    });
  }

  _replaceLetter(sq, letter) {
    this._removePiece(sq, false);
    this._addPiece(letter, sq);
  }

  /** Move piece objects for ``uci`` (handles captures, castling, en passant, promotion). */
  _animateMove(uci) {
    const from = parseSquare(uci.slice(0, 2)), to = parseSquare(uci.slice(2, 4));
    const obj = this.meshes.get(from);
    if (!obj) return;
    const letter = obj.userData.letter;
    if (this.meshes.has(to)) this._removePiece(to, true);
    if (letter.toLowerCase() === "p" && from % 8 !== to % 8 && !this.position.has(to)) {
      this._removePiece(letter === "P" ? to - 8 : to + 8, true);
    }
    if (letter.toLowerCase() === "k" && Math.abs((from % 8) - (to % 8)) === 2) {
      const rookFrom = to > from ? from + 3 : from - 4, rookTo = to > from ? from + 1 : from - 1;
      const rook = this.meshes.get(rookFrom);
      if (rook) {
        this.meshes.delete(rookFrom);
        this.meshes.set(rookTo, rook);
        this._slide(rook, rookTo);
      }
    }
    this.meshes.delete(from);
    this.meshes.set(to, obj);
    const knight = letter.toLowerCase() === "n";
    this._slide(obj, to, MOVE_MS, knight ? 0.9 : 0.25);
    let after = letter;
    if (uci.length === 5) {
      after = letter === "P" ? uci[4].toUpperCase() : uci[4];
      setTimeout(() => { if (this.meshes.get(to) === obj) this._replaceLetter(to, after); }, MOVE_MS);
    }
    this.position.delete(from);
    this.position.set(to, after);
  }

  // ------------------------------------------------------------ interface

  setOrientation(color) {
    if (color === this.orientation) return;
    this.orientation = color;
    this._resetCamera();
  }

  setPosition(fen, { animate = null, lastMove = null, check = false } = {}) {
    this._closePromo();
    if (animate) this._animateMove(animate);
    const target = parseFen(fen);
    for (const [sq, obj] of [...this.meshes]) {
      const want = target.get(sq);
      if (!want) this._removePiece(sq, !!animate);
      else if (obj.userData.letter !== want) this._replaceLetter(sq, want);
    }
    for (const [sq, letter] of target) if (!this.meshes.has(sq)) this._addPiece(letter, sq);
    this.position = target;
    this.lastMove = lastMove ? [parseSquare(lastMove.slice(0, 2)), parseSquare(lastMove.slice(2, 4))] : null;
    const turnWhite = fen.split(" ")[1] === "w";
    this.checkSquare = null;
    if (check) for (const [sq, l] of target) if (l === (turnWhite ? "K" : "k")) this.checkSquare = sq;
    this._select(null);
  }

  setInteractive(color, legal) {
    this.interactive = color ? { color, legal: legal || {} } : null;
    if (!this.interactive) this._select(null);
    else this._paint();
  }

  // ------------------------------------------------------------ highlights & input

  _targets(from) {
    if (!this.interactive || from === null) return [];
    return (this.interactive.legal[squareName(from)] || []).map(parseSquare);
  }

  _canMoveFrom(sq) {
    const letter = this.position.get(sq);
    return !!this.interactive && !!letter && colorOf(letter) === this.interactive.color &&
      this._targets(sq).length > 0;
  }

  _select(sq) {
    this.selected = sq;
    this._paint();
  }

  _paint() {
    const targets = this._targets(this.selected);
    this.tiles.forEach((tile, sq) => {
      let c = tile.userData.base;
      if (this.lastMove && this.lastMove.includes(sq)) c = c.clone().lerp(MARK.last, 0.55);
      if (sq === this.selected) c = c.clone().lerp(MARK.selected, 0.6);
      if (sq === this.checkSquare) c = c.clone().lerp(MARK.check, 0.75);
      tile.material.color.copy(c);
    });
    this.dots.forEach(({ dot, ring }, sq) => {
      const on = targets.includes(sq);
      const capture = on && this.position.has(sq);
      dot.visible = on && !capture;
      ring.visible = capture;
    });
    this.el.style.cursor = "";
  }

  /** Square under the pointer (a piece counts as its square), or null. */
  _squareAt(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                                  -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const pieces = [...this.meshes.values()];
    const hit = this.raycaster.intersectObjects([...pieces, ...this.tiles], true)[0];
    if (!hit) return null;
    let o = hit.object;
    while (o && o.userData.sq === undefined && !pieces.includes(o)) o = o.parent;
    if (!o) return null;
    if (o.userData.sq !== undefined) return o.userData.sq;
    for (const [sq, obj] of this.meshes) if (obj === o) return sq;
    return null;
  }

  _pointerDown(e) {
    if (e.button !== 0 || this.promo) return;
    const sq = this._squareAt(e);
    if (sq === null) return; // empty space: let the camera rotate
    if (this.selected !== null && this._targets(this.selected).includes(sq)) {
      e.stopPropagation();
      this._tryMove(this.selected, sq);
      return;
    }
    if (this._canMoveFrom(sq)) {
      e.stopPropagation(); // picking a piece, not rotating
      this._select(sq === this.selected ? null : sq);
    } else if (this.selected !== null) {
      this._select(null);
    }
  }

  _tryMove(from, to) {
    const letter = this.position.get(from);
    const rank = Math.floor(to / 8);
    if (letter && letter.toLowerCase() === "p" && (rank === 7 || rank === 0)) {
      this._showPromo(from, to, colorOf(letter));
      return;
    }
    this._commit(squareName(from) + squareName(to));
  }

  _commit(uci) {
    this._animateMove(uci);
    this.lastMove = [parseSquare(uci.slice(0, 2)), parseSquare(uci.slice(2, 4))];
    this.checkSquare = null;
    this.setInteractive(null);
    this.onMove(uci);
  }

  _showPromo(from, to, color) {
    this._closePromo();
    const box = document.createElement("div");
    box.className = "promo promo-3d";
    const glyphs = color === "white" ? { q: "♕", r: "♖", b: "♗", n: "♘" } : { q: "♛", r: "♜", b: "♝", n: "♞" };
    for (const p of ["q", "r", "b", "n"]) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "piece-btn";
      b.textContent = glyphs[p] + "︎";
      b.setAttribute("aria-label", { q: "Queen", r: "Rook", b: "Bishop", n: "Knight" }[p]);
      b.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        this._closePromo();
        this._commit(squareName(from) + squareName(to) + p);
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
