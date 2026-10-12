"use strict";

// Breeze phone remote. Talks to the Breeze helper on the Mac; the Mac talks to the air conditioner.

const TOKEN_KEY = "breeze-token";
const RECONNECT_MS = 1500;
const TOAST_MS = 4000;

const MODES = { auto: "Auto", cool: "Cool", dry: "Dry", heat: "Heat", fan: "Fan" };
const FANS = { auto: "Auto", silent: "Silent", low: "Low", medium: "Medium", high: "High", max: "Max" };
const PHASES = { working: "Cooling", holding: "Room at temperature, resting", fan: "Fan only" };
const STATUS_TEXT = {
  online: "Connected", offline: "AC not reachable", connecting: "Connecting to the AC",
  unlinked: "Link the AC on the Mac first",
};

const $ = (id) => document.getElementById(id);
let socket = null;
let retryTimer = 0;
let toastTimer = 0;
let state = { status: "connecting" };
let lastNotice;  // the notice id last seen; undefined until the first state arrives

// ------------------------------------------------------------ pairing token

function readToken() {
  // The QR code puts the token in the address as ?t=. It stays there, because Home Screen apps
  // keep separate storage; storage is only a backup.
  const fromAddress = new URLSearchParams(location.search).get("t");
  let stored = null;
  try { stored = localStorage.getItem(TOKEN_KEY); } catch { /* storage blocked */ }
  const found = fromAddress || stored;
  if (!found) return null;
  try { localStorage.setItem(TOKEN_KEY, found); } catch { /* fine, the address has it */ }
  if (fromAddress !== found) history.replaceState(null, "", `/?t=${encodeURIComponent(found)}`);
  document.querySelector('link[rel="manifest"]').href = `/manifest.webmanifest?t=${encodeURIComponent(found)}`;
  return found;
}
const token = readToken();

function showGate() {
  $("remote").hidden = true;
  $("gate").hidden = false;
}

function forgetToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* nothing stored */ }
  history.replaceState(null, "", "/");
  showGate();
}

// ------------------------------------------------------------ connection

function connect() {
  clearTimeout(retryTimer);
  if (!token) { showGate(); return; }
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) return;
  const ws = new WebSocket(`ws://${location.host}/ws?t=${encodeURIComponent(token)}`);
  socket = ws;
  ws.addEventListener("message", (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message.type === "ac") render(message);
    else if (message.type === "error") toast(message.message);
  });
  ws.addEventListener("close", async () => {
    if (socket !== ws) return;  // an older socket closing after a newer one opened
    socket = null;
    $("status").textContent = "Mac not reachable, retrying";
    $("dot").className = "dot off";
    // A refused code means the Mac forgot this phone: ask for a new scan instead of retrying forever.
    try {
      const check = await fetch(`/check?t=${encodeURIComponent(token)}`, { cache: "no-store" });
      if (check.status === 403) { forgetToken(); return; }
    } catch { /* the Mac is asleep or off the Wi-Fi: keep trying */ }
    retryTimer = setTimeout(connect, RECONNECT_MS);
  });
}

function send(payload) {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  else toast("Not connected to the Mac yet.");
}

const set = (changes) => send({ type: "ac_set", changes });

// ------------------------------------------------------------ drawing

function fillSelect(select, names, labels, current) {
  const wanted = names.map((name) => `${name}:${labels[name] || name}`).join("|");
  if (select.dataset.names !== wanted) {
    select.replaceChildren(...names.map((name) => new Option(labels[name] || name, name)));
    select.dataset.names = wanted;
  }
  const shown = current ?? "";
  if (select.value !== shown) select.value = shown;  // untouched while it already shows it
}

function duration(minutes) {
  if (minutes < 60) return `${minutes} min`;
  return minutes % 60 === 0 ? `${minutes / 60} h` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function render(next) {
  state = next;
  const online = next.status === "online";
  $("status").textContent = STATUS_TEXT[next.status] || "Connecting";
  $("dot").className = online ? "dot on" : "dot off";
  const room = [];
  if (typeof next.indoor === "number") room.push(`Room ${Math.round(next.indoor)}°`);
  if (typeof next.outdoor === "number") room.push(`Outside ${Math.round(next.outdoor)}°`);
  $("room").textContent = room.join("  ·  ") || " ";

  $("target").textContent = typeof next.target === "number" ? Math.round(next.target) : "--";
  $("doing").textContent = !online ? " " : next.cleaning ? "Cleaning itself. Power stops it."
    : !next.power ? "Off" : PHASES[next.phase] || " ";
  const canSet = online && next.power && !next.cleaning && next.mode !== "fan";
  $("cooler").disabled = !canSet || next.target <= next.min;
  $("warmer").disabled = !canSet || next.target >= next.max;

  $("power").classList.toggle("on", online && !!next.power);
  $("power-label").textContent = next.power ? "Switch Off" : "Switch On";

  fillSelect($("mode"), next.modes || [], MODES, next.mode);
  fillSelect($("fan"), next.fans || [], FANS, next.fan);
  const timer = $("timer");
  const choices = next.timer_choices || [];
  const timerNames = ["", ...choices.map(String), ...(next.off_in ? ["cancel"] : [])];
  // The first option's text counts down; only that text changes, so an open picker stays open.
  const timerLabels = { "": next.off_in ? "On" : "Off", cancel: "Cancel Timer" };
  for (const minutes of choices) timerLabels[String(minutes)] = `Off in ${duration(minutes)}`;
  fillSelect(timer, timerNames, timerLabels, "");
  timer.options[0].textContent = next.off_in ? `Off in ${duration(next.off_in)}` : "Off";

  for (const [id, shown] of [["eco", next.has_eco], ["turbo", next.has_turbo], ["sleep", true]]) {
    const tile = $(id);
    tile.hidden = !shown;
    tile.classList.toggle("on", !!next[id]);
    tile.querySelector(".value").textContent = next[id] ? "On" : "Off";
  }
  for (const tile of document.querySelectorAll(".tile")) {
    tile.classList.toggle("disabled", !online || !next.power || !!next.cleaning);
  }
  if (next.notice_id !== lastNotice) {
    if (lastNotice !== undefined && next.notice) toast(next.notice);
    lastNotice = next.notice_id;
  }
}

function toast(text) {
  $("toast").textContent = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").textContent = ""; }, TOAST_MS);
}

// ------------------------------------------------------------ controls

function nudge(step) {
  if (typeof state.target !== "number") return;
  const next = Math.min(Math.max(Math.round(state.target) + step, state.min), state.max);
  if (next !== state.target) {
    state = { ...state, target: next };
    $("target").textContent = next;  // at once; the Mac confirms
    set({ target: next });
  }
}

$("cooler").addEventListener("click", () => nudge(-1));
$("warmer").addEventListener("click", () => nudge(1));
$("power").addEventListener("click", () => set({ power: !state.power }));
$("mode").addEventListener("change", (event) => set({ mode: event.target.value }));
$("fan").addEventListener("change", (event) => set({ fan: event.target.value }));
$("timer").addEventListener("change", (event) => {
  const value = event.target.value;
  if (value === "cancel") send({ type: "ac_timer", minutes: null });
  else if (Number(value)) send({ type: "ac_timer", minutes: Number(value) });
});
for (const id of ["eco", "turbo", "sleep"]) {
  $(id).addEventListener("click", () => set({ [id]: !state[id] }));
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  // After the phone slept, an "open" socket may be dead: start a fresh one rather than trust it.
  const old = socket;
  socket = null;
  if (old) old.close();
  connect();
});

connect();
