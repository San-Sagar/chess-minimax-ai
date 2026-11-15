// Wood textures painted in code (no image files). A wood surface is drawn pixel by
// pixel: growth rings are a sine wave across the board whose phase is bent by smooth
// noise, plus fine fibres along the grain. Each texture is made once and cached.

import * as THREE from "three";

/** Small deterministic random generator, so every visit draws the same wood. */
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 2D value noise on a wrapping grid (so textures tile without seams). */
function valueNoise(seed, cells) {
  const r = rng(seed);
  const grid = Array.from({ length: cells * cells }, r);
  const at = (x, y) => grid[((y % cells + cells) % cells) * cells + ((x % cells + cells) % cells)];
  const smooth = (t) => t * t * (3 - 2 * t);
  return (x, y) => { // x, y in grid cells
    const xi = Math.floor(x), yi = Math.floor(y);
    const tx = smooth(x - xi), ty = smooth(y - yi);
    const a = at(xi, yi), b = at(xi + 1, yi), c = at(xi, yi + 1), d = at(xi + 1, yi + 1);
    return a + (b - a) * tx + (c - a) * ty + (a - b - c + d) * tx * ty;
  };
}

const hex = (h) => new THREE.Color(h);
const cache = new Map();

/**
 * @param {string} name cache key
 * @param {{light: string, dark: string, rings?: number, seed?: number, size?: number,
 *          contrast?: number}} o
 * @returns {THREE.CanvasTexture}
 */
export function woodTexture(name, { light, dark, rings = 9, seed = 1, size = 512, contrast = 0.75 }) {
  if (cache.has(name)) return cache.get(name);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(size, size);
  const big = valueNoise(seed, 6), mid = valueNoise(seed + 7, 16), fibre = valueNoise(seed + 13, 128);
  const L = hex(light), D = hex(dark);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const u = x / size, v = y / size;
      const bend = big(u * 6, v * 6) * 2.2 + mid(u * 16, v * 16) * 0.35;
      let ring = 0.5 + 0.5 * Math.sin((v * rings + bend) * Math.PI * 2);
      ring = ring ** 2.5;
      const f = fibre(u * 8, v * 128) - 0.5; // long thin streaks along x
      const t = Math.min(1, Math.max(0, ring * contrast + f * 0.35 + (big(u * 6 + 3, v * 6) - 0.5) * 0.25));
      const i = (y * size + x) * 4;
      img.data[i] = (L.r + (D.r - L.r) * t) * 255;
      img.data[i + 1] = (L.g + (D.g - L.g) * t) * 255;
      img.data[i + 2] = (L.b + (D.b - L.b) * t) * 255;
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = 4;
  cache.set(name, tex);
  return tex;
}

export const WOODS = {
  maple: { light: "#efd9b0", dark: "#d9b88a", rings: 5, seed: 3, contrast: 0.45 },
  walnut: { light: "#7e5338", dark: "#5c3a26", rings: 6, seed: 5, contrast: 0.5 },
  frame: { light: "#6b4027", dark: "#2e180d", rings: 14, seed: 9, contrast: 0.85 },
  boxwood: { light: "#f6e7c8", dark: "#dcc296", rings: 6, seed: 11, contrast: 0.5, size: 256 },
  ebony: { light: "#3b2b22", dark: "#120c09", rings: 8, seed: 17, contrast: 0.7, size: 256 },
};

/** Small square texture with one letter or digit, for the board's edge labels. */
export function labelTexture(text, color = "#e9d3a6") {
  const key = `label:${text}:${color}`;
  if (cache.has(key)) return cache.get(key);
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const ctx = c.getContext("2d");
  ctx.fillStyle = color;
  ctx.font = "600 44px Georgia, 'Times New Roman', serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 32, 35);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  cache.set(key, tex);
  return tex;
}
