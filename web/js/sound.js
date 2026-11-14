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

/** kind: "move" | "capture" | "check" | "end" */
export function play(kind) {
  if (!enabled) return;
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    if (kind === "move") tone(520, 0, 0.07, "triangle", 0.15);
    else if (kind === "capture") { tone(330, 0, 0.08, "square", 0.08); tone(250, 0.05, 0.1, "triangle", 0.12); }
    else if (kind === "check") { tone(660, 0, 0.08, "triangle", 0.14); tone(880, 0.08, 0.12, "triangle", 0.12); }
    else if (kind === "end") { tone(392, 0, 0.35); tone(494, 0.08, 0.35); tone(587, 0.16, 0.5); }
  } catch { /* audio not available */ }
}
