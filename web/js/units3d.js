// Battle-mode units, built in code from simple shapes (boxes, cylinders, spheres, cones).
// Our own low-poly designs: no models or images are downloaded.
//
//   pawn   -> spearman              knight -> horse archer
//   bishop -> javelin priest        rook   -> war elephant with an archer tower
//   queen  -> sorceress             king   -> warlord-mage
//
// Every unit is built facing +z and stands on a round army-coloured base. Its moving
// parts are pivot groups (joints) listed in ``userData.rig``, so the animations (idle
// here, attacks in battle3d.js) only rotate joints. ``userData.idle(t)`` animates the unit
// while it waits.

import * as THREE from "three";
import { mergeGeometries } from "../vendor/three/BufferGeometryUtils.js";

export const ARMIES = {
  white: { metal: "#c9a24a", cloth: "#2a5bb0", trim: "#efe0b0", skin: "#e2b893", leather: "#7a5233",
           hair: "#6b4a2a", magic: "#6cc6ff", horse: "#e9e2d4", elephant: "#9a958e", banner: "#2a5bb0" },
  black: { metal: "#3b3b42", cloth: "#9a1d24", trim: "#1d1d22", skin: "#c99673", leather: "#3a2618",
           hair: "#1b1410", magic: "#ff5a30", horse: "#3a2a22", elephant: "#625d58", banner: "#9a1d24" },
};

// ------------------------------------------------------------------ shared materials

const materials = new Map();
function mat(color, { metal = 0, rough = 0.7, emissive = null, intensity = 1 } = {}) {
  const key = `${color}|${metal}|${rough}|${emissive}|${intensity}`;
  if (!materials.has(key)) {
    materials.set(key, new THREE.MeshStandardMaterial({
      color, metalness: metal, roughness: rough,
      emissive: emissive || "#000000", emissiveIntensity: emissive ? intensity : 0 }));
  }
  return materials.get(key);
}
const metalMat = (a) => mat(a.metal, { metal: 0.75, rough: 0.35 });
const clothMat = (a) => mat(a.cloth, { rough: 0.85 });
const trimMat = (a) => mat(a.trim, { metal: 0.3, rough: 0.5 });
const skinMat = (a) => mat(a.skin, { rough: 0.8 });
const leatherMat = (a) => mat(a.leather, { rough: 0.9 });
const woodMat = () => mat("#6a4a2c", { rough: 0.85 });
const steelMat = () => mat("#cfd3d8", { metal: 0.9, rough: 0.25 });
const glowMat = (a, i = 2.2) => mat(a.magic, { emissive: a.magic, intensity: i, rough: 0.3 });

// ------------------------------------------------------------------ shape helpers

function add(parent, mesh, x = 0, y = 0, z = 0) {
  mesh.position.set(x, y, z);
  mesh.castShadow = true;
  parent.add(mesh);
  return mesh;
}
const box = (w, h, d, m) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
const cyl = (rt, rb, h, m, seg = 12) => new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
const sph = (r, m, w = 14, h = 10) => new THREE.Mesh(new THREE.SphereGeometry(r, w, h), m);
const cone = (r, h, m, seg = 12) => new THREE.Mesh(new THREE.ConeGeometry(r, h, seg), m);
function pivot(parent, x = 0, y = 0, z = 0) {
  const g = new THREE.Group();
  g.position.set(x, y, z);
  parent.add(g);
  return g;
}

/** Soft round glow (additive sprite), used for magic, torches and arrow tips. */
let glowTexture = null;
export function glowSprite(color, size = 0.5, opacity = 0.9) {
  if (!glowTexture) {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const g = c.getContext("2d");
    const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.25, "rgba(255,255,255,0.6)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    glowTexture = new THREE.CanvasTexture(c);
  }
  const s = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTexture, color, transparent: true, opacity, depthWrite: false,
    blending: THREE.AdditiveBlending }));
  s.scale.setScalar(size);
  s.raycast = () => {}; // glows are never clicked
  return s;
}

/** Round base every unit stands on, in its army's colour. */
function base(root, a, r = 0.36) {
  const b = add(root, cyl(r, r + 0.02, 0.05, clothMat(a), 28), 0, 0.025, 0);
  b.receiveShadow = true;
  add(root, cyl(r + 0.025, r + 0.03, 0.025, trimMat(a), 28), 0, 0.012, 0);
}

// ------------------------------------------------------------------ humanoid

/**
 * A simple person: legs, body, head and two arms with elbows.
 * @returns {{root: THREE.Group, rig: object}} rig = joints and attachment points
 */
function humanoid(a, { robe = false, armour = true, helmet = "cap", height = 1 } = {}) {
  const root = new THREE.Group();
  const rig = {};
  const s = height;
  rig.hips = pivot(root, 0, 0.42 * s, 0);

  if (robe) { // long robe instead of visible legs
    add(rig.hips, cyl(0.12 * s, 0.2 * s, 0.42 * s, clothMat(a), 14), 0, -0.2 * s, 0);
    add(rig.hips, cyl(0.205 * s, 0.215 * s, 0.04 * s, trimMat(a), 14), 0, -0.4 * s, 0);
  } else {
    for (const side of [-1, 1]) {
      const leg = pivot(rig.hips, 0.07 * s * side, 0, 0);
      add(leg, cyl(0.045 * s, 0.04 * s, 0.38 * s, leatherMat(a)), 0, -0.19 * s, 0);
      add(leg, box(0.07 * s, 0.05 * s, 0.12 * s, leatherMat(a)), 0, -0.39 * s, 0.02 * s);
      rig[side < 0 ? "legL" : "legR"] = leg;
    }
  }

  rig.body = pivot(rig.hips, 0, 0, 0);
  add(rig.body, box(0.24 * s, 0.3 * s, 0.15 * s, clothMat(a)), 0, 0.16 * s, 0);
  if (armour) {
    add(rig.body, box(0.26 * s, 0.2 * s, 0.17 * s, metalMat(a)), 0, 0.22 * s, 0);
    add(rig.body, box(0.25 * s, 0.035 * s, 0.16 * s, leatherMat(a)), 0, 0.04 * s, 0);
    for (const side of [-1, 1]) {
      add(rig.body, sph(0.06 * s, metalMat(a), 10, 8), 0.15 * s * side, 0.3 * s, 0);
    }
  } else {
    add(rig.body, box(0.255 * s, 0.035 * s, 0.16 * s, trimMat(a)), 0, 0.06 * s, 0);
  }

  rig.head = pivot(rig.body, 0, 0.33 * s, 0);
  add(rig.head, cyl(0.035 * s, 0.04 * s, 0.05 * s, skinMat(a)), 0, 0.01 * s, 0);
  add(rig.head, sph(0.085 * s, skinMat(a)), 0, 0.09 * s, 0);
  if (helmet === "cap") {
    add(rig.head, cyl(0.06 * s, 0.095 * s, 0.09 * s, metalMat(a), 12), 0, 0.15 * s, 0);
    add(rig.head, box(0.02 * s, 0.07 * s, 0.02 * s, metalMat(a)), 0, 0.09 * s, 0.09 * s);
    add(rig.head, cone(0.02 * s, 0.07 * s, metalMat(a), 6), 0, 0.23 * s, 0);
  }

  for (const side of [-1, 1]) {
    const arm = pivot(rig.body, 0.16 * s * side, 0.29 * s, 0);
    add(arm, cyl(0.035 * s, 0.032 * s, 0.2 * s, armour ? metalMat(a) : clothMat(a)), 0, -0.1 * s, 0);
    const fore = pivot(arm, 0, -0.2 * s, 0);
    add(fore, cyl(0.032 * s, 0.028 * s, 0.18 * s, armour ? leatherMat(a) : clothMat(a)), 0, -0.09 * s, 0);
    const hand = pivot(fore, 0, -0.19 * s, 0);
    add(hand, sph(0.033 * s, skinMat(a), 8, 6));
    const k = side < 0 ? "L" : "R";
    rig[`arm${k}`] = arm;
    rig[`fore${k}`] = fore;
    rig[`hand${k}`] = hand;
  }
  return { root, rig };
}

// ------------------------------------------------------------------ weapons

function spear(hand, len = 1.0) {
  const g = pivot(hand);
  add(g, cyl(0.012, 0.012, len, woodMat(), 6), 0, len * 0.2, 0);
  add(g, cone(0.03, 0.12, steelMat(), 6), 0, len * 0.7 + 0.05, 0);
  return g;
}

function bow(hand, a) {
  const g = pivot(hand);
  const arc = new THREE.Mesh(new THREE.TorusGeometry(0.2, 0.012, 6, 16, Math.PI * 0.9), woodMat());
  arc.rotation.set(0, Math.PI / 2, Math.PI / 2 + Math.PI * 0.05);
  add(g, arc, 0, 0, -0.02);
  add(g, cyl(0.003, 0.003, 0.39, trimMat(a), 4), 0, 0, -0.02 - 0.0);
  return g;
}

function sword(hand) {
  const g = pivot(hand);
  add(g, box(0.035, 0.5, 0.012, steelMat()), 0, -0.3, 0);
  add(g, box(0.14, 0.025, 0.03, mat("#b8923a", { metal: 0.8, rough: 0.3 })), 0, -0.05, 0);
  add(g, cyl(0.016, 0.016, 0.1, leatherMat(ARMIES.white)), 0, 0.02, 0);
  return g;
}

function staff(hand, a, len = 1.15) {
  const g = pivot(hand);
  add(g, cyl(0.018, 0.022, len, woodMat(), 8), 0, len * 0.25, 0);
  const top = pivot(g, 0, len * 0.75 + 0.06, 0);
  add(top, sph(0.065, glowMat(a, 2.5), 16, 12));
  const glow = glowSprite(a.magic, 0.55);
  top.add(glow);
  for (let i = 0; i < 3; i++) { // claws holding the orb
    const c = add(top, cone(0.015, 0.12, trimMat(a), 4), 0, -0.04, 0);
    c.rotation.z = 0.5;
    c.rotation.y = (i / 3) * Math.PI * 2;
    c.position.set(Math.sin((i / 3) * Math.PI * 2) * 0.05, -0.05, Math.cos((i / 3) * Math.PI * 2) * 0.05);
  }
  return { g, top, glow };
}

// ------------------------------------------------------------------ units

function spearman(a) {
  const root = new THREE.Group();
  base(root, a, 0.27);
  const { root: man, rig } = humanoid(a, { helmet: "cap" });
  root.add(man);
  // right hand holds the spear upright, left forearm carries a round shield
  rig.armR.rotation.x = -0.25;
  rig.foreR.rotation.x = -1.0;
  const sp = spear(rig.handR, 1.05);
  sp.rotation.x = 1.25;
  rig.spear = sp;
  rig.armL.rotation.set(-0.2, 0, 0.15);
  rig.foreL.rotation.x = -1.2;
  const shield = pivot(rig.foreL, 0.02, -0.1, 0.05);
  const disc = add(shield, cyl(0.14, 0.14, 0.03, clothMat(a), 18));
  disc.rotation.x = Math.PI / 2;
  disc.rotation.z = 0;
  add(shield, cyl(0.15, 0.15, 0.02, metalMat(a), 18), 0, 0, -0.008).rotation.x = Math.PI / 2;
  add(shield, sph(0.035, metalMat(a), 8, 6), 0, 0, 0.02);
  shield.rotation.x = 1.2;
  rig.shield = shield;
  return finish(root, rig, "p", (t, r) => {
    r.body.rotation.x = Math.sin(t * 1.6) * 0.02;
    r.body.scale.y = 1 + Math.sin(t * 1.6) * 0.012;
    r.head.rotation.y = Math.sin(t * 0.5) * 0.15;
  });
}

function horse(a) {
  const g = new THREE.Group();
  const rig = {};
  const coat = mat(a.horse, { rough: 0.75 });
  const dark = mat(a.hair, { rough: 0.9 });
  rig.horseBody = pivot(g, 0, 0.5, 0);
  const torso = add(rig.horseBody, new THREE.Mesh(new THREE.CapsuleGeometry(0.13, 0.36, 6, 12), coat));
  torso.rotation.x = Math.PI / 2;
  // saddle cloth in army colours
  add(rig.horseBody, box(0.3, 0.06, 0.3, clothMat(a)), 0, 0.11, 0.0);
  add(rig.horseBody, box(0.31, 0.02, 0.31, trimMat(a)), 0, 0.08, 0.0);
  rig.neck = pivot(rig.horseBody, 0, 0.06, 0.2);
  const neck = add(rig.neck, cyl(0.07, 0.1, 0.3, coat), 0, 0.12, 0.05);
  neck.rotation.x = 0.55;
  add(rig.neck, box(0.03, 0.26, 0.08, dark), 0, 0.14, 0.0).rotation.x = 0.55;
  const head = pivot(rig.neck, 0, 0.27, 0.14);
  rig.horseHead = head;
  add(head, box(0.1, 0.11, 0.24, coat), 0, 0, 0.06).rotation.x = 0.35;
  for (const s of [-1, 1]) add(head, cone(0.02, 0.07, coat, 5), 0.03 * s, 0.08, -0.03);
  rig.hooves = [];
  for (const [x, z] of [[-0.08, 0.17], [0.08, 0.17], [-0.08, -0.17], [0.08, -0.17]]) {
    const leg = pivot(g, x, 0.44, z);
    add(leg, cyl(0.03, 0.025, 0.4, coat, 8), 0, -0.2, 0);
    add(leg, cyl(0.032, 0.035, 0.04, dark, 8), 0, -0.41, 0);
    rig.hooves.push(leg);
  }
  rig.tail = pivot(rig.horseBody, 0, 0.04, -0.3);
  add(rig.tail, cyl(0.02, 0.04, 0.28, dark, 6), 0, -0.12, -0.03).rotation.x = -0.3;
  return { g, rig };
}

function horseArcher(a) {
  const root = new THREE.Group();
  base(root, a, 0.32);
  const { g: h, rig } = horse(a);
  h.scale.setScalar(1.05);
  root.add(h);
  const { root: man, rig: r } = humanoid(a, { helmet: "cap", height: 0.85 });
  man.position.set(0, 0.15 - 0.42 * 0.85, -0.02); // hips sit on the saddle
  rig.horseBody.add(man);
  r.legL.rotation.set(-1.3, 0, 0.45);
  r.legR.rotation.set(-1.3, 0, -0.45);
  // left hand holds the bow out to the side, right hand by the quiver
  r.armL.rotation.set(-0.6, 0, 0.5);
  r.foreL.rotation.x = -0.3;
  rig.bow = bow(r.handL, a);
  rig.bow.rotation.y = 0.4;
  r.armR.rotation.set(0.2, 0, -0.2);
  const quiver = pivot(r.body, 0.06, 0.2, -0.1);
  add(quiver, cyl(0.035, 0.03, 0.22, leatherMat(a), 8)).rotation.z = 0.3;
  for (let i = 0; i < 3; i++) add(quiver, cyl(0.004, 0.004, 0.12, woodMat(), 4), 0.02 + i * 0.012, 0.15, 0);
  Object.assign(rig, r);
  return finish(root, rig, "n", (t, q) => {
    q.horseBody.position.y = 0.5 + Math.sin(t * 1.8) * 0.006;
    q.neck.rotation.x = Math.sin(t * 0.9) * 0.08;
    q.tail.rotation.z = Math.sin(t * 2.2) * 0.25;
    q.hooves[0].rotation.x = Math.max(0, Math.sin(t * 0.7)) * 0.25; // paws the ground now and then
    q.head.rotation.y = Math.sin(t * 0.6) * 0.2;
  });
}

function javelinPriest(a) {
  const root = new THREE.Group();
  base(root, a, 0.27);
  const { root: man, rig } = humanoid(a, { robe: true, armour: false, helmet: "none" });
  root.add(man);
  // tall mitre
  add(rig.head, cyl(0.06, 0.09, 0.18, trimMat(a), 10), 0, 0.2, 0);
  add(rig.head, cone(0.06, 0.12, trimMat(a), 10), 0, 0.35, 0);
  add(rig.head, box(0.02, 0.2, 0.095, clothMat(a)), 0, 0.22, 0.045);
  // stole over the shoulders
  add(rig.body, box(0.08, 0.32, 0.02, trimMat(a)), 0, 0.14, 0.082);
  // right hand raises a javelin with a glowing tip
  rig.armR.rotation.set(-0.1, 0, -0.15);
  rig.foreR.rotation.x = -1.2;
  const jav = pivot(rig.handR);
  add(jav, cyl(0.01, 0.01, 0.85, woodMat(), 6), 0, 0.15, 0);
  add(jav, cone(0.025, 0.1, glowMat(a, 1.8), 6), 0, 0.62, 0);
  const tipGlow = glowSprite(a.magic, 0.28);
  tipGlow.position.y = 0.62;
  jav.add(tipGlow);
  jav.rotation.x = 1.3;
  rig.javelin = jav;
  rig.tipGlow = tipGlow;
  rig.armL.rotation.set(-0.5, 0, 0.2);
  rig.foreL.rotation.x = -0.6;
  return finish(root, rig, "b", (t, r) => {
    r.body.rotation.y = Math.sin(t * 0.7) * 0.06;
    r.body.scale.y = 1 + Math.sin(t * 1.4) * 0.012;
    r.tipGlow.material.opacity = 0.6 + Math.sin(t * 3) * 0.3;
  });
}

function warElephant(a) {
  const root = new THREE.Group();
  base(root, a, 0.37);
  const rig = {};
  const hide = mat(a.elephant, { rough: 0.95 });
  const ivory = mat("#f2ead8", { rough: 0.5 });
  const e = pivot(root, 0, 0, 0);
  e.scale.setScalar(0.82);
  rig.elephant = e;
  rig.ebody = pivot(e, 0, 0.66, 0);
  add(rig.ebody, sph(0.3, hide, 18, 14)).scale.set(1, 0.85, 1.3);
  // blanket and armour plates
  add(rig.ebody, box(0.56, 0.3, 0.5, clothMat(a)), 0, 0.12, -0.02);
  add(rig.ebody, box(0.58, 0.05, 0.52, trimMat(a)), 0, -0.02, -0.02);
  rig.ehead = pivot(rig.ebody, 0, 0.08, 0.38);
  add(rig.ehead, sph(0.2, hide, 16, 12)).scale.set(1, 1, 0.9);
  add(rig.ehead, box(0.22, 0.12, 0.05, metalMat(a)), 0, 0.08, 0.15);
  for (const s of [-1, 1]) {
    const ear = pivot(rig.ehead, 0.17 * s, 0.03, -0.05);
    const disc = add(ear, cyl(0.16, 0.16, 0.025, hide, 14), 0.06 * s, -0.02, 0);
    disc.rotation.z = Math.PI / 2;
    rig[s < 0 ? "earL" : "earR"] = ear;
    const tusk = add(rig.ehead, cone(0.025, 0.24, ivory, 8), 0.08 * s, -0.12, 0.17);
    tusk.rotation.x = Math.PI / 2 + 0.4;
  }
  // trunk: three segments, each a joint
  rig.trunk = [];
  let parent = pivot(rig.ehead, 0, -0.06, 0.16);
  for (let i = 0; i < 3; i++) {
    const r0 = 0.07 - i * 0.015;
    add(parent, cyl(r0 * 0.8, r0, 0.16, hide, 10), 0, -0.08, 0);
    rig.trunk.push(parent);
    parent.rotation.x = i === 0 ? 0.25 : 0.2;
    parent = pivot(parent, 0, -0.16, 0);
  }
  rig.legs = [];
  for (const [x, z] of [[-0.17, 0.22], [0.17, 0.22], [-0.17, -0.22], [0.17, -0.22]]) {
    const leg = pivot(e, x, 0.5, z);
    add(leg, cyl(0.085, 0.09, 0.5, hide, 10), 0, -0.25, 0);
    add(leg, cyl(0.095, 0.1, 0.04, ivory, 10), 0, -0.48, 0);
    rig.legs.push(leg);
  }
  rig.etail = pivot(rig.ebody, 0, 0.0, -0.38);
  add(rig.etail, cyl(0.01, 0.02, 0.25, hide, 6), 0, -0.12, 0);
  // the tower (howdah) with an archer in it
  const tower = pivot(rig.ebody, 0, 0.38, -0.04);
  add(tower, box(0.42, 0.22, 0.4, woodMat()));
  add(tower, box(0.44, 0.04, 0.42, metalMat(a)), 0, 0.12, 0);
  for (const [x, z] of [[-0.18, -0.17], [0.18, -0.17], [-0.18, 0.17], [0.18, 0.17], [0, 0.18], [0, -0.18]]) {
    add(tower, box(0.08, 0.1, 0.06, metalMat(a)), x, 0.18, z);
  }
  const flagPole = add(tower, cyl(0.008, 0.008, 0.45, woodMat(), 4), -0.18, 0.4, -0.17);
  const flag = add(tower, box(0.16, 0.1, 0.005, clothMat(a)), -0.1, 0.56, -0.17);
  flag.userData.keep = true; // waves on its own
  rig.flag = flag;
  void flagPole;
  const { root: archer, rig: ar } = humanoid(a, { helmet: "cap", height: 0.62 });
  archer.position.set(0, -0.06, 0.02);
  tower.add(archer);
  ar.armL.rotation.set(-1.2, 0, 0.3);
  rig.towerBow = bow(ar.handL, a);
  rig.towerArcher = ar;
  return finish(root, rig, "r", (t, r) => {
    r.ebody.position.y = 0.66 + Math.sin(t * 1.1) * 0.008;
    r.earL.rotation.y = -0.2 + Math.sin(t * 1.7) * 0.25;
    r.earR.rotation.y = 0.2 - Math.sin(t * 1.7 + 0.5) * 0.25;
    r.trunk[0].rotation.x = 0.25 + Math.sin(t * 0.9) * 0.12;
    r.trunk[1].rotation.x = 0.2 + Math.sin(t * 0.9 + 0.6) * 0.18;
    r.trunk[2].rotation.x = 0.2 + Math.sin(t * 0.9 + 1.2) * 0.25;
    r.etail.rotation.z = Math.sin(t * 2.5) * 0.3;
    r.flag.rotation.y = Math.sin(t * 2.6) * 0.3;
  });
}

function sorceress(a) {
  const root = new THREE.Group();
  base(root, a, 0.29);
  const { root: w, rig } = humanoid(a, { robe: true, armour: false, helmet: "none", height: 1.12 });
  root.add(w);
  const s = 1.12;
  // long hair, crown and a flowing cape
  add(rig.head, sph(0.092 * s, mat(a.hair), 12, 10), 0, 0.1 * s, -0.02).scale.set(1, 1.05, 1);
  add(rig.head, box(0.16 * s, 0.24 * s, 0.05 * s, mat(a.hair)), 0, -0.02, -0.07);
  const crown = add(rig.head, cyl(0.075 * s, 0.08 * s, 0.05, mat("#e3bf54", { metal: 0.9, rough: 0.25 }), 14), 0, 0.18 * s, 0);
  for (let i = 0; i < 6; i++) {
    const p = add(crown, cone(0.015, 0.06, mat("#e3bf54", { metal: 0.9, rough: 0.25 }), 4), 0, 0.05, 0);
    const ang = (i / 6) * Math.PI * 2;
    p.position.set(Math.sin(ang) * 0.075, 0.05, Math.cos(ang) * 0.075);
  }
  add(crown, sph(0.02, glowMat(a, 3), 8, 6), 0, 0.03, 0.085);
  rig.cape = pivot(rig.body, 0, 0.32 * s, -0.08);
  add(rig.cape, box(0.3 * s, 0.75 * s, 0.02, clothMat(a)), 0, -0.36 * s, 0);
  // staff with a glowing orb, three sparks circling it
  rig.armR.rotation.set(-0.2, 0, -0.15);
  rig.foreR.rotation.x = -0.9;
  const st = staff(rig.handR, a, 1.2);
  st.g.rotation.x = 1.1;
  rig.staff = st.g;
  rig.orb = st.top;
  rig.orbGlow = st.glow;
  rig.sparks = [];
  for (let i = 0; i < 3; i++) {
    const sp = glowSprite(a.magic, 0.1);
    st.top.add(sp);
    rig.sparks.push(sp);
  }
  rig.armL.rotation.set(-0.4, 0, 0.35);
  rig.foreL.rotation.x = -0.9;
  return finish(root, rig, "q", (t, r) => {
    r.body.scale.y = 1 + Math.sin(t * 1.3) * 0.012;
    r.cape.rotation.x = -0.08 - Math.sin(t * 1.5) * 0.06;
    r.orbGlow.scale.setScalar(0.5 + Math.sin(t * 3.2) * 0.08);
    r.sparks.forEach((sp, i) => {
      const ang = t * 2.4 + (i * Math.PI * 2) / 3;
      sp.position.set(Math.sin(ang) * 0.13, Math.sin(t * 3 + i) * 0.05, Math.cos(ang) * 0.13);
    });
  });
}

function warlordMage(a) {
  const root = new THREE.Group();
  base(root, a, 0.3);
  const { root: k, rig } = humanoid(a, { helmet: "none", height: 1.2 });
  root.add(k);
  const s = 1.2;
  const gold = mat("#e3bf54", { metal: 0.9, rough: 0.25 });
  // beard, crown with tall points, heavy cape
  add(rig.head, cone(0.06 * s, 0.12 * s, mat(a.hair), 8), 0, 0.02, 0.05).rotation.x = Math.PI;
  const crown = add(rig.head, cyl(0.085 * s, 0.09 * s, 0.07, gold, 14), 0, 0.17 * s, 0);
  for (let i = 0; i < 5; i++) {
    const ang = (i / 5) * Math.PI * 2;
    const p = add(crown, cone(0.022, 0.1, gold, 4), Math.sin(ang) * 0.09, 0.07, Math.cos(ang) * 0.09);
    void p;
  }
  add(crown, sph(0.025, glowMat(a, 3), 8, 6), 0, 0.0, 0.1);
  rig.cape = pivot(rig.body, 0, 0.32 * s, -0.09);
  add(rig.cape, box(0.34 * s, 0.7 * s, 0.025, clothMat(a)), 0, -0.34 * s, 0);
  add(rig.cape, box(0.36 * s, 0.05, 0.03, trimMat(a)), 0, 0, 0);
  // right hand: great sword resting point-down; left hand: open, gathering magic
  rig.armR.rotation.set(-0.35, 0, -0.1);
  rig.foreR.rotation.x = -0.5;
  rig.sword = sword(rig.handR);
  rig.sword.rotation.x = 0.85;
  rig.armL.rotation.set(-0.5, 0, 0.45);
  rig.foreL.rotation.x = -0.8;
  rig.handGlow = glowSprite(a.magic, 0.22);
  rig.handL.add(rig.handGlow);
  // glowing rune circle on the ground, turning slowly
  rig.runes = pivot(root, 0, 0.06, 0);
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.3, 0.34, 40), new THREE.MeshBasicMaterial({
    color: a.magic, transparent: true, opacity: 0.75, side: THREE.DoubleSide, depthWrite: false,
    blending: THREE.AdditiveBlending }));
  ring.rotation.x = -Math.PI / 2;
  ring.raycast = () => {};
  rig.runes.add(ring);
  for (let i = 0; i < 6; i++) {
    const ang = (i / 6) * Math.PI * 2;
    const rune = new THREE.Mesh(new THREE.PlaneGeometry(0.06, 0.06), ring.material);
    rune.rotation.set(-Math.PI / 2, 0, ang);
    rune.position.set(Math.sin(ang) * 0.32, 0.001, Math.cos(ang) * 0.32);
    rune.raycast = () => {};
    rig.runes.add(rune);
  }
  return finish(root, rig, "k", (t, r) => {
    r.body.scale.y = 1 + Math.sin(t * 1.2) * 0.012;
    r.cape.rotation.x = -0.06 - Math.sin(t * 1.4) * 0.05;
    r.runes.rotation.y = t * 0.4;
    r.handGlow.material.opacity = 0.5 + Math.sin(t * 2.6) * 0.35;
  });
}

/**
 * Speed-up: inside every joint, the shapes that never move relative to each other are
 * merged into one mesh per material, so the GPU draws ~3x fewer objects. Meshes marked
 * ``userData.keep`` (animated on their own) and meshes with children are left alone.
 */
function mergeStatic(root) {
  const groups = [];
  root.traverse((node) => groups.push(node));
  for (const node of groups) {
    const byMat = new Map();
    for (const child of node.children) {
      if (!child.isMesh || child.children.length || child.userData.keep) continue;
      if (!byMat.has(child.material)) byMat.set(child.material, []);
      byMat.get(child.material).push(child);
    }
    for (const [material, meshes] of byMat) {
      if (meshes.length < 2) continue;
      const geos = meshes.map((m) => {
        m.updateMatrix();
        return m.geometry.clone().applyMatrix4(m.matrix);
      });
      const merged = mergeGeometries(geos, false);
      if (!merged) continue;
      for (const m of meshes) node.remove(m);
      const one = new THREE.Mesh(merged, material);
      one.castShadow = true;
      node.add(one);
    }
  }
}

function finish(root, rig, type, idle) {
  mergeStatic(root);
  root.traverse((o) => { if (o.isMesh) o.castShadow = true; });
  const phase = Math.random() * 10; // units don't breathe in step
  root.userData.rig = rig;
  root.userData.type = type;
  root.userData.idle = (t) => idle(t + phase, rig);
  return root;
}

const BUILDERS = { p: spearman, n: horseArcher, b: javelinPriest, r: warElephant, q: sorceress, k: warlordMage };

/**
 * Build one battle unit facing its enemy (White faces -z, Black faces +z).
 * @param {"p"|"n"|"b"|"r"|"q"|"k"} type
 * @param {"white"|"black"} color
 */
export function buildUnit(type, color) {
  const unit = BUILDERS[type](ARMIES[color]);
  const g = new THREE.Group();
  g.add(unit);
  unit.rotation.y = color === "white" ? Math.PI : 0;
  unit.scale.setScalar(1.12); // a little larger than a square's half-width, easier to see
  g.userData = { ...unit.userData, body: unit, color };
  return g;
}
