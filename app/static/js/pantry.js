// Pantry: what's at home, how much is left, where it is and when it expires.

import { html, useState } from '../vendor/preact-htm.js';
import { api } from './api.js';
import { format } from './units.js';
import {
  Icon, Sheet, Segmented, Field, QtyInput, Empty, useAsync, toast, errorToast, store,
  expiryText, fmtShort, LOCATION_LABEL, LOCATION_ICON,
} from './ui.js';

export function PantryView() {
  const { data, error, reload } = useAsync(() => api.get('/pantry'), []);
  const [loc, setLoc] = useState('all');
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);

  if (error) return html`<section class="view"><${Empty} title="Couldn't load the pantry">${error.message}</${Empty}></section>`;
  if (!data) return html`<section class="view"><p class="muted pad">Loading…</p></section>`;

  const soon = data.filter((p) => p.days_left != null && p.days_left <= 4);
  const shown = data.filter((p) => loc === 'all' || p.location === loc);
  const count = (l) => data.filter((p) => p.location === l).length;

  return html`<section class="view pantry">
    <header class="page-head">
      <div><h1>Pantry</h1><p class="muted">${data.length} thing${data.length === 1 ? '' : 's'} at home</p></div>
      <div class="head-actions"><button class="btn small" onClick=${() => setAdding(true)}><${Icon} name="plus" size=${18} /> Add</button></div>
    </header>

    ${soon.length > 0 && html`<div class="use-soon">
      <h2>Use soon</h2>
      <ul>${soon.map((p) => { const ex = expiryText(p.expires_at); return html`<li key=${p.id}>
        <button onClick=${() => setEditing(p)}><span>${p.name}</span><span class=${'exp ' + ex.cls}>${ex.text}</span></button></li>`; })}</ul>
    </div>`}

    <div class="filters"><${Segmented} small=${true} value=${loc} onChange=${setLoc}
      options=${[['all', 'All'], ['fridge', `Fridge ${count('fridge')}`], ['freezer', `Freezer ${count('freezer')}`], ['pantry', `Cupboard ${count('pantry')}`]]} /></div>

    ${shown.length === 0 && html`<${Empty} title=${loc === 'all' ? 'Nothing logged yet' : 'Nothing in the ' + LOCATION_LABEL[loc].toLowerCase()}>
      Items appear here when you finish shopping. You can also add things you already have.</${Empty}>`}

    <ul class="pantry-list">${shown.map((p) => html`<${PantryRow} p=${p} key=${p.id} onTap=${() => setEditing(p)} showLoc=${loc === 'all'} />`)}</ul>

    ${editing && html`<${PantrySheet} p=${editing} close=${() => setEditing(null)} reload=${() => reload(true)} />`}
    ${adding && html`<${AddPantrySheet} close=${() => setAdding(false)} reload=${() => reload(true)} />`}
  </section>`;
}

function PantryRow({ p, onTap, showLoc }) {
  const ex = expiryText(p.expires_at);
  const frac = p.quantity != null && p.initial_quantity ? Math.max(0, Math.min(1, p.quantity / p.initial_quantity)) : null;
  return html`<li><button class="pantry-row" onClick=${onTap}>
    ${showLoc && html`<span class="loc-icon" title=${LOCATION_LABEL[p.location]}><${Icon} name=${LOCATION_ICON[p.location]} size=${20} /></span>`}
    <span class="pr-main">
      <span class="pr-name">${p.name}${p.low && html` <span class="tag warn">Running low</span>`}${p.opened_at && html` <span class="tag">Opened</span>`}</span>
      <span class="pr-qty muted">${p.quantity != null ? format(p.quantity, p.unit) + (p.initial_quantity && p.initial_quantity !== p.quantity ? ' left of ' + format(p.initial_quantity, p.unit) : '') : 'Some'}</span>
      ${frac != null && frac < 1 && html`<span class="bar" aria-hidden="true"><span style=${{ width: frac * 100 + '%' }}></span></span>`}
    </span>
    <span class=${'exp ' + ex.cls}>${ex.text}</span>
  </button></li>`;
}

function PantrySheet({ p, close, reload }) {
  const [qty, setQty] = useState({ quantity: p.quantity, unit: p.unit || 'pc' });
  const [exp, setExp] = useState(p.expires_at || '');
  const [note, setNote] = useState(p.note || '');
  const ex = expiryText(p.expires_at);
  const patch = async (body, msg, keepOpen = false) => {
    try { await api.patch('/pantry/' + p.id, body); if (!keepOpen) close(); reload(); if (msg) toast(msg); }
    catch (e) { errorToast(e); }
  };
  const used = (f) => {
    if (p.quantity == null) return patch({ status: 'used' }, `${p.name} used up`);
    const q = Math.round((p.quantity - (p.initial_quantity || p.quantity) * f) * 100) / 100;
    return patch({ quantity: Math.max(0, q) }, q <= 0 ? `${p.name} used up` : `${format(Math.max(0, q), p.unit)} of ${p.name} left`);
  };
  const restock = async () => {
    try { await api.post(`/pantry/${p.id}/restock`); close(); reload(); toast(`${p.name} added to the shopping list`); }
    catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${p.name}>
    <p class="muted sheet-sub">${LOCATION_LABEL[p.location]}${p.purchased_at ? ' · bought ' + fmtShort(p.purchased_at) : ''} · <span class=${'exp ' + ex.cls}>${ex.text}</span></p>
    ${p.storage_advice && html`<p class="advice">${p.storage_advice}</p>`}
    <${Field} label="How much is left?">
      <${QtyInput} quantity=${qty.quantity} unit=${qty.unit} onChange=${setQty} />
    </${Field}>
    <div class="chip-row">
      <button class="chip" onClick=${() => used(0.25)}>Used ¼</button>
      <button class="chip" onClick=${() => used(0.5)}>Used ½</button>
      <button class="chip" onClick=${() => used(1)}>Used it all</button>
      ${!p.opened_at && html`<button class="chip" onClick=${() => patch({ opened: true }, 'Marked as opened — expiry updated', true)}>Just opened it</button>`}
    </div>
    <${Field} label="Where is it?"><${Segmented} small=${true} value=${p.location}
      onChange=${(l) => patch({ location: l }, `Moved to the ${LOCATION_LABEL[l].toLowerCase()} — new expiry date set`, true)}
      options=${[['fridge', 'Fridge'], ['freezer', 'Freezer'], ['pantry', 'Cupboard']]} /></${Field}>
    <${Field} label="Use by"><input type="date" value=${exp} onInput=${(e) => setExp(e.target.value)} /></${Field}>
    <${Field} label="Note"><input value=${note} onInput=${(e) => setNote(e.target.value)} placeholder="e.g. 2 portions, cooked chili" /></${Field}>
    <div class="row-actions">
      <button class="btn primary" onClick=${() => patch({ quantity: qty.quantity, unit: qty.unit, expires_at: exp || null, note: note || null }, 'Saved')}>Save</button>
    </div>
    <div class="action-list compact">
      <button class="action" onClick=${restock}><${Icon} name="cart" /><span>Running low — add to shopping list</span></button>
      <button class="action" onClick=${() => patch({ status: 'discarded' }, `${p.name} thrown away`)}><${Icon} name="trash" /><span>Threw it away</span></button>
      <button class="action danger" onClick=${async () => { if (!confirm('Delete this entry? Use this for mistakes.')) return; try { await api.del('/pantry/' + p.id); close(); reload(); } catch (e) { errorToast(e); } }}>
        <${Icon} name="close" /><span>Delete entry</span></button>
    </div>
  </${Sheet}>`;
}

function AddPantrySheet({ close, reload }) {
  const cats = (store.boot && store.boot.categories) || [];
  const [v, setV] = useState({ name: '', quantity: null, unit: 'g', location: '', category: '', expires_at: '', note: '' });
  const set = (k) => (x) => setV({ ...v, [k]: x });
  const save = async (e) => {
    e.preventDefault();
    if (!v.name.trim()) { toast('Give it a name', 'error'); return; }
    try {
      await api.post('/pantry', { name: v.name.trim(), quantity: v.quantity, unit: v.quantity == null ? null : v.unit,
        location: v.location || null, category: v.category || null, expires_at: v.expires_at || null, note: v.note || null });
      close(); reload(); toast('Added to the pantry');
    } catch (err) { errorToast(err); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title="Add to pantry">
    <form class="form" onSubmit=${save}>
      <${Field} label="What"><input value=${v.name} onInput=${(e) => set('name')(e.target.value)} placeholder="e.g. Leftover chili, olive oil" autofocus /></${Field}>
      <${Field} label="Amount" hint="Leave empty for things like spices"><${QtyInput} quantity=${v.quantity} unit=${v.unit} onChange=${({ quantity, unit }) => setV({ ...v, quantity, unit })} /></${Field}>
      <${Field} label="Kind of food" hint="Sets the default place and expiry"><select value=${v.category} onChange=${(e) => set('category')(e.target.value)}>
        <option value="">Same as last time / not sure</option>${cats.map((c) => html`<option value=${c.key}>${c.label}</option>`)}</select></${Field}>
      <${Field} label="Where"><${Segmented} small=${true} value=${v.location} onChange=${set('location')}
        options=${[['', 'Default'], ['fridge', 'Fridge'], ['freezer', 'Freezer'], ['pantry', 'Cupboard']]} /></${Field}>
      <${Field} label="Use by" hint="Leave empty to set it automatically"><input type="date" value=${v.expires_at} onInput=${(e) => set('expires_at')(e.target.value)} /></${Field}>
      <${Field} label="Note"><input value=${v.note} onInput=${(e) => set('note')(e.target.value)} /></${Field}>
      <button class="btn primary wide" type="submit">Add</button>
    </form>
  </${Sheet}>`;
}
