// Carved (Staunton style) chess pieces, built in code. Most of each piece is a profile
// (radius at each height) spun around the vertical axis, like wood turned on a lathe.
// The knight's head is a flat horse-head outline extruded with rounded (bevelled) edges.
// Geometries and materials are made once and shared by all pieces of the same kind.

import * as THREE from "three";
import { WOODS, woodTexture } from "./textures3d.js";

// [radius, height] points from the bottom up (1 unit = one board square)
const BASE = [[0, 0], [0.37, 0], [0.376, 0.02], [0.37, 0.05], [0.34, 0.07], [0.35, 0.09],
              [0.33, 0.11], [0.29, 0.12], [0.28, 0.15], [0.31, 0.16], [0.3, 0.18], [0.24, 0.2]];

/** Points on a ball of radius r centred at height cy, starting where its radius is rStart. */
function ball(cy, r, rStart, n = 12) {
  const a0 = Math.asin(Math.min(1, rStart / r));
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = a0 + ((Math.PI - a0) * i) / n;
    pts.push([r * Math.sin(a), cy - r * Math.cos(a)]);
  }
  return pts;
}

const PROFILES = {
  p: [...BASE, [0.17, 0.26], [0.13, 0.36], [0.115, 0.44], [0.19, 0.46], [0.2, 0.48], [0.19, 0.5],
      [0.1, 0.52], ...ball(0.64, 0.15, 0.09)],
  r: [...BASE, [0.24, 0.26], [0.2, 0.34], [0.19, 0.62], [0.22, 0.66], [0.27, 0.7], [0.27, 0.86],
      [0.21, 0.86], [0.21, 0.8], [0, 0.8]],
  b: [...BASE, [0.19, 0.26], [0.14, 0.4], [0.12, 0.62], [0.2, 0.65], [0.21, 0.68], [0.2, 0.7],
      [0.12, 0.72], [0.14, 0.75], [0.17, 0.8], [0.18, 0.86], [0.16, 0.93], [0.12, 0.99],
      [0.06, 1.04], [0.03, 1.06], ...ball(1.09, 0.04, 0.03, 8)],
  q: [...BASE, [0.2, 0.26], [0.15, 0.42], [0.12, 0.78], [0.23, 0.81], [0.24, 0.84], [0.22, 0.86],
      [0.13, 0.88], [0.15, 0.92], [0.2, 1.02], [0.24, 1.1], [0.22, 1.12], [0.14, 1.1], [0.1, 1.12],
      ...ball(1.17, 0.06, 0.05, 8)],
  k: [...BASE, [0.21, 0.26], [0.16, 0.42], [0.13, 0.84], [0.24, 0.87], [0.25, 0.9], [0.23, 0.92],
      [0.14, 0.94], [0.16, 0.98], [0.22, 1.1], [0.23, 1.15], [0.2, 1.17], [0.1, 1.19], [0.1, 1.21],
      [0, 1.21]],
  n: [...BASE, [0.24, 0.26], [0.23, 0.3], [0.27, 0.32], [0.27, 0.35], [0, 0.35]],
};

// horse head outline, x = towards the opponent, y = up (sits on top of the knight's base)
const HORSE = [[-0.2, 0], [0.19, 0], [0.17, 0.08], [0.12, 0.17], [0.14, 0.22], [0.24, 0.27],
  [0.33, 0.31], [0.36, 0.36], [0.33, 0.41], [0.25, 0.43], [0.17, 0.45], [0.13, 0.51], [0.1, 0.58],
  [0.06, 0.64], [0.05, 0.72], [0.0, 0.67], [-0.05, 0.68], [-0.09, 0.62], [-0.16, 0.55],
  [-0.21, 0.44], [-0.24, 0.3], [-0.24, 0.16], [-0.22, 0.07]];

const geometries = new Map();
const materials = new Map();

function lathe(type) {
  const pts = PROFILES[type].map(([r, y]) => new THREE.Vector2(r, y));
  return new THREE.LatheGeometry(pts, 48);
}

function horseHead() {
  const shape = new THREE.Shape();
  shape.moveTo(...HORSE[0]);
  shape.splineThru(HORSE.slice(1).map(([x, y]) => new THREE.Vector2(x, y)));
  shape.closePath();
  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: 0.17, bevelEnabled: true, bevelThickness: 0.04, bevelSize: 0.03,
    bevelSegments: 4, curveSegments: 40 });
  geo.translate(-0.05, 0.32, -0.085);
  geo.computeVertexNormals();
  return geo;
}

function geometry(key, make) {
  if (!geometries.has(key)) geometries.set(key, make());
  return geometries.get(key);
}

/** Lacquered wood: boxwood for White, ebony for Black. */
export function pieceMaterial(color) {
  if (!materials.has(color)) {
    const wood = woodTexture(color === "white" ? "boxwood" : "ebony",
                             color === "white" ? WOODS.boxwood : WOODS.ebony);
    const map = wood.clone(); // turned wood: grain runs up the piece
    map.rotation = Math.PI / 2;
    map.repeat.set(1, 2);
    map.needsUpdate = true;
    materials.set(color, new THREE.MeshPhysicalMaterial({
      map, roughness: color === "white" ? 0.42 : 0.32, metalness: 0,
      clearcoat: color === "white" ? 0.45 : 0.7, clearcoatRoughness: 0.25 }));
  }
  return materials.get(color);
}

function mesh(geo, mat) {
  const m = new THREE.Mesh(geo, mat);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

/**
 * Build one piece standing on y = 0, centred on x = z = 0, facing the opponent.
 * @param {"p"|"n"|"b"|"r"|"q"|"k"} type
 * @param {"white"|"black"} color
 */
export function buildPiece(type, color) {
  const mat = pieceMaterial(color);
  const g = new THREE.Group();
  g.add(mesh(geometry(type, () => lathe(type)), mat));

  if (type === "n") {
    const head = mesh(geometry("horse", horseHead), mat);
    head.rotation.y = color === "white" ? Math.PI / 2 : -Math.PI / 2; // +x -> towards opponent
    g.add(head);
  }
  if (type === "r") { // battlements: six teeth around the top rim
    const tooth = geometry("tooth", () => new THREE.BoxGeometry(0.1, 0.08, 0.07));
    for (let i = 0; i < 6; i++) {
      const a = ((i + 0.5) / 6) * Math.PI * 2;
      const t = mesh(tooth, mat);
      t.position.set(Math.sin(a) * 0.235, 0.9, Math.cos(a) * 0.235);
      t.rotation.y = a;
      g.add(t);
    }
  }
  if (type === "b") { // the mitre's cut
    const key = `cut-${color}`;
    if (!materials.has(key)) {
      materials.set(key, new THREE.MeshStandardMaterial({ color: color === "white" ? "#8b7552" : "#050403" }));
    }
    const cut = mesh(geometry("cut", () => new THREE.BoxGeometry(0.035, 0.13, 0.4)), materials.get(key));
    cut.position.set(0, 0.93, 0);
    cut.rotation.z = 0.55;
    g.add(cut);
  }
  if (type === "q") { // crown points
    const pt = geometry("crownpt", () => new THREE.SphereGeometry(0.032, 12, 8));
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2;
      const m = mesh(pt, mat);
      m.position.set(Math.sin(a) * 0.225, 1.125, Math.cos(a) * 0.225);
      g.add(m);
    }
  }
  if (type === "k") { // cross
    const v = mesh(geometry("crossv", () => new THREE.BoxGeometry(0.07, 0.26, 0.07)), mat);
    v.position.y = 1.33;
    const h = mesh(geometry("crossh", () => new THREE.BoxGeometry(0.2, 0.07, 0.07)), mat);
    h.position.y = 1.36;
    if (color === "black") { v.rotation.y = h.rotation.y = Math.PI; }
    g.add(v, h);
  }
  g.userData.type = type;
  return g;
}
