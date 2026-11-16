// Battle view: the 3D board turned into a battlefield at dusk, with the pieces as
// soldiers (units3d.js). It reuses all of Board3D's game logic (moves, input, intro)
// and only replaces the scenery, the piece models and the idle animation.

import * as THREE from "three";
import { Board3D } from "./board3d.js";
import { ARMIES, buildUnit, glowSprite } from "./units3d.js";
import { noiseTexture, skyTexture } from "./textures3d.js";

const GROUND_Y = -0.42;

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
  }

  _home() {
    return { angle: this.orientation === "white" ? 0 : Math.PI, dist: 10.6, height: 11.0 };
  }

  _createPiece(type, color) {
    return buildUnit(type, color);
  }

  // ------------------------------------------------------------ scenery

  _buildLights() {
    this.scene.add(new THREE.HemisphereLight("#ffe2bd", "#3a2c1f", 1.15));
    const sun = new THREE.DirectionalLight("#ffd3a0", 3.0); // low evening sun
    sun.position.set(7, 8, 3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
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
    for (const [sq, unit] of this.meshes) if (sq >= 0) unit.userData.idle?.(t);
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
