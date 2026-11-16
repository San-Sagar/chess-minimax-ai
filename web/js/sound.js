// Move sounds made with the Web Audio API (no sound files).

let ctx = null;
let enabled = true;

try { enabled = localStorage.getItem("sound") !== "off"; } catch { /* storage blocked */ }

export function soundEnabled() { return enabled; }

export function toggleSound() {
  enabled = !enabled;
  try { localStorage.setItem("sound", enabled ? "on" : "off"); } catch { /* ignore */ }
  return enabled;
}

function tone(freq, start, dur, type = "sine", gain = 0.12) {
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + start);
  osc.stop(ctx.currentTime + start + dur + 0.02);
}

/** A tone whose pitch slides from ``f0`` to ``f1``. */
function sweep(f0, f1, start, dur, type = "sawtooth", gain = 0.08) {
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  const t = ctx.currentTime + start;
  osc.type = type;
  osc.frequency.setValueAtTime(f0, t);
  osc.frequency.exponentialRampToValueAtTime(f1, t + dur);
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

let noiseBuffer = null;
/** Filtered white noise (whooshes, impacts, crackle); the filter slides from ``f0`` to ``f1``. */
function noise(start, dur, { gain = 0.2, filter = "bandpass", f0 = 2000, f1 = 600, q = 1 } = {}) {
  if (!noiseBuffer) {
    noiseBuffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const d = noiseBuffer.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  const bq = ctx.createBiquadFilter();
  bq.type = filter;
  bq.Q.value = q;
  const g = ctx.createGain();
  const t = ctx.currentTime + start;
  bq.frequency.setValueAtTime(f0, t);
  bq.frequency.exponentialRampToValueAtTime(f1, t + dur);
  g.gain.setValueAtTime(0, t);
  g.gain.linearRampToValueAtTime(gain, t + Math.min(0.03, dur / 4));
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(bq).connect(g).connect(ctx.destination);
  src.start(t);
  src.stop(t + dur + 0.02);
}

const SOUNDS = {
  move: () => tone(520, 0, 0.07, "triangle", 0.15),
  capture: () => { tone(330, 0, 0.08, "square", 0.08); tone(250, 0.05, 0.1, "triangle", 0.12); },
  check: () => { tone(660, 0, 0.08, "triangle", 0.14); tone(880, 0.08, 0.12, "triangle", 0.12); },
  end: () => { tone(392, 0, 0.35); tone(494, 0.08, 0.35); tone(587, 0.16, 0.5); },
  // ---- battle mode
  step: () => noise(0, 0.08, { gain: 0.08, filter: "lowpass", f0: 400, f1: 150 }),
  gallop: () => { for (let i = 0; i < 3; i++) noise(i * 0.09, 0.07, { gain: 0.1, filter: "lowpass", f0: 500, f1: 160 }); },
  stab: () => { tone(1250, 0, 0.12, "square", 0.04); tone(1900, 0.01, 0.1, "triangle", 0.05);
                noise(0, 0.12, { gain: 0.15, f0: 4000, f1: 1500, q: 2 }); },
  arrow: () => noise(0, 0.35, { gain: 0.16, f0: 3000, f1: 700, q: 3 }),
  javelin: () => { noise(0, 0.4, { gain: 0.14, f0: 1600, f1: 400, q: 2 }); sweep(900, 300, 0, 0.4, "sine", 0.05); },
  hit: () => { noise(0, 0.15, { gain: 0.2, filter: "lowpass", f0: 900, f1: 200 }); tone(140, 0, 0.15, "triangle", 0.1); },
  zap: () => { sweep(1800, 120, 0, 0.45, "sawtooth", 0.07);
               noise(0, 0.5, { gain: 0.18, filter: "highpass", f0: 2500, f1: 5000, q: 0.7 }); },
  boom: () => { sweep(120, 40, 0, 0.7, "sine", 0.3); noise(0, 0.6, { gain: 0.25, filter: "lowpass", f0: 600, f1: 80 }); },
  fall: () => { sweep(180, 60, 0, 0.3, "triangle", 0.12); noise(0.05, 0.2, { gain: 0.1, filter: "lowpass", f0: 500, f1: 120 }); },
  charge: () => { sweep(220, 330, 0, 0.5, "sawtooth", 0.05); sweep(330, 440, 0.15, 0.45, "sawtooth", 0.04); },
  promote: () => { [523, 659, 784, 1047].forEach((f, i) => tone(f, i * 0.08, 0.3, "triangle", 0.1)); },
  march: () => { for (let i = 0; i < 6; i++) tone(i % 2 ? 110 : 82, i * 0.32, 0.18, "triangle", 0.18); },
  kneel: () => { tone(294, 0, 0.6, "sine", 0.1); tone(220, 0.25, 0.9, "sine", 0.1); },
};

/** kind: "move" | "capture" | "check" | "end", or a battle sound (see SOUNDS). */
export function play(kind) {
  if (!enabled || !SOUNDS[kind]) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    SOUNDS[kind]();
  } catch { /* audio not available */ }
}
