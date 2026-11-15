// 3D chess pieces built in code: each piece is a profile (radius at each height) spun
// around the vertical axis (a "lathe", like turning wood), plus a few extra shapes for
// the knight's head, the king's cross and the queen's crown. Nothing is downloaded.

import * as THREE from "three";

const MATERIALS = {
  white: () => new THREE.MeshStandardMaterial({ color: "#efe2c6", roughness: 0.45, metalness: 0.05 }),
  black: () => new THREE.MeshStandardMaterial({ color: "#2b2420", roughness: 0.4, metalness: 0.1 }),
};

// [radius, height] points from the bottom up (units: board squares)
const BASE = [[0, 0], [0.36, 0], [0.37, 0.05], [0.33, 0.09], [0.3, 0.1], [0.3, 0.13], [0.24, 0.17]];
const PROFILES = {
  p: [...BASE, [0.15, 0.22], [0.11, 0.42], [0.18, 0.45], [0.18, 0.48], [0.1, 0.5],
      [0.16, 0.56], [0.17, 0.62], [0.14, 0.69], [0.07, 0.73], [0, 0.74]],
  r: [...BASE, [0.21, 0.24], [0.18, 0.6], [0.25, 0.64], [0.26, 0.78], [0.2, 0.78], [0.2, 0.72], [0, 0.72]],
  b: [...BASE, [0.15, 0.24], [0.11, 0.62], [0.2, 0.66], [0.2, 0.69], [0.11, 0.71], [0.16, 0.8],
      [0.17, 0.88], [0.13, 0.97], [0.05, 1.02], [0.06, 1.05], [0, 1.07]],
  q: [...BASE, [0.18, 0.24], [0.12, 0.78], [0.22, 0.82], [0.22, 0.86], [0.13, 0.88], [0.2, 1.02],
      [0.22, 1.1], [0.15, 1.1], [0.1, 1.08], [0, 1.08]],
  k: [...BASE, [0.19, 0.24], [0.13, 0.84], [0.23, 0.88], [0.23, 0.92], [0.14, 0.94], [0.21, 1.1],
      [0.2, 1.15], [0, 1.15]],
  n: [...BASE, [0.22, 0.24], [0.2, 0.32], [0, 0.32]],
};

const cache = new Map();
function latheGeometry(type) {
  if (!cache.has(type)) {
    const pts = PROFILES[type].map(([r, y]) => new THREE.Vector2(r, y));
    cache.set(type, new THREE.LatheGeometry(pts, 40));
  }
  return cache.get(type).clone();
}

function mesh(geometry, material) {
  const m = new THREE.Mesh(geometry, material);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/**
 * Build one piece.
 * @param {"p"|"n"|"b"|"r"|"q"|"k"} type
 * @param {"white"|"black"} color
 * @returns {THREE.Group} standing on y = 0, centred on x = z = 0
 */
export function buildPiece(type, color) {
  const mat = MATERIALS[color]();
  const g = new THREE.Group();
  g.add(mesh(latheGeometry(type), mat));
  const facing = color === "white" ? -1 : 1; // pieces face the opponent (-z for White)

  if (type === "n") { // horse head: neck, head, ears, mane
    const neck = mesh(new THREE.CylinderGeometry(0.13, 0.19, 0.5, 20), mat);
    neck.position.set(0, 0.55, 0.04 * -facing);
    neck.rotation.x = 0.25 * facing;
    const head = mesh(new THREE.BoxGeometry(0.2, 0.2, 0.42), mat);
    head.position.set(0, 0.8, 0.12 * facing);
    head.rotation.x = -0.45 * facing;
    const muzzle = mesh(new THREE.CylinderGeometry(0.085, 0.1, 0.16, 16), mat);
    muzzle.rotation.x = Math.PI / 2 - 0.45 * facing;
    muzzle.position.set(0, 0.7, 0.3 * facing);
    const mane = mesh(new THREE.BoxGeometry(0.06, 0.46, 0.12), mat);
    mane.position.set(0, 0.67, -0.12 * facing);
    mane.rotation.x = 0.25 * facing;
    g.add(neck, head, muzzle, mane);
    for (const x of [-0.06, 0.06]) {
      const ear = mesh(new THREE.ConeGeometry(0.04, 0.12, 8), mat);
      ear.position.set(x, 0.96, 0.0);
      g.add(ear);
    }
  }
  if (type === "r") { // battlements
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      const tooth = mesh(new THREE.BoxGeometry(0.11, 0.09, 0.07), mat);
      tooth.position.set(Math.sin(a) * 0.22, 0.82, Math.cos(a) * 0.22);
      tooth.rotation.y = a;
      g.add(tooth);
    }
  }
  if (type === "b") { // mitre slit
    const slit = mesh(new THREE.BoxGeometry(0.03, 0.12, 0.3), new THREE.MeshStandardMaterial({
      color: color === "white" ? "#9c8a6a" : "#0d0b0a" }));
    slit.position.set(0, 0.92, 0);
    slit.rotation.z = 0.5;
    g.add(slit);
  }
  if (type === "q") { // crown points and a ball
    for (let i = 0; i < 8; i++) {
      const a = (i / 8) * Math.PI * 2;
      const pt = mesh(new THREE.SphereGeometry(0.035, 10, 8), mat);
      pt.position.set(Math.sin(a) * 0.2, 1.13, Math.cos(a) * 0.2);
      g.add(pt);
    }
    const ball = mesh(new THREE.SphereGeometry(0.07, 16, 12), mat);
    ball.position.y = 1.16;
    g.add(ball);
  }
  if (type === "k") { // cross
    const v = mesh(new THREE.BoxGeometry(0.07, 0.24, 0.07), mat);
    v.position.y = 1.26;
    const h = mesh(new THREE.BoxGeometry(0.2, 0.07, 0.07), mat);
    h.position.y = 1.29;
    g.add(v, h);
  }
  return g;
}
