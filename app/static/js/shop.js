// Shopping list (editable amounts, Dutch names, store filter), "done shopping",
// and the put-away screen that tells you where everything goes.

import { html, useState } from '../vendor/preact-htm.js';
import { api } from './api.js';
import { format } from './units.js';
import {
  Icon, Sheet, Segmented, Field, QtyInput, Empty, useAsync, toast, errorToast, store,
  expiryText, fmtDay, LOCATION_LABEL, LOCATION_ICON,
} from './ui.js';

export function ShopView() {
  const { data, error, loading, reload, setData } = useAsync(() => api.get('/shopping'), []);
  const [storeFilter, setStoreFilter] = useState('all');
  const [editing, setEditing] = useState(null);
  const [adding, setAdding] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [showBasket, setShowBasket] = useState(false);

  if (error) return html`<section class="view"><${Empty} title="Couldn't load the list">${error.message}</${Empty}></section>`;
  if (!data) return html`<section class="view"><p class="muted pad">${loading ? 'Loading…' : ''}</p></section>`;

  const items = data.items;
  const stores = [...new Set(items.map((i) => i.store).filter(Boolean))];
  const visible = items.filter((i) => storeFilter === 'all' || i.store === storeFilter || (storeFilter === 'any' && !i.store));
  const todo = visible.filter((i) => !i.checked);
  const basket = visible.filter((i) => i.checked);
  const groups = [];
  for (const it of todo) {
    const key = it.category || 'other';
    let g = groups.find((x) => x.key === key);
    if (!g) groups.push(g = { key, label: it.category_label || 'Other', label_nl: it.category_label_nl, items: [] });
    g.items.push(it);
  }
  const total = items.reduce((s, i) => s + (i.price || 0), 0);

  async function toggle(it) {
    const checked = !it.checked;
    setData((d) => ({ ...d, items: d.items.map((x) => x.id === it.id ? { ...x, checked } : x) }));
    try { await api.patch('/shopping/items/' + it.id, { checked }); }
    catch (e) { errorToast(e); reload(true); }
  }

  return html`<section class="view shop">
    <header class="page-head">
      <div>
        <h1>Shopping list</h1>
        <p class="muted">${items.filter((i) => !i.checked).length} to get${total ? ` · about €${total.toFixed(2)}` : ''}</p>
      </div>
      <div class="head-actions">
        <button class="btn small" onClick=${() => setAdding(true)}><${Icon} name="plus" size=${18} /> Add</button>
      </div>
    </header>

    ${stores.length > 0 && html`<div class="filters"><${Segmented} small=${true} value=${storeFilter} onChange=${setStoreFilter}
      options=${[['all', 'All'], ...stores.map((s) => [s, s]), ...(items.some((i) => !i.store) ? [['any', 'Any store']] : [])]} /></div>`}

    ${items.length === 0 && html`<${Empty} title="Your list is empty">Ask Claude to plan your week, or add items yourself.</${Empty}>`}
    ${items.length > 0 && todo.length === 0 && html`<${Empty} title="Everything's in the basket">Tap “Done shopping” when you're home.</${Empty}>`}

    ${groups.map((g) => html`<div class="aisle" key=${g.key}>
      <h2 class="aisle-head">${g.label}${g.label_nl && html` <span class="nl">${g.label_nl}</span>`}</h2>
      <ul class="shop-list">${g.items.map((it) => html`<${ShopItem} it=${it} key=${it.id} onToggle=${() => toggle(it)} onEdit=${() => setEditing(it)} />`)}</ul>
    </div>`)}

    ${basket.length > 0 && html`<div class="aisle basket">
      <button class="aisle-head as-button" onClick=${() => setShowBasket(!showBasket)} aria-expanded=${showBasket}>
        In your basket (${basket.length}) <${Icon} name=${showBasket ? 'left' : 'right'} size=${16} cls=${showBasket ? 'rot-90' : ''} /></button>
      ${showBasket && html`<ul class="shop-list">${basket.map((it) => html`<${ShopItem} it=${it} key=${it.id} onToggle=${() => toggle(it)} onEdit=${() => setEditing(it)} />`)}</ul>`}
    </div>`}

    ${items.some((i) => i.checked) && html`<div class="sticky-action">
      <button class="btn primary wide" onClick=${() => setCompleting(true)}><${Icon} name="bag" /> Done shopping (${items.filter((i) => i.checked).length})</button>
    </div>`}

    ${editing && html`<${ItemSheet} item=${editing} close=${() => setEditing(null)} reload=${() => reload(true)} />`}
    ${adding && html`<${ItemSheet} item=${null} close=${() => setAdding(false)} reload=${() => reload(true)} />`}
    ${completing && html`<${CompleteSheet} items=${items} close=${() => setCompleting(false)} />`}
  </section>`;
}

function ShopItem({ it, onToggle, onEdit }) {
  return html`<li class=${'shop-item' + (it.checked ? ' checked' : '')}>
    <button class="tick" role="checkbox" aria-checked=${it.checked} aria-label=${(it.checked ? 'Untick ' : 'Tick ') + it.name} onClick=${onToggle}>
      ${it.checked && html`<${Icon} name="check" size=${20} />`}
    </button>
    <button class="shop-main" onClick=${onEdit}>
      <span class="shop-name">${it.name}</span>
      ${it.name_nl && html`<span class="nl">${it.name_nl}</span>`}
      ${(it.offer || it.store || it.for_meals || it.note) && html`<span class="shop-meta">
        ${it.offer && html`<span class="offer">${it.offer}</span>`}
        ${it.store && html`<span class="store">${it.store}</span>`}
        ${it.for_meals && html`<span class="muted">${it.for_meals}</span>`}
        ${it.note && html`<span class="muted">${it.note}</span>`}
      </span>`}
    </button>
    <button class="qty-pill" onClick=${onEdit} aria-label=${'Change amount of ' + it.name}>${it.quantity != null ? format(it.quantity, it.unit) : 'Amount?'}${it.unit === 'pc' && it.quantity != null ? '×' : ''}</button>
  </li>`;
}

function ItemSheet({ item, close, reload }) {
  const cats = (store.boot && store.boot.categories) || [];
  const stores = (store.boot && store.boot.settings.stores) || [];
  const [v, setV] = useState(item ? { ...item } : { name: '', quantity: 1, unit: 'pc', category: 'other' });
  const [more, setMore] = useState(false);
  const set = (k) => (x) => setV({ ...v, [k]: x });
  const save = async (e) => {
    e && e.preventDefault();
    if (!v.name || !v.name.trim()) { toast('Give the item a name', 'error'); return; }
    const body = { name: v.name.trim(), name_nl: v.name_nl || null, quantity: v.quantity, unit: v.unit, category: v.category,
      store: v.store || null, offer: v.offer || null, note: v.note || null, location: v.location || null,
      shelf_life_days: v.shelf_life_days === '' ? null : v.shelf_life_days, storage_advice: v.storage_advice || null,
      price: v.price === '' ? null : v.price };
    try {
      if (item) await api.patch('/shopping/items/' + item.id, body);
      else await api.post('/shopping/items', body);
      close(); reload(); toast(item ? 'Saved' : 'Added to the list');
    } catch (err) { errorToast(err); }
  };
  const del = async () => {
    try { await api.del('/shopping/items/' + item.id); close(); reload(); toast('Removed from the list'); }
    catch (err) { errorToast(err); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${item ? item.name : 'Add to the list'}>
    <form onSubmit=${save} class="form">
      ${item && item.name_nl && html`<p class="nl sheet-sub">${item.name_nl}</p>`}
      ${!item && html`<${Field} label="What"><input value=${v.name} onInput=${(e) => set('name')(e.target.value)} placeholder="e.g. Milk" autofocus /></${Field}>`}
      <${Field} label="Amount" hint=${item && item.for_meals ? 'Needed for: ' + item.for_meals : 'Change it to the package you actually found'}>
        <${QtyInput} quantity=${v.quantity} unit=${v.unit} onChange=${({ quantity, unit }) => setV({ ...v, quantity, unit })} />
      </${Field}>
      ${item && item.storage_advice && html`<p class="advice"><b>At home:</b> ${item.storage_advice}</p>`}
      <button type="button" class="link" onClick=${() => setMore(!more)} aria-expanded=${more}>${more ? 'Fewer details' : 'More details'}</button>
      ${more && html`<div class="more-fields">
        ${item && html`<${Field} label="Name"><input value=${v.name} onInput=${(e) => set('name')(e.target.value)} /></${Field}>`}
        <${Field} label="Dutch name"><input value=${v.name_nl || ''} onInput=${(e) => set('name_nl')(e.target.value)} placeholder="Naam op het schap" /></${Field}>
        <${Field} label="Aisle"><select value=${v.category || 'other'} onChange=${(e) => set('category')(e.target.value)}>
          ${cats.map((c) => html`<option value=${c.key}>${c.label}</option>`)}</select></${Field}>
        <${Field} label="Store"><select value=${v.store || ''} onChange=${(e) => set('store')(e.target.value)}>
          <option value="">Any store</option>${[...new Set([...stores, v.store].filter(Boolean))].map((s) => html`<option value=${s}>${s}</option>`)}</select></${Field}>
        <${Field} label="Offer"><input value=${v.offer || ''} onInput=${(e) => set('offer')(e.target.value)} placeholder="e.g. 1+1 gratis" /></${Field}>
        <${Field} label="Price (€)"><input type="number" inputmode="decimal" step="0.01" value=${v.price ?? ''} onInput=${(e) => set('price')(e.target.value === '' ? '' : Number(e.target.value))} /></${Field}>
        <${Field} label="Store it in"><${Segmented} small=${true} value=${v.location || ''} onChange=${set('location')}
          options=${[['', 'Default'], ['fridge', 'Fridge'], ['freezer', 'Freezer'], ['pantry', 'Cupboard']]} /></${Field}>
        <${Field} label="Keeps for (days)" hint="Leave empty to use the default for this aisle"><input type="number" min="0" value=${v.shelf_life_days ?? ''}
          onInput=${(e) => set('shelf_life_days')(e.target.value === '' ? '' : Number(e.target.value))} /></${Field}>
        <${Field} label="Storage advice"><textarea rows="2" value=${v.storage_advice || ''} onInput=${(e) => set('storage_advice')(e.target.value)} /></${Field}>
        <${Field} label="Note"><input value=${v.note || ''} onInput=${(e) => set('note')(e.target.value)} /></${Field}>
      </div>`}
      <div class="row-actions">
        ${item && html`<button type="button" class="btn ghost danger" onClick=${del}><${Icon} name="trash" size=${18} /> Remove</button>`}
        <button type="submit" class="btn primary">${item ? 'Save' : 'Add'}</button>
      </div>
    </form>
  </${Sheet}>`;
}

function CompleteSheet({ items, close }) {
  const bought = items.filter((i) => i.checked);
  const left = items.filter((i) => !i.checked);
  const stores = [...new Set([...bought.map((i) => i.store).filter(Boolean), ...((store.boot && store.boot.settings.stores) || [])])];
  const [keep, setKeep] = useState(true);
  const [where, setWhere] = useState(bought.find((i) => i.store)?.store || '');
  const [spent, setSpent] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const trip = await api.post('/shopping/complete', { keep_unchecked: keep, store: where || null, total_spent: spent === '' ? null : Number(spent) });
      close();
      location.hash = '#/putaway/' + trip.id;
    } catch (e) { errorToast(e); setBusy(false); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title="Done shopping">
    <p>${bought.length} item${bought.length === 1 ? '' : 's'} go into your pantry, dated today with an expiry date for each.</p>
    ${left.length > 0 && html`<label class="check"><input type="checkbox" checked=${keep} onChange=${() => setKeep(!keep)} />
      <span>Keep the ${left.length} item${left.length === 1 ? '' : 's'} you didn't get on the list</span></label>`}
    <${Field} label="Where did you shop?"><select value=${where} onChange=${(e) => setWhere(e.target.value)}>
      <option value="">—</option>${stores.map((s) => html`<option value=${s}>${s}</option>`)}</select></${Field}>
    <${Field} label="Total on the receipt (€, optional)"><input type="number" inputmode="decimal" step="0.01" value=${spent} onInput=${(e) => setSpent(e.target.value)} /></${Field}>
    <button class="btn primary wide" onClick=${submit} disabled=${busy}>Log shopping and put things away</button>
  </${Sheet}>`;
}

// ------------------------------------------------------------------ put away

export function PutAwayView({ id }) {
  const { data: trip, error, reload } = useAsync(() => api.get('/trips/' + id), [id]);
  if (error) return html`<section class="view"><${Empty} title="Couldn't load this trip">${error.message}</${Empty}></section>`;
  if (!trip) return html`<section class="view"><p class="muted pad">Loading…</p></section>`;
  const groups = ['freezer', 'fridge', 'pantry'].map((loc) => ({ loc, items: trip.pantry_items.filter((p) => p.location === loc) }))
    .filter((g) => g.items.length);
  const setLoc = async (p, location) => {
    try { await api.patch('/pantry/' + p.id, { location }); reload(true); toast(`${p.name} → ${LOCATION_LABEL[location].toLowerCase()}, new expiry date set`); }
    catch (e) { errorToast(e); }
  };
  const setExp = async (p, expires_at) => {
    try { await api.patch('/pantry/' + p.id, { expires_at }); reload(true); }
    catch (e) { errorToast(e); }
  };
  return html`<section class="view putaway">
    <header class="page-head">
      <div><h1>Put it away</h1>
        <p class="muted">Bought ${fmtDay(trip.completed_at.slice(0, 10))}${trip.store ? ' at ' + trip.store : ''}${trip.total_spent ? ` · €${trip.total_spent.toFixed(2)}` : ''}</p></div>
    </header>
    ${trip.pantry_items.length === 0 && html`<${Empty} title="Nothing from this trip is in the pantry anymore" />`}
    ${groups.map((g) => html`<div class="putaway-group" key=${g.loc}>
      <h2 class="loc-head"><${Icon} name=${LOCATION_ICON[g.loc]} /> ${LOCATION_LABEL[g.loc]}</h2>
      <ul class="putaway-list">${g.items.map((p) => {
        const ex = expiryText(p.expires_at);
        return html`<li key=${p.id}>
          <div class="pa-top"><b>${p.name}</b><span class="muted">${p.quantity != null ? format(p.quantity, p.unit) : ''}</span></div>
          ${p.storage_advice && html`<p class="advice">${p.storage_advice}</p>`}
          <div class="pa-controls">
            <label class=${'exp ' + ex.cls}>Use by <input type="date" value=${p.expires_at || ''} onChange=${(e) => setExp(p, e.target.value)} /></label>
            <${Segmented} small=${true} value=${p.location} onChange=${(l) => setLoc(p, l)}
              options=${[['fridge', 'Fridge'], ['freezer', 'Freezer'], ['pantry', 'Cupboard']]} />
          </div>
        </li>`;
      })}</ul>
    </div>`)}
    <div class="sticky-action"><a class="btn primary wide" href="#/pantry">All put away</a></div>
  </section>`;
}
