// Cooking timers: survive page reloads (end times are stored), ring with sound +
// vibration + notification, and keep the screen awake while any timer runs.

import { useEffect, useState } from '../vendor/preact-htm.js';

const KEY = 'mp_timers_v1';
let timers = load();
const listeners = new Set();
let audioCtx = null;
let ringing = null;
let wakeLock = null;

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(timers)); } catch { /* private mode */ }
}
function emit() { save(); listeners.forEach((fn) => fn([...timers])); syncWakeLock(); }

export function remaining(t, now = Date.now()) {
  if (t.state === 'running') return Math.max(0, Math.round((t.endsAt - now) / 1000));
  if (t.state === 'paused') return t.left;
  return 0;
}

export function fmt(secs) {
  secs = Math.max(0, Math.round(secs));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60), s = secs % 60;
  const mm = h ? String(m).padStart(2, '0') : String(m);
  return (h ? h + ':' : '') + mm + ':' + String(s).padStart(2, '0');
}

export function findByKey(key) { return timers.find((t) => t.key === key); }

export function startTimer({ key, label, seconds, recipeId, recipeTitle }) {
  unlockAudio();
  askNotificationPermission();
  const existing = key && timers.find((t) => t.key === key);
  if (existing) {
    if (existing.state === 'paused') resume(existing.id);
    else if (existing.state === 'done') { restart(existing.id); }
    return existing.id;
  }
  const t = {
    id: Math.random().toString(36).slice(2), key, label, recipeId, recipeTitle,
    total: seconds, endsAt: Date.now() + seconds * 1000, state: 'running',
  };
  timers.push(t);
  emit();
  return t.id;
}

export function pause(id) {
  const t = timers.find((x) => x.id === id);
  if (t && t.state === 'running') { t.left = remaining(t); t.state = 'paused'; emit(); }
}
export function resume(id) {
  unlockAudio();
  const t = timers.find((x) => x.id === id);
  if (t && t.state === 'paused') { t.endsAt = Date.now() + t.left * 1000; t.state = 'running'; emit(); }
}
export function restart(id) {
  const t = timers.find((x) => x.id === id);
  if (t) { t.endsAt = Date.now() + t.total * 1000; t.state = 'running'; delete t.left; stopRinging(); emit(); }
}
export function addTime(id, secs) {
  const t = timers.find((x) => x.id === id);
  if (!t) return;
  if (t.state === 'running') t.endsAt += secs * 1000;
  else if (t.state === 'paused') t.left += secs;
  else { t.endsAt = Date.now() + secs * 1000; t.state = 'running'; }
  stopRingingIfNoneDone();
  emit();
}
export function remove(id) {
  timers = timers.filter((x) => x.id !== id);
  stopRingingIfNoneDone();
  emit();
}

export function useTimers() {
  const [list, setList] = useState(timers);
  const [, setTick] = useState(0);
  useEffect(() => {
    listeners.add(setList);
    const iv = setInterval(() => setTick((n) => n + 1), 500);
    return () => { listeners.delete(setList); clearInterval(iv); };
  }, []);
  return list;
}

// ------------------------------------------------------------------ ringing

function check() {
  let changed = false;
  for (const t of timers) {
    if (t.state === 'running' && Date.now() >= t.endsAt) {
      t.state = 'done';
      changed = true;
      notify(t);
    }
  }
  if (changed) { emit(); startRinging(); }
}
setInterval(check, 500);
document.addEventListener('visibilitychange', () => { check(); syncWakeLock(); });

function unlockAudio() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
  } catch { /* no audio */ }
}

function beep() {
  if (!audioCtx) return;
  const t0 = audioCtx.currentTime;
  [0, 0.22, 0.44].forEach((off) => {
    const o = audioCtx.createOscillator();
    const g = audioCtx.createGain();
    o.type = 'square';
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, t0 + off);
    g.gain.exponentialRampToValueAtTime(0.25, t0 + off + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + off + 0.18);
    o.connect(g).connect(audioCtx.destination);
    o.start(t0 + off);
    o.stop(t0 + off + 0.2);
  });
}

function startRinging() {
  if (ringing) return;
  const ring = () => {
    beep();
    if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
  };
  ring();
  ringing = setInterval(ring, 1600);
  // stop automatically after 2 minutes so it never rings forever
  setTimeout(stopRinging, 120000);
}
export function stopRinging() {
  if (ringing) { clearInterval(ringing); ringing = null; }
  if (navigator.vibrate) navigator.vibrate(0);
}
function stopRingingIfNoneDone() {
  if (!timers.some((t) => t.state === 'done')) stopRinging();
}

function askNotificationPermission() {
  try {
    if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
  } catch { /* unsupported */ }
}

async function notify(t) {
  try {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    const title = `${t.label} — time's up`;
    const opts = { body: t.recipeTitle || 'Timer finished', tag: 'timer-' + t.id, renotify: true,
      vibrate: [300, 150, 300, 150, 300], requireInteraction: true, icon: '/static/icons/icon-192.png' };
    const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
    if (reg) reg.showNotification(title, opts); else new Notification(title, opts);
  } catch { /* ignore */ }
}

async function syncWakeLock() {
  const needed = timers.some((t) => t.state === 'running') && document.visibilityState === 'visible';
  try {
    if (needed && !wakeLock && 'wakeLock' in navigator) {
      wakeLock = await navigator.wakeLock.request('screen');
      wakeLock.addEventListener('release', () => { wakeLock = null; });
    } else if (!needed && wakeLock) {
      await wakeLock.release();
      wakeLock = null;
    }
  } catch { wakeLock = null; }
}
