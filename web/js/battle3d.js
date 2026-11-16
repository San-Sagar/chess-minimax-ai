// Battle view: the 3D board turned into a battlefield at dusk, with the pieces as
// soldiers (units3d.js). It reuses all of Board3D's game logic (moves, input, intro)
// and only replaces the scenery, the piece models and the idle animation.

import * as THREE from "three";
import { Board3D } from "./board3d.js";
import { parseSquare } from "./board.js";
import { ARMIES, buildUnit, glowSprite } from "./units3d.js";
import { noiseTexture, skyTexture } from "./textures3d.js";
import * as sound from "./sound.js";

const GROUND_Y = -0.42;
const sqX = (sq) => (sq % 8) - 3.5;
const sqZ = (sq) => 3.5 - Math.floor(sq / 8);
const colorOf = (letter) => (letter === letter.toUpperCase() ? "white" : "black");
const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const easeOut = (t) => 1 - (1 - t) ** 3;
const easeIn = (t) => t * t * t;
const clamp01 = (t) => Math.min(1, Math.max(0, t));
const lerp = (a, b, t) => a + (b - a) * t;
const SPEEDS = { normal: 1, fast: 2.2, skip: 0 };
const SPEED_KEY = "battleSpeed";

/** Deterministic random numbers, so the scenery is the same on every visit. */
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

export class BattleBoard extends Board3D {
  constructor(el, options) {
    super(el, options);
    this.trayY = GROUND_Y;
    this.queue = Promise.resolve(); // moves play one after another, never on top of each other
    this.effects = new THREE.Group();
    this.scene.add(this.effects);
    this.speed = "normal";
    try { this.speed = localStorage.getItem(SPEED_KEY) || "normal"; } catch { /* storage blocked */ }
    if (!(this.speed in SPEEDS)) this.speed = "normal";
    this._buildSpeedControl();
  }

  // ------------------------------------------------------------ speed control (1x / 2x / Skip)

  _buildSpeedControl() {
    const box = document.createElement("div");
    box.className = "battle-speed";
    box.setAttribute("role", "group");
    box.setAttribute("aria-label", "Battle animation speed");
    for (const [key, label, title] of [["normal", "1×", "Full battle animations"],
                                       ["fast", "2×", "Faster animations"],
                                       ["skip", "Skip", "Pieces just move, no fights"]]) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.title = title;
      b.dataset.speed = key;
      b.setAttribute("aria-pressed", String(key === this.speed));
      b.addEventListener("click", () => {
        this.speed = key;
        try { localStorage.setItem(SPEED_KEY, key); } catch { /* storage blocked */ }
        for (const x of box.children) x.setAttribute("aria-pressed", String(x.dataset.speed === key));
      });
      box.append(b);
    }
    this.el.append(box);
  }

  _pointerDown(e) {
    if (e.target.closest?.(".battle-speed")) return; // the speed buttons are not the board
    super._pointerDown(e);
  }

  // ------------------------------------------------------------ queue: the game talks to us here

  _enqueue(fn) {
    this.queue = this.queue.then(() => (this.running ? fn() : null)).catch((err) => console.error(err));
    return this.queue;
  }

  setPosition(fen, opts = {}) {
    const { animate = null } = opts;
    this._enqueue(async () => {
      if (animate && this.meshes.has(parseSquare(animate.slice(0, 2)))) await this._battle(animate);
      Board3D.prototype.setPosition.call(this, fen, { ...opts, animate: null });
      this._standOrKneel(fen, !!opts.mated);
    });
  }

  setInteractive(color, legal) {
    if (!color) Board3D.prototype.setInteractive.call(this, null); // block input at once
    this._enqueue(() => Board3D.prototype.setInteractive.call(this, color, legal));
  }

  _commit(uci) { // the human made a move: fight it out, and tell the game straight away
    this.interactive = null;
    this._select(null);
    this.lastMove = [parseSquare(uci.slice(0, 2)), parseSquare(uci.slice(2, 4))];
    this.checkSquare = null;
    this._enqueue(() => this._battle(uci));
    this.onMove(uci);
  }

  // ------------------------------------------------------------ timing helpers

  /** Run ``step(t)`` for t = 0..1 over ``ms`` (scaled by the speed setting). */
  _anim(ms, step) {
    const factor = SPEEDS[this.speed] || 1;
    return new Promise((resolve) => this._tween(ms / factor, step, resolve));
  }

  _wait(ms) { return this._anim(ms, () => {}); }

  _sfx(kind) { sound.play(kind); }

  // ------------------------------------------------------------ poses

  _savePose(unit) {
    const pose = [];
    const rig = unit.userData.rig;
    const joints = Object.values(rig).flatMap((v) => (Array.isArray(v) ? v : [v]))
      .filter((o) => o && o.isObject3D);
    for (const j of joints) pose.push([j, j.position.clone(), j.rotation.clone(), j.scale.clone()]);
    unit.userData.pose = pose;
  }

  _restorePose(unit) {
    for (const [j, p, r, s] of unit.userData.pose || []) {
      j.position.copy(p); j.rotation.copy(r); j.scale.copy(s);
    }
  }

  /** World angle that makes ``unit`` look towards (x, z). */
  _faceAngle(unit, x, z) {
    const inner = unit.userData.color === "white" ? Math.PI : 0;
    let a = Math.atan2(x - unit.position.x, z - unit.position.z) - inner;
    while (a > Math.PI) a -= 2 * Math.PI;
    while (a < -Math.PI) a += 2 * Math.PI;
    return a;
  }

  _turn(unit, angle, ms = 220) {
    const a0 = unit.rotation.y;
    let d = angle - a0;
    while (d > Math.PI) d -= 2 * Math.PI;
    while (d < -Math.PI) d += 2 * Math.PI;
    if (Math.abs(d) < 0.01) return Promise.resolve();
    return this._anim(ms, (t) => { unit.rotation.y = a0 + d * easeInOut(t); });
  }

  /** One frame of the walking / galloping cycle; ``ph`` grows with distance travelled. */
  _gait(unit, ph, amount = 1) {
    const r = unit.userData.rig, type = unit.userData.type;
    if (type === "n") {
      r.hooves.forEach((leg, i) => { leg.rotation.x = Math.sin(ph + [0, Math.PI, 1.2, Math.PI + 1.2][i]) * 0.75 * amount; });
      r.horseBody.rotation.x = Math.sin(ph * 2) * 0.06 * amount;
      r.horseBody.position.y = 0.5 + Math.abs(Math.sin(ph)) * 0.05 * amount;
    } else if (type === "r") {
      r.legs.forEach((leg, i) => { leg.rotation.x = Math.sin(ph + (i % 2 ? Math.PI : 0) + (i > 1 ? Math.PI / 2 : 0)) * 0.35 * amount; });
      r.ebody.rotation.z = Math.sin(ph) * 0.05 * amount;
    } else if (r.legL) { // spearman, king: legs swing
      r.legL.rotation.x = Math.sin(ph) * 0.65 * amount;
      r.legR.rotation.x = -Math.sin(ph) * 0.65 * amount;
      r.hips.position.y = r.hips.userData.y0 + Math.abs(Math.sin(ph)) * 0.025 * amount;
    } else { // robes: glide with a gentle sway
      r.body.rotation.z = Math.sin(ph) * 0.06 * amount;
      r.hips.position.y = r.hips.userData.y0 + Math.abs(Math.sin(ph)) * 0.015 * amount;
    }
  }

  /** Walk / gallop / glide ``unit`` to (x, z). */
  async _travel(unit, x, z, { run = false, hop = 0 } = {}) {
    const x0 = unit.position.x, z0 = unit.position.z;
    const dist = Math.hypot(x - x0, z - z0);
    if (dist < 0.01) return;
    const type = unit.userData.type;
    const per = type === "n" ? 160 : type === "r" ? (run ? 170 : 300) : run ? 150 : 260;
    const ms = 250 + dist * per;
    const r = unit.userData.rig;
    r.hips && (r.hips.userData.y0 ??= r.hips.position.y);
    const steps = dist * (type === "n" ? 2.4 : 3.2);
    let lastStep = -1;
    await this._anim(ms, (t) => {
      const e = easeInOut(t);
      unit.position.x = lerp(x0, x, e);
      unit.position.z = lerp(z0, z, e);
      unit.position.y = hop ? Math.sin(Math.PI * t) * hop : 0;
      const ph = e * steps * Math.PI;
      this._gait(unit, ph, Math.min(1, Math.sin(Math.PI * t) * 3));
      const step = Math.floor(ph / Math.PI);
      if (step !== lastStep) { lastStep = step; if (step % 2 === 0) this._sfx(type === "n" ? "gallop" : "step"); }
    });
    unit.position.y = 0;
  }

  // ------------------------------------------------------------ effects

  _worldOf(obj, offset = new THREE.Vector3()) {
    obj.updateWorldMatrix(true, false);
    return offset.applyMatrix4(obj.matrixWorld);
  }

  _flash(pos, color, size = 1.2, ms = 350) {
    const s = glowSprite(color, 0.1, 1);
    s.position.copy(pos);
    this.effects.add(s);
    return this._anim(ms, (t) => {
      s.scale.setScalar(0.1 + size * easeOut(t));
      s.material.opacity = 1 - t;
    }).then(() => { this.effects.remove(s); s.material.dispose(); });
  }

  _sparks(pos, color, n = 10) {
    const parts = [];
    for (let i = 0; i < n; i++) {
      const s = glowSprite(color, 0.09, 1);
      s.position.copy(pos);
      const v = new THREE.Vector3((Math.random() - 0.5) * 2.4, 1 + Math.random() * 1.6, (Math.random() - 0.5) * 2.4);
      this.effects.add(s);
      parts.push([s, v]);
    }
    return this._anim(500, (t) => {
      for (const [s, v] of parts) {
        s.position.set(pos.x + v.x * t * 0.5, pos.y + v.y * t * 0.5 - 2.2 * t * t * 0.5, pos.z + v.z * t * 0.5);
        s.material.opacity = 1 - t;
      }
    }).then(() => parts.forEach(([s]) => { this.effects.remove(s); s.material.dispose(); }));
  }

  _arrowMesh(color) {
    const g = new THREE.Group();
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.4, 5),
      new THREE.MeshStandardMaterial({ color: "#7a5a36" }));
    shaft.rotation.x = Math.PI / 2;
    const tip = new THREE.Mesh(new THREE.ConeGeometry(0.02, 0.07, 5),
      new THREE.MeshStandardMaterial({ color: "#ddd", metalness: 0.8, roughness: 0.3 }));
    tip.rotation.x = Math.PI / 2;
    tip.position.z = 0.22;
    g.add(shaft, tip);
    if (color) { const gl = glowSprite(color, 0.25); gl.position.z = 0.2; g.add(gl); }
    return g;
  }

  /** Fly ``obj`` from a to b along an arc, pointing where it goes. */
  _fly(obj, a, b, ms, arc = 0.6) {
    this.effects.add(obj);
    const at = (t) => new THREE.Vector3(lerp(a.x, b.x, t), lerp(a.y, b.y, t) + Math.sin(Math.PI * t) * arc, lerp(a.z, b.z, t));
    obj.position.copy(a);
    return this._anim(ms, (t) => {
      obj.position.copy(at(t));
      obj.lookAt(at(Math.min(1, t + 0.02)));
    }).then(() => this.effects.remove(obj));
  }

  /** Jagged bolt of light between two points, re-drawn a few times so it flickers. */
  async _lightning(a, b, color) {
    const mat = new THREE.MeshBasicMaterial({ color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
    const bolt = new THREE.Group();
    this.effects.add(bolt);
    const draw = () => {
      bolt.clear();
      const pts = [a.clone()];
      for (let i = 1; i < 8; i++) {
        const p = a.clone().lerp(b, i / 8);
        p.x += (Math.random() - 0.5) * 0.35; p.y += (Math.random() - 0.5) * 0.35; p.z += (Math.random() - 0.5) * 0.35;
        pts.push(p);
      }
      pts.push(b.clone());
      for (let i = 0; i < pts.length - 1; i++) {
        const len = pts[i].distanceTo(pts[i + 1]);
        const seg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, len, 4), mat);
        seg.position.copy(pts[i]).lerp(pts[i + 1], 0.5);
        seg.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), pts[i + 1].clone().sub(pts[i]).normalize());
        bolt.add(seg);
        if (i % 2 === 0) { const gl = glowSprite(color, 0.45, 0.7); gl.position.copy(pts[i]); bolt.add(gl); }
      }
    };
    for (let k = 0; k < 4; k++) {
      draw();
      mat.opacity = 1;
      await this._anim(90, (t) => { mat.opacity = 1 - t * 0.6; });
    }
    bolt.traverse((o) => o.geometry?.dispose());
    this.effects.remove(bolt);
    mat.dispose();
  }

  _shockwave(pos, color) {
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.75, 1, 48), new THREE.MeshBasicMaterial({
      color, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(pos.x, 0.08, pos.z);
    this.effects.add(ring);
    return this._anim(520, (t) => {
      ring.scale.setScalar(0.1 + 1.2 * easeOut(t));
      ring.material.opacity = 1 - t;
    }).then(() => { this.effects.remove(ring); ring.geometry.dispose(); ring.material.dispose(); });
  }

  // ------------------------------------------------------------ dying

  /** The defender falls back, sinks into the ground and disappears. */
  _die(victimSq, from) {
    const v = this.meshes.get(victimSq);
    if (!v) return Promise.resolve();
    this.meshes.delete(victimSq);
    v.userData.busy = true;
    const dir = new THREE.Vector3(v.position.x - from.x, 0, v.position.z - from.z).normalize();
    const axis = new THREE.Vector3(dir.z, 0, -dir.x); // fall away from the attacker
    const q0 = v.quaternion.clone();
    const p0 = v.position.clone();
    this._sfx("fall");
    return this._anim(750, (t) => {
      const fall = easeIn(clamp01(t / 0.55));
      v.quaternion.copy(q0).premultiply(new THREE.Quaternion().setFromAxisAngle(axis, fall * 1.45));
      v.position.set(p0.x + dir.x * fall * 0.25, -0.55 * clamp01((t - 0.55) / 0.45), p0.z + dir.z * fall * 0.25);
      if (t > 0.55) v.scale.setScalar(1 - 0.5 * (t - 0.55) / 0.45);
    }).then(() => this.scene.remove(v));
  }

  // ------------------------------------------------------------ the six attacks

  /**
   * ``unit`` on ``from`` attacks the piece on ``victimSq`` and ends on ``to``.
   * Each attack: face the enemy, strike (melee, arrow, javelin, lightning, shockwave),
   * the enemy falls, then the attacker takes the square.
   */
  async _attack(unit, from, to, victimSq) {
    const type = unit.userData.type, a = ARMIES[unit.userData.color], r = unit.userData.rig;
    const vx = sqX(victimSq), vz = sqZ(victimSq);
    const target = new THREE.Vector3(vx, 0.55, vz);
    const here = new THREE.Vector3(unit.position.x, 0, unit.position.z);
    await this._turn(unit, this._faceAngle(unit, vx, vz));

    if (type === "p") { // spearman: close in, thrust, step onto the square
      const d = Math.hypot(vx - here.x, vz - here.z);
      const stop = Math.max(0, d - 0.6);
      await this._travel(unit, lerp(here.x, vx, stop / d), lerp(here.z, vz, stop / d));
      const s0 = r.spear.rotation.x, a0 = r.armR.rotation.x, f0 = r.foreR.rotation.x;
      await this._anim(260, (t) => { // pull back
        r.armR.rotation.x = lerp(a0, 0.3, easeOut(t));
        r.body.rotation.x = lerp(0, -0.12, t);
      });
      await this._anim(140, (t) => { // thrust: arm straight out, spear tip pointing forward
        r.armR.rotation.x = lerp(0.3, -1.45, easeIn(t));
        r.foreR.rotation.x = lerp(f0, -0.1, t);
        r.spear.rotation.x = lerp(s0, 3.05, t);
        r.body.rotation.x = lerp(-0.12, 0.25, t);
      });
      this._sfx("stab");
      this._sparks(target, "#ffd27a", 12);
      const dying = this._die(victimSq, unit.position);
      await this._anim(260, (t) => {
        r.armR.rotation.x = lerp(-1.45, a0, easeInOut(t));
        r.foreR.rotation.x = lerp(-0.1, f0, t);
        r.spear.rotation.x = lerp(3.05, s0, t);
        r.body.rotation.x = lerp(0.25, 0, t);
      });
      await dying;
      await this._travel(unit, sqX(to), sqZ(to));
      return;
    }

    if (type === "n" || type === "r") { // archers: loose an arrow first
      const archer = type === "n" ? r : r.towerArcher;
      const arm0 = archer.armR.rotation.x;
      await this._anim(300, (t) => { archer.armR.rotation.x = lerp(arm0, -1.6, easeOut(t)); }); // draw
      const start = this._worldOf(type === "n" ? r.bow : r.towerBow);
      this._sfx("arrow");
      await this._fly(this._arrowMesh(null), start, target, 380, 0.35);
      this._sfx("hit");
      this._sparks(target, "#ffffff", 6);
      const dying = this._die(victimSq, unit.position);
      this._anim(250, (t) => { archer.armR.rotation.x = lerp(-1.6, arm0, t); });
      if (type === "r") { // the elephant raises its trunk and charges
        this._sfx("charge");
        const t0 = r.trunk[0].rotation.x;
        await this._anim(350, (t) => { r.trunk[0].rotation.x = lerp(t0, -1.1, easeOut(t)); });
        await dying;
        await this._travel(unit, sqX(to), sqZ(to), { run: true });
        await this._anim(300, (t) => { r.trunk[0].rotation.x = lerp(-1.1, t0, t); });
      } else {
        await dying;
        await this._travel(unit, sqX(to), sqZ(to), { hop: 0.35 });
      }
      return;
    }

    if (type === "b") { // javelin priest: wind up, throw a glowing javelin
      const a0 = r.armR.rotation.x;
      await this._anim(320, (t) => { r.armR.rotation.x = lerp(a0, -2.6, easeOut(t)); r.body.rotation.x = lerp(0, -0.15, t); });
      const start = this._worldOf(r.javelin, new THREE.Vector3(0, 0.4, 0));
      r.javelin.visible = false;
      this._anim(160, (t) => { r.armR.rotation.x = lerp(-2.6, -0.6, t); r.body.rotation.x = lerp(-0.15, 0.2, t); });
      this._sfx("javelin");
      const jav = this._arrowMesh(a.magic);
      jav.scale.set(1.6, 1.6, 2.2);
      await this._fly(jav, start, target, 420, 0.5);
      this._sfx("hit");
      this._flash(target, a.magic, 1.4);
      this._sparks(target, a.magic, 10);
      await this._die(victimSq, unit.position);
      r.javelin.visible = true;
      this._anim(250, (t) => { r.armR.rotation.x = lerp(-0.6, a0, t); r.body.rotation.x = lerp(0.2, 0, t); });
      await this._travel(unit, sqX(to), sqZ(to));
      return;
    }

    if (type === "q") { // sorceress: raise the staff, call lightning
      const a0 = r.armR.rotation.x, f0 = r.foreR.rotation.x, st0 = r.staff.rotation.x;
      await this._anim(380, (t) => { // arm up, staff turned so the orb is held high
        r.armR.rotation.x = lerp(a0, -2.3, easeOut(t));
        r.foreR.rotation.x = lerp(f0, -0.2, t);
        r.staff.rotation.x = lerp(st0, 2.8, easeOut(t));
        r.orbGlow.scale.setScalar(0.5 + t * 0.6);
      });
      const orb = this._worldOf(r.orb);
      this._sfx("zap");
      this._flash(orb, a.magic, 1.2, 500);
      await this._lightning(orb, target, a.magic);
      this._flash(target, a.magic, 1.8, 450);
      this._sparks(target, a.magic, 14);
      const dying = this._die(victimSq, unit.position);
      await this._anim(300, (t) => {
        r.armR.rotation.x = lerp(-2.3, a0, t);
        r.foreR.rotation.x = lerp(-0.2, f0, t);
        r.staff.rotation.x = lerp(2.8, st0, t);
        r.orbGlow.scale.setScalar(1.1 - t * 0.6);
      });
      await dying;
      await this._travel(unit, sqX(to), sqZ(to)); // she glides
      return;
    }

    // king (warlord-mage): raise the open hand, release a shockwave and fire
    const a0 = r.armL.rotation.x;
    await this._anim(380, (t) => {
      r.armL.rotation.x = lerp(a0, -2.4, easeOut(t));
      r.handGlow.scale.setScalar(0.22 + t * 0.5);
    });
    this._sfx("boom");
    this._shockwave(here, a.magic);
    this._shockwave(target, a.magic);
    this._flash(target, "#ff9a3c", 2.0, 500);
    this._sparks(target, "#ffb347", 16);
    const dying = this._die(victimSq, unit.position);
    await this._anim(320, (t) => {
      r.armL.rotation.x = lerp(-2.4, a0, t);
      r.handGlow.scale.setScalar(0.72 - t * 0.5);
    });
    await dying;
    await this._travel(unit, sqX(to), sqZ(to));
  }

  // ------------------------------------------------------------ one move, start to finish

  async _battle(uci) {
    const from = parseSquare(uci.slice(0, 2)), to = parseSquare(uci.slice(2, 4));
    while (this.march && this.running) await this._wait(100); // let the armies arrive first
    const unit = this.meshes.get(from);
    if (!unit) return;
    const letter = unit.userData.letter, type = letter.toLowerCase();
    unit.position.set(sqX(from), 0, sqZ(from)); // a dragged unit goes back to start first
    unit.rotation.y = 0;

    if (this.speed === "skip") { // pieces just move, like the 3D board
      Board3D.prototype._animateMove.call(this, uci);
      await this._wait(450);
      return;
    }

    const victimSq = this.position.has(to) ? to
      : type === "p" && from % 8 !== to % 8 ? (letter === "P" ? to - 8 : to + 8) : null;
    const castle = type === "k" && Math.abs((from % 8) - (to % 8)) === 2;
    unit.userData.busy = true;
    this._savePose(unit);

    if (castle) { // king and rook march together
      const rookFrom = to > from ? from + 3 : from - 4, rookTo = to > from ? from + 1 : from - 1;
      const rook = this.meshes.get(rookFrom);
      const moves = [this._turn(unit, this._faceAngle(unit, sqX(to), sqZ(to))).then(() => this._travel(unit, sqX(to), sqZ(to)))];
      if (rook) {
        rook.userData.busy = true;
        this._savePose(rook);
        moves.push(this._turn(rook, this._faceAngle(rook, sqX(rookTo), sqZ(rookTo)))
          .then(() => this._travel(rook, sqX(rookTo), sqZ(rookTo))));
        this.meshes.delete(rookFrom);
        this.meshes.set(rookTo, rook);
        this.position.set(rookTo, this.position.get(rookFrom));
        this.position.delete(rookFrom);
      }
      await Promise.all(moves);
      if (rook) { await this._turn(rook, 0); this._restorePose(rook); rook.userData.busy = false; }
    } else if (victimSq !== null && this.meshes.has(victimSq)) {
      await this._attack(unit, from, to, victimSq);
    } else {
      await this._turn(unit, this._faceAngle(unit, sqX(to), sqZ(to)));
      await this._travel(unit, sqX(to), sqZ(to), { hop: type === "n" ? 0.35 : 0 });
    }

    this.meshes.delete(from);
    this.meshes.set(to, unit);
    this.position.delete(from);
    if (victimSq !== null) this.position.delete(victimSq);
    let after = letter;
    if (uci.length === 5) after = letter === "P" ? uci[4].toUpperCase() : uci[4];
    this.position.set(to, after);

    await this._turn(unit, 0);
    this._restorePose(unit);
    unit.userData.busy = false;
    if (after !== letter) await this._promote(to, after);
  }

  /** A pillar of light, and the spearman becomes the new piece. */
  async _promote(sq, letter) {
    const color = colorOf(letter), a = ARMIES[color];
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.45, 3, 24, 1, true),
      new THREE.MeshBasicMaterial({ color: "#fff2b0", transparent: true, opacity: 0, side: THREE.DoubleSide,
                                    blending: THREE.AdditiveBlending, depthWrite: false }));
    pillar.position.set(sqX(sq), 1.5, sqZ(sq));
    this.effects.add(pillar);
    this._sfx("promote");
    await this._anim(400, (t) => { pillar.material.opacity = 0.7 * t; pillar.scale.set(1, t, 1); });
    this._flash(new THREE.Vector3(sqX(sq), 0.7, sqZ(sq)), a.magic, 2.2, 500);
    this._replaceLetter(sq, letter);
    const unit = this.meshes.get(sq);
    await this._anim(450, (t) => {
      unit.scale.setScalar(0.3 + 0.7 * easeOut(t));
      pillar.material.opacity = 0.7 * (1 - t);
    });
    this.effects.remove(pillar);
    pillar.geometry.dispose();
    pillar.material.dispose();
  }

  // ------------------------------------------------------------ checkmate: the king kneels

  _standOrKneel(fen, mated) {
    const turnWhite = fen.split(" ")[1] === "w";
    let kingSq = null;
    for (const [sq, l] of this.position) if (l === (turnWhite ? "K" : "k")) kingSq = sq;
    const king = kingSq !== null ? this.meshes.get(kingSq) : null;
    if (this.kneeling && (this.kneeling !== king || !mated)) { // undo after mate: stand up
      this._restorePose(this.kneeling);
      this.kneeling.userData.busy = false;
      this.kneeling = null;
    }
    if (!mated || !king || this.kneeling === king) return;
    this.kneeling = king;
    king.userData.busy = true;
    this._savePose(king);
    const r = king.userData.rig;
    const hy = r.hips.position.y;
    this._sfx("kneel");
    this._anim(1100, (t) => {
      const e = easeInOut(t);
      r.hips.position.y = hy - 0.2 * e;
      r.legL.rotation.x = -1.5 * e;
      r.legR.rotation.x = 1.2 * e;
      r.body.rotation.x = 0.45 * e;
      r.head.rotation.x = 0.4 * e;
      r.armL.rotation.x = lerp(-0.5, 0.1, e);
      r.runes.scale.setScalar(1 - e);
      r.handGlow.material.opacity = 1 - e;
    });
  }

  // ------------------------------------------------------------ intro: the armies march in

  playIntro(options) { // after any queued position, so the march uses the new game's units
    this._enqueue(() => this._startIntro(options));
  }

  _startIntro({ drop = false } = {}) {
    super.playIntro({ drop: false });
    if (!drop) return;
    this._sfx("march");
    this.march = { start: performance.now(), units: [] };
    for (const [sq, unit] of this.meshes) {
      if (sq < 0) continue;
      const side = unit.userData.color === "white" ? 1 : -1;
      unit.userData.busy = true;
      this._savePose(unit);
      unit.userData.rig.hips && (unit.userData.rig.hips.userData.y0 ??= unit.userData.rig.hips.position.y);
      this.march.units.push({ unit, z: sqZ(sq), side, delay: 0.12 + Math.random() * 0.12 });
      unit.position.z = sqZ(sq) + side * 3.2;
    }
  }

  _marchFrame(now) {
    const p = clamp01((now - this.march.start) / 4200);
    for (const m of this.march.units) {
      const local = clamp01((p - m.delay) / 0.55);
      m.unit.position.z = m.z + m.side * 3.2 * (1 - easeOut(local));
      if (local < 1) this._gait(m.unit, local * 10 * Math.PI, Math.min(1, (1 - local) * 4));
    }
    if (p >= 1) this._endMarch();
  }

  _endMarch() {
    if (!this.march) return;
    for (const m of this.march.units) {
      m.unit.position.z = m.z;
      this._restorePose(m.unit);
      m.unit.userData.busy = false;
    }
    this.march = null;
  }

  _endIntro() {
    super._endIntro();
    this._endMarch();
  }

  _home() {
    return { angle: this.orientation === "white" ? 0 : Math.PI, dist: 10.6, height: 11.0 };
  }

  _createPiece(type, color) {
    const unit = buildUnit(type, color);
    // phones: the soldiers' many small parts don't cast shadows (halves the drawing work);
    // their round bases still sit them on the ground
    if (this.quality === "low") unit.traverse((o) => { if (o.isMesh) o.castShadow = false; });
    return unit;
  }

  // ------------------------------------------------------------ scenery

  _buildLights() {
    this.scene.add(new THREE.HemisphereLight("#ffe2bd", "#3a2c1f", 1.15));
    const sun = new THREE.DirectionalLight("#ffd3a0", 3.0); // low evening sun
    sun.position.set(7, 8, 3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(this.shadowSize, this.shadowSize);
    Object.assign(sun.shadow.camera, { left: -7, right: 7, top: 7, bottom: -7, near: 2, far: 30 });
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    this.scene.add(sun);
    const moon = new THREE.DirectionalLight("#8aa2ff", 0.55);
    moon.position.set(-6, 6, -7);
    this.scene.add(moon);
  }

  _buildBoard() {
    this.scene.environmentIntensity = 0.3;
    this.scene.fog = new THREE.Fog("#5b4446", 18, 52);
    const sandstone = noiseTexture("sandstone", { colors: ["#b3a68c", "#d6cbb0", "#c2b598"], seed: 2,
                                                  cracks: 0.18, speckle: 0.3 });
    const slate = noiseTexture("slate", { colors: ["#3a3835", "#55524d", "#44413d"], seed: 4,
                                          cracks: 0.2, speckle: 0.3 });
    this._buildTiles(sandstone, slate, { roughness: 0.9, metalness: 0 });
    this._buildStoneFrame();
    this._buildGround();
    this._buildRocks();
    this._buildTrees();
    this._buildTorches();
    this._buildBanners();
    this._buildSky();
    this._buildDust();
    this._buildLabels("#f6e2b8");
    this._buildDots();
  }

  _buildStoneFrame() {
    const stone = new THREE.MeshStandardMaterial({
      map: noiseTexture("frame-stone", { colors: ["#3b342d", "#5a5046", "#463e35"], seed: 6, cracks: 0.6 }),
      roughness: 0.95 });
    const R = 4.75, r = 4.0;
    const outer = new THREE.Shape();
    outer.moveTo(-R, -R); outer.lineTo(R, -R); outer.lineTo(R, R); outer.lineTo(-R, R); outer.lineTo(-R, -R);
    const hole = new THREE.Path();
    hole.moveTo(-r, -r); hole.lineTo(-r, r); hole.lineTo(r, r); hole.lineTo(r, -r); hole.lineTo(-r, -r);
    outer.holes.push(hole);
    const geo = new THREE.ExtrudeGeometry(outer, { depth: 0.44, bevelEnabled: true,
      bevelThickness: 0.04, bevelSize: 0.08, bevelSegments: 2 });
    geo.rotateX(-Math.PI / 2);
    geo.translate(0, GROUND_Y, 0);
    const frame = new THREE.Mesh(geo, stone);
    frame.castShadow = frame.receiveShadow = true;
    this.scene.add(frame);
    const under = new THREE.Mesh(new THREE.BoxGeometry(8.02, 0.36, 8.02), stone);
    under.position.y = -0.26;
    this.scene.add(under);
  }

  _buildGround() {
    const map = noiseTexture("battle-ground", {
      colors: ["#3c2f1f", "#584529", "#4f5728", "#3a4420"], seed: 12, cracks: 0.25, speckle: 0.5 });
    map.repeat.set(16, 16);
    const ground = new THREE.Mesh(new THREE.CircleGeometry(60, 48),
      new THREE.MeshStandardMaterial({ map, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = GROUND_Y;
    ground.receiveShadow = true;
    this.scene.add(ground);
  }

  _buildRocks() {
    const r = rng(7);
    const mats = ["#5d5650", "#6e665c", "#4a443f"].map((c) =>
      new THREE.MeshStandardMaterial({ color: c, roughness: 0.95, flatShading: true }));
    for (let i = 0; i < 34; i++) {
      const ang = r() * Math.PI * 2, dist = 7 + r() * 14;
      const size = 0.25 + r() * (dist > 12 ? 1.4 : 0.6);
      const rock = new THREE.Mesh(new THREE.DodecahedronGeometry(size, 0), mats[i % 3]);
      rock.position.set(Math.sin(ang) * dist, GROUND_Y + size * 0.2, Math.cos(ang) * dist);
      rock.rotation.set(r() * 3, r() * 3, r() * 3);
      rock.scale.y = 0.6 + r() * 0.5;
      rock.castShadow = rock.receiveShadow = true;
      this.scene.add(rock);
    }
  }

  _buildTrees() {
    const r = rng(19);
    const bark = new THREE.MeshStandardMaterial({ color: "#3b2a1e", roughness: 1, flatShading: true });
    const branch = (parent, len, rad, depth) => {
      const seg = new THREE.Mesh(new THREE.CylinderGeometry(rad * 0.6, rad, len, 6), bark);
      seg.position.y = len / 2;
      seg.castShadow = true;
      parent.add(seg);
      if (depth === 0) return;
      const tip = new THREE.Group();
      tip.position.y = len;
      parent.add(tip);
      const n = depth === 3 ? 1 : 2 + Math.floor(r() * 2);
      for (let i = 0; i < n; i++) {
        const g = new THREE.Group();
        g.rotation.set((r() - 0.5) * 1.4, r() * Math.PI * 2, (r() - 0.5) * 1.4 + (depth === 3 ? 0 : 0.3));
        tip.add(g);
        branch(g, len * (0.6 + r() * 0.25), rad * 0.6, depth - 1);
      }
    };
    for (let i = 0; i < 8; i++) {
      const ang = (i / 8) * Math.PI * 2 + r() * 0.5, dist = 10 + r() * 7;
      const tree = new THREE.Group();
      tree.position.set(Math.sin(ang) * dist, GROUND_Y, Math.cos(ang) * dist);
      tree.rotation.y = r() * Math.PI * 2;
      tree.scale.setScalar(0.9 + r() * 0.8);
      branch(tree, 1.6, 0.16, 3);
      this.scene.add(tree);
    }
  }

  _buildTorches() {
    this.torches = [];
    const iron = new THREE.MeshStandardMaterial({ color: "#2a2623", metalness: 0.6, roughness: 0.5 });
    const fire = new THREE.MeshStandardMaterial({ color: "#ffb347", emissive: "#ff7a1a", emissiveIntensity: 3 });
    for (const [x, z] of [[-5.3, -5.3], [5.3, -5.3], [-5.3, 5.3], [5.3, 5.3]]) {
      const t = new THREE.Group();
      t.position.set(x, GROUND_Y, z);
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.08, 1.5, 8), iron);
      pole.position.y = 0.75;
      pole.castShadow = true;
      const bowl = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.1, 0.16, 10), iron);
      bowl.position.y = 1.55;
      const flame = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.42, 8), fire);
      flame.position.y = 1.8;
      const glow = glowSprite("#ff9a3c", 1.4, 0.8);
      glow.position.y = 1.85;
      const light = new THREE.PointLight("#ff9440", 7, 9, 1.6);
      light.position.y = 1.9;
      t.add(pole, bowl, flame, glow, light);
      this.scene.add(t);
      this.torches.push({ flame, glow, light, seed: x * 3 + z });
    }
  }

  _buildBanners() {
    this.banners = [];
    const wood = new THREE.MeshStandardMaterial({ color: "#4a3422", roughness: 0.9 });
    for (const [color, z] of [["white", 6.3], ["black", -6.3]]) {
      const a = ARMIES[color];
      for (const x of [-3, 3]) {
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 3, 8), wood);
        pole.position.set(x, GROUND_Y + 1.25, z);
        pole.castShadow = true;
        const flag = new THREE.Group();
        flag.position.set(x, GROUND_Y + 2.45, z);
        const cloth = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 1.3, 8, 1),
          new THREE.MeshStandardMaterial({ color: a.banner, roughness: 0.9, side: THREE.DoubleSide }));
        cloth.position.set(0.45, -0.55, 0);
        const stripe = new THREE.Mesh(new THREE.PlaneGeometry(0.9, 0.12),
          new THREE.MeshStandardMaterial({ color: a.trim, roughness: 0.6, side: THREE.DoubleSide }));
        stripe.position.set(0.45, -0.02, 0.002);
        cloth.castShadow = true;
        flag.add(cloth, stripe);
        flag.rotation.y = x < 0 ? 0 : Math.PI;
        this.scene.add(pole, flag);
        this.banners.push({ flag, base: flag.rotation.y, phase: x + z });
      }
    }
  }

  _buildSky() {
    const sky = new THREE.Mesh(new THREE.SphereGeometry(70, 32, 16), new THREE.MeshBasicMaterial({
      map: skyTexture("dusk", [[0, "#141b30"], [0.38, "#463e5c"], [0.47, "#b9705a"],
                               [0.5, "#e39b5e"], [0.52, "#5b4446"], [1, "#2a201b"]]),
      side: THREE.BackSide, fog: false, depthWrite: false }));
    sky.raycast = () => {};
    this.scene.add(sky);
  }

  _buildDust() { // embers and dust drifting over the field
    const n = 140, r = rng(31);
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (r() - 0.5) * 22;
      pos[i * 3 + 1] = r() * 5;
      pos[i * 3 + 2] = (r() - 0.5) * 22;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.dust = new THREE.Points(geo, new THREE.PointsMaterial({
      color: "#ffcf8a", size: 0.05, transparent: true, opacity: 0.7, depthWrite: false,
      blending: THREE.AdditiveBlending }));
    this.dust.raycast = () => {};
    this.scene.add(this.dust);
  }

  // ------------------------------------------------------------ idle animation

  _animateIdle(now) {
    const t = now / 1000;
    if (this.march) this._marchFrame(now);
    for (const [sq, unit] of this.meshes) if (sq >= 0 && !unit.userData.busy) unit.userData.idle?.(t);
    if (this.checkSquare !== null) { // the king in check: his rune circle flares
      const k = this.meshes.get(this.checkSquare)?.userData.rig?.runes;
      if (k) k.scale.setScalar(1.15 + 0.3 * Math.sin(t * 9));
    }
    for (const tc of this.torches) {
      const f = 0.82 + 0.1 * Math.sin(t * 11 + tc.seed) + 0.08 * Math.sin(t * 23 + tc.seed * 2);
      tc.light.intensity = 7 * f;
      tc.flame.scale.set(1, f * 1.1, 1);
      tc.glow.scale.setScalar(1.3 * f);
    }
    for (const b of this.banners) b.flag.rotation.y = b.base + Math.sin(t * 1.8 + b.phase) * 0.18;
    if (this.dust) {
      const p = this.dust.geometry.attributes.position;
      for (let i = 0; i < p.count; i++) {
        let y = p.getY(i) + 0.004;
        if (y > 5) y = 0;
        p.setY(i, y);
        p.setX(i, p.getX(i) + Math.sin(t * 0.5 + i) * 0.002);
      }
      p.needsUpdate = true;
    }
  }
}
