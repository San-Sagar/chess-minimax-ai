// 3D board view (Three.js). Same interface as the plain board (see boardhost.js).
//
// World layout: one board square = 1 unit. Square a1 is at x = -3.5, z = +3.5 and h8 at
// x = +3.5, z = -3.5, so White sits on the +z side. The board's top surface is y = 0.
// Pieces and wood are made in code (pieces3d.js, textures3d.js); nothing is downloaded.

import * as THREE from "three";
import { OrbitControls } from "../vendor/three/OrbitControls.js";
import { RoomEnvironment } from "../vendor/three/RoomEnvironment.js";
import { parseFen, parseSquare, squareName } from "./board.js";
import { buildPiece } from "./pieces3d.js";
import { WOODS, labelTexture, woodTexture } from "./textures3d.js";

const FILES = "abcdefgh";
const colorOf = (letter) => (letter === letter.toUpperCase() ? "white" : "black");
const sqX = (sq) => (sq % 8) - 3.5;
const sqZ = (sq) => 3.5 - Math.floor(sq / 8);
const MARK = { last: new THREE.Color("#e6cf4f"), selected: new THREE.Color("#58b368"),
               check: new THREE.Color("#ff3b25"), drop: new THREE.Color("#7fd18c") };
const MOVE_MS = 420;
const INTRO_MS = 4200;
const START_COUNT = { p: 8, n: 2, b: 2, r: 2, q: 1 };
const TRAY_ORDER = "qrbnp";

const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const easeOut = (t) => 1 - (1 - t) ** 3;
const clamp01 = (t) => Math.min(1, Math.max(0, t));

export class Board3D {
  constructor(el, { onMove, mode = "3d" }) {
    this.el = el;
    this.onMove = onMove;
    this.mode = mode;
    this.orientation = "white";
    this.position = new Map(); // square -> letter
    this.meshes = new Map(); // square -> piece group
    this.interactive = null;
    this.selected = null;
    this.lastMove = null;
    this.checkSquare = null;
    this.dropSquare = null;
    this.drag = null;
    this.tweens = [];
    this.promo = null;
    this.intro = null;
    this.traySignature = "";
    this.trayY = -0.6; // height of the table the captured pieces stand on

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.domElement.className = "board3d-canvas";
    el.append(this.renderer.domElement);

    this.scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture; // soft reflections
    this.scene.environment = this.envMap;
    this.scene.environmentIntensity = 0.55;
    pmrem.dispose();

    this.camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enablePan: false, enableDamping: true, dampingFactor: 0.08,
                                   minDistance: 8, maxDistance: 22, maxPolarAngle: 1.3,
                                   rotateSpeed: 0.7 });

    this._buildLights();
    this._buildBoard();
    this.trays = new THREE.Group();
    this.scene.add(this.trays);
    this._resetCamera();

    this.raycaster = new THREE.Raycaster();
    this.groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    this.listeners = [
      // capture phase on the container: runs before the camera controls, so picking up a
      // piece doesn't also rotate the view
      [el, "pointerdown", (e) => this._pointerDown(e), true],
      [el, "pointermove", (e) => this._hover(e), false],
      [window, "pointermove", (e) => this._dragMove(e), false],
      [window, "pointerup", (e) => this._dragEnd(e), false],
      [window, "pointercancel", () => this._dragCancel(), false],
      [el, "contextmenu", (e) => e.preventDefault(), false],
      [document, "keydown", (e) => {
        if (e.key === "Escape") { this._closePromo(); this._dragCancel(); this._select(null); }
      }, false],
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
    this.envMap.dispose();
    this.renderer.dispose();
    this.el.style.cursor = "";
    this.el.replaceChildren();
  }

  // ------------------------------------------------------------ scene

  _buildLights() {
    this.scene.add(new THREE.HemisphereLight("#fff4e0", "#2b2118", 0.9));
    const key = new THREE.DirectionalLight("#fff1dc", 2.6);
    key.position.set(5, 11, 6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -7, right: 7, top: 7, bottom: -7, near: 2, far: 30 });
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.02;
    key.shadow.radius = 4;
    this.scene.add(key);
    const rim = new THREE.DirectionalLight("#9fb6ff", 0.6); // cool light from behind
    rim.position.set(-6, 5, -8);
    this.scene.add(rim);
  }

  _buildBoard() {
    // inlaid squares: maple and walnut, each showing a different part of the grain
    this._buildTiles(woodTexture("maple", WOODS.maple), woodTexture("walnut", WOODS.walnut),
                     { roughness: 0.38, clearcoat: 0.35, clearcoatRoughness: 0.3 });
    this._buildFrame();
    this._buildLabels("#e9d3a6");
    this._buildDots();
  }

  /** The 64 squares; each shows a different part of its texture. */
  _buildTiles(lightMap, darkMap, materialOptions) {
    this.tiles = [];
    const tileGeo = new THREE.BoxGeometry(1, 0.08, 1);
    for (let sq = 0; sq < 64; sq++) {
      const light = ((sq % 8) + Math.floor(sq / 8)) % 2 === 1;
      const map = (light ? lightMap : darkMap).clone();
      map.repeat.set(0.3, 0.3);
      map.offset.set((sq * 0.37) % 1, (sq * 0.61) % 1);
      if (sq % 3 === 0) map.rotation = Math.PI / 2;
      map.needsUpdate = true;
      const base = new THREE.Color("#ffffff");
      const tile = new THREE.Mesh(tileGeo, new THREE.MeshPhysicalMaterial({ map, color: base, ...materialOptions }));
      tile.position.set(sqX(sq), -0.04, sqZ(sq));
      tile.receiveShadow = true;
      tile.userData = { sq, base };
      this.tiles.push(tile);
      this.scene.add(tile);
    }
  }

  _buildFrame() {
    // frame: a thick border with a bevelled edge, and a darker plinth under it
    const frameMat = new THREE.MeshPhysicalMaterial({
      map: woodTexture("frame", WOODS.frame), roughness: 0.4, clearcoat: 0.5, clearcoatRoughness: 0.3 });
    const outer = new THREE.Shape();
    const R = 4.75, r = 4.0;
    outer.moveTo(-R, -R); outer.lineTo(R, -R); outer.lineTo(R, R); outer.lineTo(-R, R); outer.lineTo(-R, -R);
    const hole = new THREE.Path();
    hole.moveTo(-r, -r); hole.lineTo(-r, r); hole.lineTo(r, r); hole.lineTo(r, -r); hole.lineTo(-r, -r);
    outer.holes.push(hole);
    const frameGeo = new THREE.ExtrudeGeometry(outer, { depth: 0.36, bevelEnabled: true,
      bevelThickness: 0.06, bevelSize: 0.06, bevelSegments: 3 });
    frameGeo.rotateX(-Math.PI / 2);
    frameGeo.translate(0, -0.36, 0);
    const frame = new THREE.Mesh(frameGeo, frameMat);
    frame.castShadow = frame.receiveShadow = true;
    this.scene.add(frame);
    const under = new THREE.Mesh(new THREE.BoxGeometry(8.02, 0.3, 8.02), frameMat);
    under.position.y = -0.23;
    this.scene.add(under);
    const plinth = new THREE.Mesh(new THREE.BoxGeometry(10.1, 0.18, 10.1),
      new THREE.MeshStandardMaterial({ color: "#1d120b", roughness: 0.6 }));
    plinth.position.y = -0.52;
    plinth.receiveShadow = true;
    this.scene.add(plinth);

    // a soft shadow on the "table" under the board
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.35 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.62;
    ground.receiveShadow = true;
    this.scene.add(ground);
  }

  /** a-h and 1-8 on all four sides of the board. */
  _buildLabels(color) {
    this.labels = [];
    const labelGeo = new THREE.PlaneGeometry(0.42, 0.42);
    const along = [-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5];
    const edge = 4.38;
    along.forEach((p, i) => {
      for (const side of [1, -1]) {
        for (const [text, x, z] of [[FILES[i], p, side * edge], [String(i + 1), side * edge, -p]]) {
          const m = new THREE.Mesh(labelGeo, new THREE.MeshBasicMaterial({
            map: labelTexture(text, color), transparent: true, depthWrite: false }));
          m.rotation.x = -Math.PI / 2;
          m.position.set(x, 0.065, z);
          this.labels.push(m);
          this.scene.add(m);
        }
      }
    });
  }

  /** Legal-move markers: a dot for a quiet move, a ring for a capture. */
  _buildDots() {
    this.dots = [];
    const dotGeo = new THREE.CircleGeometry(0.15, 28);
    const ringGeo = new THREE.RingGeometry(0.39, 0.47, 40);
    const dotMat = new THREE.MeshBasicMaterial({ color: "#123d20", transparent: true, opacity: 0.5,
                                                 depthWrite: false });
    for (let sq = 0; sq < 64; sq++) {
      const dot = new THREE.Mesh(dotGeo, dotMat), ring = new THREE.Mesh(ringGeo, dotMat);
      for (const m of [dot, ring]) {
        m.rotation.x = -Math.PI / 2;
        m.position.set(sqX(sq), 0.004, sqZ(sq));
        m.visible = false;
        this.scene.add(m);
      }
      this.dots.push({ dot, ring });
    }
  }

  /** Camera spot for the player's side: [angle around the board, distance, height]. */
  _home() {
    return { angle: this.orientation === "white" ? 0 : Math.PI, dist: 9.4, height: 12.0 };
  }

  _placeCamera(angle, dist, height) {
    this.camera.position.set(Math.sin(angle) * dist, height, Math.cos(angle) * dist);
    const side = Math.cos(angle) >= 0 ? 1 : -1;
    this.controls.target.set(0, 0, 0.35 * side * Math.abs(Math.cos(angle)));
    this.camera.lookAt(this.controls.target);
  }

  _resetCamera() {
    const h = this._home();
    this._placeCamera(h.angle, h.dist, h.height);
    this.controls.update();
    // labels read correctly from the player's side
    for (const m of this.labels) m.rotation.z = this.orientation === "white" ? 0 : Math.PI;
  }

  _resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // narrow (portrait) screens: widen the view so the whole board fits
    this.camera.fov = w / h < 0.9 ? 44 : 36;
    this.camera.updateProjectionMatrix();
  }

  _tick(now) {
    this.tweens = this.tweens.filter((tw) => {
      const t = clamp01((now - tw.start) / tw.ms);
      tw.step(t);
      if (t >= 1) { tw.done?.(); return false; }
      return true;
    });
    this._animateIdle(now);
    if (this.intro) this._introFrame(now);
    else this.controls.update();
    if (this.checkSquare !== null) { // the checked king's square pulses
      const tile = this.tiles[this.checkSquare];
      const k = 0.55 + 0.35 * Math.sin(now / 180);
      tile.material.color.copy(tile.userData.base).lerp(MARK.check, k);
    }
    this.renderer.render(this.scene, this.camera);
  }

  _tween(ms, step, done) {
    this.tweens.push({ start: performance.now(), ms, step, done });
  }

  // ------------------------------------------------------------ intro (360° camera spin)

  /**
   * Fly once around the board before the game starts. With ``drop`` the pieces also
   * fall into place one rank after another. Clicking skips it.
   */
  playIntro({ drop = false } = {}) {
    const h = this._home();
    this.intro = { start: performance.now(), drop, home: h, pieces: [...this.meshes] };
    this.controls.enabled = false;
    if (drop) for (const [, obj] of this.meshes) obj.visible = false;
  }

  _introFrame(now) {
    const it = this.intro;
    const p = clamp01((now - it.start) / INTRO_MS);
    const e = easeInOut(p);
    const angle = it.home.angle - (1 - e) * Math.PI * 2;
    const dist = 17 + (it.home.dist - 17) * e;
    const height = 7 + (it.home.height - 7) * easeOut(p);
    this._placeCamera(angle, dist, height);
    if (it.drop) {
      for (const [sq, obj] of it.pieces) {
        const rank = Math.floor(sq / 8);
        const order = rank <= 3 ? rank : 7 - rank; // back ranks first, pawns last
        const local = clamp01((p - 0.25 - order * 0.1) / 0.22);
        obj.visible = local > 0;
        obj.position.y = 2.5 * (1 - easeOut(local)) ** 2;
      }
    }
    if (p >= 1) this._endIntro();
  }

  _endIntro() {
    if (!this.intro) return;
    if (this.intro.drop) for (const [, obj] of this.intro.pieces) { obj.visible = true; obj.position.y = 0; }
    this.intro = null;
    this._resetCamera();
    this.controls.enabled = true;
  }

  // ------------------------------------------------------------ pieces

  /** One piece model (the Battle view replaces this with soldiers). */
  _createPiece(type, color) {
    return buildPiece(type, color);
  }

  /** Per-frame animation of the pieces standing still (none for wooden pieces). */
  _animateIdle() {}

  _addPiece(letter, sq) {
    const obj = this._createPiece(letter.toLowerCase(), colorOf(letter));
    obj.position.set(sqX(sq), 0, sqZ(sq));
    obj.userData.letter = letter;
    this.scene.add(obj);
    this.meshes.set(sq, obj);
    return obj;
  }

  _removePiece(sq, animated) {
    const obj = this.meshes.get(sq);
    if (!obj) return;
    this.meshes.delete(sq);
    if (!animated) { this.scene.remove(obj); return; }
    // the captured piece tips over and sinks into the board
    const dir = Math.random() < 0.5 ? 1 : -1;
    this._tween(520, (t) => {
      const e = easeInOut(t);
      obj.rotation.z = dir * e * 1.3;
      obj.position.y = -0.9 * Math.max(0, t - 0.4) / 0.6;
      obj.scale.setScalar(1 - 0.4 * Math.max(0, t - 0.5) / 0.5);
    }, () => this.scene.remove(obj));
  }

  _slide(obj, to, ms = MOVE_MS, hop = 0.3) {
    const x0 = obj.position.x, z0 = obj.position.z, x1 = sqX(to), z1 = sqZ(to);
    const y0 = obj.position.y;
    this._tween(ms, (t) => {
      const e = easeInOut(t);
      obj.position.x = x0 + (x1 - x0) * e;
      obj.position.z = z0 + (z1 - z0) * e;
      obj.position.y = y0 * (1 - e) + Math.sin(Math.PI * t) * hop;
    });
  }

  _replaceLetter(sq, letter) {
    this._removePiece(sq, false);
    return this._addPiece(letter, sq);
  }

  /** Move pieces for ``uci`` (handles captures, castling, en passant, promotion). */
  _animateMove(uci, { instant = false } = {}) {
    const from = parseSquare(uci.slice(0, 2)), to = parseSquare(uci.slice(2, 4));
    const obj = this.meshes.get(from);
    if (!obj) return;
    const letter = obj.userData.letter;
    const delay = instant ? 0 : MOVE_MS * 0.55; // the victim falls as the attacker arrives
    const victimSq = this.meshes.has(to) ? to
      : letter.toLowerCase() === "p" && from % 8 !== to % 8 && !this.position.has(to)
        ? (letter === "P" ? to - 8 : to + 8) : null;
    if (victimSq !== null) {
      const victim = this.meshes.get(victimSq);
      this.meshes.delete(victimSq);
      const tmp = -1 - victimSq; // park it under a key no square uses until it falls
      this.meshes.set(tmp, victim);
      setTimeout(() => this._removePiece(tmp, true), delay);
    }
    if (letter.toLowerCase() === "k" && Math.abs((from % 8) - (to % 8)) === 2) {
      const rookFrom = to > from ? from + 3 : from - 4, rookTo = to > from ? from + 1 : from - 1;
      const rook = this.meshes.get(rookFrom);
      if (rook) {
        this.meshes.delete(rookFrom);
        this.meshes.set(rookTo, rook);
        this._slide(rook, rookTo, MOVE_MS, 0.6);
      }
    }
    this.meshes.delete(from);
    this.meshes.set(to, obj);
    if (instant) { obj.position.set(sqX(to), 0, sqZ(to)); }
    else this._slide(obj, to, MOVE_MS, letter.toLowerCase() === "n" ? 1.0 : 0.3);
    let after = letter;
    if (uci.length === 5) { // promotion: the pawn becomes the new piece with a little pop
      after = letter === "P" ? uci[4].toUpperCase() : uci[4];
      setTimeout(() => {
        if (this.meshes.get(to) !== obj) return;
        const np = this._replaceLetter(to, after);
        this._tween(380, (t) => np.scale.setScalar(0.6 + 0.4 * easeOut(t) + 0.15 * Math.sin(Math.PI * t)));
      }, instant ? 0 : MOVE_MS);
    }
    this.position.delete(from);
    if (victimSq !== null) this.position.delete(victimSq);
    this.position.set(to, after);
  }

  /** Pieces each side has lost, shown small beside the board. */
  _updateTrays(target) {
    const count = { white: {}, black: {} };
    for (const letter of target.values()) {
      const c = colorOf(letter), t = letter.toLowerCase();
      count[c][t] = (count[c][t] || 0) + 1;
    }
    const lost = { white: [], black: [] };
    for (const c of ["white", "black"]) {
      for (const t of TRAY_ORDER) {
        const n = Math.max(0, START_COUNT[t] - (count[c][t] || 0));
        for (let i = 0; i < n; i++) lost[c].push(t);
      }
    }
    const sig = lost.white.join("") + "|" + lost.black.join("");
    if (sig === this.traySignature) return;
    this.traySignature = sig;
    this.trays.clear();
    // Black's lost pieces on White's right, White's lost pieces on Black's right
    for (const [c, x, dirZ] of [["black", 5.55, 1], ["white", -5.55, -1]]) {
      lost[c].forEach((t, i) => {
        const p = this._createPiece(t, c);
        const col = Math.floor(i / 8), row = i % 8;
        p.scale.setScalar(0.62);
        p.position.set(x + (x > 0 ? 1 : -1) * col * 0.55, this.trayY, dirZ * (3.6 - row * 0.62));
        this.trays.add(p);
      });
    }
  }

  // ------------------------------------------------------------ interface

  setOrientation(color) {
    if (color === this.orientation) return;
    this.orientation = color;
    this._endIntro();
    this._resetCamera();
  }

  setPosition(fen, { animate = null, lastMove = null, check = false } = {}) {
    this._closePromo();
    this._dragCancel();
    if (animate) this._animateMove(animate);
    const target = parseFen(fen);
    for (const [sq, obj] of [...this.meshes]) {
      if (sq < 0) continue; // a captured piece still falling
      const want = target.get(sq);
      if (!want) this._removePiece(sq, !!animate);
      else if (obj.userData.letter !== want && !animate) this._replaceLetter(sq, want);
    }
    for (const [sq, letter] of target) if (!this.meshes.has(sq)) this._addPiece(letter, sq);
    this.position = target;
    this.lastMove = lastMove ? [parseSquare(lastMove.slice(0, 2)), parseSquare(lastMove.slice(2, 4))] : null;
    const turnWhite = fen.split(" ")[1] === "w";
    this.checkSquare = null;
    if (check) for (const [sq, l] of target) if (l === (turnWhite ? "K" : "k")) this.checkSquare = sq;
    setTimeout(() => this._updateTrays(target), animate ? MOVE_MS + 300 : 0);
    this._select(null);
  }

  setInteractive(color, legal) {
    this.interactive = color ? { color, legal: legal || {} } : null;
    if (!this.interactive) { this._dragCancel(); this._select(null); } else this._paint();
  }

  // ------------------------------------------------------------ highlights

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
      const c = tile.userData.base.clone();
      if (this.lastMove && this.lastMove.includes(sq)) c.lerp(MARK.last, 0.45);
      if (sq === this.selected) c.lerp(MARK.selected, 0.55);
      if (sq === this.dropSquare) c.lerp(MARK.drop, 0.6);
      tile.material.color.copy(c);
    });
    this.dots.forEach(({ dot, ring }, sq) => {
      const on = targets.includes(sq);
      const capture = on && this.position.has(sq);
      dot.visible = on && !capture;
      ring.visible = capture;
    });
  }

  // ------------------------------------------------------------ input

  _ray(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                                  -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
  }

  /** Square under the pointer (a piece counts as its square), or null. */
  _squareAt(e) {
    this._ray(e);
    const pieces = [...this.meshes].filter(([sq]) => sq >= 0);
    const objs = pieces.map(([, o]) => o);
    const hit = this.raycaster.intersectObjects([...objs, ...this.tiles], true)[0];
    if (!hit) return null;
    let o = hit.object;
    while (o && o.userData.sq === undefined && !objs.includes(o)) o = o.parent;
    if (!o) return null;
    if (o.userData.sq !== undefined) return o.userData.sq;
    return pieces.find(([, obj]) => obj === o)?.[0] ?? null;
  }

  /** Square whose area the pointer is over, measured on the board plane. */
  _boardSquareAt(e) {
    this._ray(e);
    const p = new THREE.Vector3();
    if (!this.raycaster.ray.intersectPlane(this.groundPlane, p)) return { sq: null, p: null };
    const file = Math.floor(p.x + 4), rank = Math.floor(4 - p.z);
    const sq = file >= 0 && file < 8 && rank >= 0 && rank < 8 ? rank * 8 + file : null;
    return { sq, p };
  }

  _pointerDown(e) {
    if (e.button !== 0 || this.promo) return;
    if (this.intro) { e.stopPropagation(); this._endIntro(); return; } // click skips the intro
    const sq = this._squareAt(e);
    if (sq === null) return; // empty space: let the camera rotate
    if (this.selected !== null && this._targets(this.selected).includes(sq)) {
      e.stopPropagation();
      this._tryMove(this.selected, sq, false);
      return;
    }
    if (this._canMoveFrom(sq)) {
      e.stopPropagation(); // picking up a piece, not rotating the camera
      const wasSelected = this.selected === sq;
      this._select(sq);
      this.drag = { from: sq, obj: this.meshes.get(sq), x: e.clientX, y: e.clientY,
                    moved: false, wasSelected };
    } else if (this.selected !== null) {
      this._select(null);
    }
  }

  _dragMove(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) return;
    d.moved = true;
    const { sq, p } = this._boardSquareAt(e);
    if (p) d.obj.position.set(Math.max(-4.6, Math.min(4.6, p.x)), 0.45, Math.max(-4.6, Math.min(4.6, p.z)));
    const drop = sq !== null && this._targets(d.from).includes(sq) ? sq : null;
    if (drop !== this.dropSquare) { this.dropSquare = drop; this._paint(); }
    this.el.style.cursor = "grabbing";
  }

  _dragEnd(e) {
    const d = this.drag;
    if (!d) return;
    this.drag = null;
    this.dropSquare = null;
    this.el.style.cursor = "";
    if (!d.moved) { // a click: toggle the selection
      if (d.wasSelected) this._select(null);
      return;
    }
    const { sq } = this._boardSquareAt(e);
    if (sq !== null && this._targets(d.from).includes(sq)) {
      this._tryMove(d.from, sq, true);
    } else {
      this._slide(d.obj, d.from, 200, 0); // snap back
      this._paint();
    }
  }

  _dragCancel() {
    const d = this.drag;
    if (!d) return;
    this.drag = null;
    this.dropSquare = null;
    d.obj.position.set(sqX(d.from), 0, sqZ(d.from));
    this.el.style.cursor = "";
  }

  _hover(e) {
    if (this.drag || this.intro || this._hoverPending) return;
    this._hoverPending = true;
    requestAnimationFrame(() => {
      this._hoverPending = false;
      if (!this.running || this.drag) return;
      const sq = this._squareAt(e);
      const usable = sq !== null && (this._canMoveFrom(sq) ||
        (this.selected !== null && this._targets(this.selected).includes(sq)));
      this.el.style.cursor = usable ? "pointer" : "";
    });
  }

  _tryMove(from, to, dropped) {
    const letter = this.position.get(from);
    const rank = Math.floor(to / 8);
    if (letter && letter.toLowerCase() === "p" && (rank === 7 || rank === 0)) {
      if (dropped) this.meshes.get(from).position.set(sqX(to), 0, sqZ(to));
      this._showPromo(from, to, colorOf(letter), dropped);
      return;
    }
    this._commit(squareName(from) + squareName(to), dropped);
  }

  _commit(uci, instant) {
    this._animateMove(uci, { instant });
    this.lastMove = [parseSquare(uci.slice(0, 2)), parseSquare(uci.slice(2, 4))];
    this.checkSquare = null;
    this.setInteractive(null);
    this.onMove(uci);
  }

  _showPromo(from, to, color, dropped) {
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
        this._commit(squareName(from) + squareName(to) + p, dropped);
      });
      box.append(b);
    }
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "piece-btn promo-cancel";
    cancel.textContent = "✕";
    cancel.setAttribute("aria-label", "Cancel");
    cancel.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      this._closePromo();
      const obj = this.meshes.get(from);
      if (obj) obj.position.set(sqX(from), 0, sqZ(from));
      this._select(null);
    });
    box.append(cancel);
    this.el.append(box);
    this.promo = box;
  }

  _closePromo() {
    if (this.promo) { this.promo.remove(); this.promo = null; }
  }
}
