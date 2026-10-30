// Shared UI pieces: icons, sheets, toasts, small inputs, hooks, date helpers.

import { html, useEffect, useRef, useState, useCallback } from '../vendor/preact-htm.js';
import { label as unitLabel } from './units.js';

export const store = { boot: null };

// ------------------------------------------------------------------ icons (24px stroke icons)

const PATHS = {
  week: 'M4 5h16v15H4zM4 9h16M9 3v4M15 3v4',
  cart: 'M3 4h2l2.4 11h10.2L20 8H6.2M9 20a1 1 0 1 0 0-.01M17 20a1 1 0 1 0 0-.01',
  pantry: 'M5 3h14v18H5zM5 9h14M5 15h14M10 6h4M10 12h4M10 18h4',
  book: 'M5 4h9a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4zM5 16a4 4 0 0 1 4-4h9',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  plus: 'M12 5v14M5 12h14',
  check: 'M5 12.5l4.5 4.5L19 7',
  left: 'M15 5l-7 7 7 7',
  right: 'M9 5l7 7-7 7',
  close: 'M6 6l12 12M18 6L6 18',
  play: 'M8 5v14l11-7z',
  pause: 'M8 5v14M16 5v14',
  timer: 'M12 8v5l3 2M9 2h6M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  star: 'M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.8z',
  move: 'M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  edit: 'M4 20h4L19 9l-4-4L4 16zM14 6l4 4',
  fridge: 'M6 2h12v20H6zM6 10h12M9 5v2M9 13v3',
  freezer: 'M12 2v20M4.5 6.5l15 11M19.5 6.5l-15 11M9 3.5l3 2.5 3-2.5M9 20.5l3-2.5 3 2.5',
  cupboard: 'M4 3h16v18H4zM12 3v18M9.5 11v2M14.5 11v2',
  alert: 'M12 9v4M12 17h.01M10.3 3.9L2.4 17.6A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-2.9L13.7 3.9a2 2 0 0 0-3.4 0z',
  swap: 'M7 4L3 8l4 4M3 8h14M17 20l4-4-4-4M21 16H7',
  bag: 'M5 8h14l-1 13H6zM9 8V6a3 3 0 0 1 6 0v2',
  scale: 'M12 3v3M5 21h14l-2-12H7zM9 6h6M12 13l2-2',
  chat: 'M4 5h16v11H9l-5 4z',
  minus: 'M5 12h14',
  undo: 'M9 14L4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3',
};

export function Icon({ name, size = 22, fill = false, cls = '' }) {
  return html`<svg class=${'icon ' + cls} width=${size} height=${size} viewBox="0 0 24 24" aria-hidden="true"
    fill=${fill ? 'currentColor' : 'none'} stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
    stroke-linejoin="round"><path d=${PATHS[name] || ''} /></svg>`;
}

// ------------------------------------------------------------------ toasts

const toastListeners = new Set();
export function toast(text, kind = 'info', action = null) {
  toastListeners.forEach((fn) => fn({ text, kind, action, id: Math.random() }));
}
export function Toasts() {
  const [items, setItems] = useState([]);
  useEffect(() => {
    const fn = (t) => {
      setItems((xs) => [...xs, t]);
      setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.action ? 6000 : 3500);
    };
    toastListeners.add(fn);
    return () => toastListeners.delete(fn);
  }, []);
  return html`<div class="toasts" role="status" aria-live="polite">
    ${items.map((t) => html`<div class=${'toast ' + t.kind} key=${t.id}>
      <span>${t.text}</span>
      ${t.action && html`<button class="link" onClick=${() => { t.action.run(); setItems((xs) => xs.filter((x) => x.id !== t.id)); }}>${t.action.label}</button>`}
    </div>`)}
  </div>`;
}

export function errorToast(e) { toast(e.message || String(e), 'error'); }

// ------------------------------------------------------------------ bottom sheet

export function Sheet({ open, onClose, title, children, wide = false }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('no-scroll');
    setTimeout(() => {
      const el = ref.current && ref.current.querySelector('[autofocus], input, select, textarea, button');
      if (el) el.focus({ preventScroll: true });
    }, 50);
    return () => { document.removeEventListener('keydown', onKey); document.body.classList.remove('no-scroll'); };
  }, [open]);
  if (!open) return null;
  return html`<div class="sheet-backdrop" onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <div class=${'sheet' + (wide ? ' wide' : '')} role="dialog" aria-modal="true" aria-label=${title} ref=${ref}>
      <div class="sheet-head">
        <h2>${title}</h2>
        <button class="icon-btn" onClick=${onClose} aria-label="Close"><${Icon} name="close" /></button>
      </div>
      <div class="sheet-body">${children}</div>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ small inputs

export function Stars({ value, onChange, size = 30 }) {
  return html`<div class="stars" role="radiogroup" aria-label="Rating">
    ${[1, 2, 3, 4, 5].map((n) => html`<button type="button" role="radio" aria-checked=${value === n}
      aria-label=${n + ' star' + (n > 1 ? 's' : '')} class=${'star' + (value >= n ? ' on' : '')}
      onClick=${() => onChange(n)}><${Icon} name="star" size=${size} fill=${value >= n} /></button>`)}
  </div>`;
}

export function Segmented({ options, value, onChange, small = false }) {
  return html`<div class=${'segmented' + (small ? ' small' : '')} role="tablist">
    ${options.map(([v, lbl]) => html`<button type="button" role="tab" aria-selected=${value === v}
      class=${value === v ? 'on' : ''} onClick=${() => onChange(v)}>${lbl}</button>`)}
  </div>`;
}

export const UNIT_CHOICES = ['g', 'kg', 'ml', 'l', 'pc', 'pack', 'can', 'jar', 'bottle', 'bag', 'bunch', 'slice',
  'clove', 'tsp', 'tbsp', 'cup', 'oz', 'lb'];

export function UnitSelect({ value, onChange, id }) {
  const v = value || 'pc';
  const choices = UNIT_CHOICES.includes(v) ? UNIT_CHOICES : [v, ...UNIT_CHOICES];
  return html`<select id=${id} value=${v} onChange=${(e) => onChange(e.target.value)}>
    ${choices.map((u) => html`<option value=${u}>${u === 'pc' ? 'pieces' : unitLabel(u)}</option>`)}
  </select>`;
}

/** Quantity + unit editor with quick steppers. */
export function QtyInput({ quantity, unit, onChange }) {
  const q = quantity ?? '';
  const step = (d) => {
    const n = Number(q) || 0;
    const inc = ['g', 'ml'].includes(unit) ? (n >= 500 ? 100 : 50) : ['kg', 'l'].includes(unit) ? 0.25 : 1;
    onChange({ quantity: Math.max(0, Math.round((n + d * inc) * 100) / 100), unit });
  };
  return html`<div class="qty-input">
    <button type="button" class="icon-btn boxed" aria-label="Less" onClick=${() => step(-1)}><${Icon} name="minus" /></button>
    <input type="number" inputmode="decimal" step="any" min="0" value=${q} aria-label="Amount"
      onInput=${(e) => onChange({ quantity: e.target.value === '' ? null : Number(e.target.value), unit })} />
    <button type="button" class="icon-btn boxed" aria-label="More" onClick=${() => step(1)}><${Icon} name="plus" /></button>
    <${UnitSelect} value=${unit} onChange=${(u) => onChange({ quantity, unit: u })} />
  </div>`;
}

export function Field({ label, children, hint }) {
  return html`<label class="field"><span>${label}</span>${children}${hint && html`<small class="muted">${hint}</small>`}</label>`;
}

export function Empty({ title, children }) {
  return html`<div class="empty"><p class="empty-title">${title}</p>${children && html`<div class="muted">${children}</div>`}</div>`;
}

// ------------------------------------------------------------------ hooks

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const run = useCallback(async (quiet = false) => {
    if (!quiet) setState((s) => ({ ...s, loading: true }));
    try {
      const data = await fn();
      setState({ data, error: null, loading: false });
      return data;
    } catch (e) {
      setState((s) => ({ ...s, error: e, loading: false }));
    }
  }, deps);
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run, setData: (d) => setState((s) => ({ ...s, data: typeof d === 'function' ? d(s.data) : d })) };
}

// ------------------------------------------------------------------ dates

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function parseISO(s) { const [y, m, d] = s.slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); }
export function iso(d) { return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
export function addDays(s, n) { const d = parseISO(s); d.setDate(d.getDate() + n); return iso(d); }
export function todayISO() { return iso(new Date()); }
export function fmtDay(s) { const d = parseISO(s); return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`; }
export function fmtShort(s) { const d = parseISO(s); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; }
export function weekday(s) { return DAYS[parseISO(s).getDay()]; }
export function daysBetween(a, b) { return Math.round((parseISO(b) - parseISO(a)) / 86400000); }

export function expiryText(expires) {
  if (!expires) return { text: 'No expiry date', cls: 'none' };
  const n = daysBetween(todayISO(), expires);
  if (n < 0) return { text: `Expired ${-n === 1 ? 'yesterday' : -n + ' days ago'}`, cls: 'expired' };
  if (n === 0) return { text: 'Use today', cls: 'urgent' };
  if (n === 1) return { text: 'Use by tomorrow', cls: 'urgent' };
  if (n <= 4) return { text: `${n} days left`, cls: 'soon' };
  if (n <= 60) return { text: `${n} days left`, cls: 'ok' };
  return { text: `Until ${fmtShort(expires)}${parseISO(expires).getFullYear() !== new Date().getFullYear() ? ' ' + parseISO(expires).getFullYear() : ''}`, cls: 'ok' };
}

export const LOCATION_LABEL = { fridge: 'Fridge', freezer: 'Freezer', pantry: 'Cupboard' };
export const LOCATION_ICON = { fridge: 'fridge', freezer: 'freezer', pantry: 'cupboard' };
export const SLOT_LABEL = { breakfast: 'Breakfast', lunch: 'Lunch', dinner: 'Dinner', snack: 'Snack' };
