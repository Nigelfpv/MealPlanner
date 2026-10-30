// "More": taste profile & dislikes, change requests, ratings, shopping history,
// expiry defaults, Claude connection, export.

import { html, useState } from '../vendor/preact-htm.js';
import { api } from './api.js';
import {
  Icon, Sheet, Segmented, Field, Empty, Stars, useAsync, toast, errorToast, store, fmtDay, fmtShort,
} from './ui.js';

export function MoreView() {
  const links = [
    ['#/more/taste', 'chat', 'Taste profile', 'Dislikes and notes Claude plans around'],
    ['#/more/requests', 'swap', 'Change requests', 'Meals you asked Claude to change'],
    ['#/more/ratings', 'star', 'Ratings', 'Everything you rated'],
    ['#/more/history', 'bag', 'Shopping trips', 'When you shopped and what you bought'],
    ['#/more/expiry', 'fridge', 'Expiry and storage', 'Default shelf life per kind of food'],
    ['#/convert', 'scale', 'Convert units', 'Spoons, cups, grams and ml'],
    ['#/more/claude', 'chat', 'Connect Claude', 'Use this app from your Claude chats'],
  ];
  return html`<section class="view more">
    <header class="page-head"><div><h1>More</h1></div></header>
    <ul class="menu">${links.map(([href, icon, title, sub]) => html`<li key=${href}><a href=${href}>
      <${Icon} name=${icon} /><span><b>${title}</b><small class="muted">${sub}</small></span><${Icon} name="right" size=${18} cls="chev" /></a></li>`)}</ul>
    <div class="menu-foot">
      <a class="btn ghost small" href="/api/export" download="mealplanner-export.json">Download all data</a>
      <form method="post" action="/logout"><button class="btn ghost small" type="submit">Sign out</button></form>
    </div>
  </section>`;
}

function SubHead({ title, sub }) {
  return html`<header class="page-head"><div>
    <a class="link back" href="#/more"><${Icon} name="left" size=${18} /> More</a>
    <h1>${title}</h1>${sub && html`<p class="muted">${sub}</p>`}</div></header>`;
}

// ------------------------------------------------------------------ taste profile

const SEV = [[1, 'Mild'], [2, 'Avoid'], [3, 'Never']];
const SEV_HELP = { 1: 'Fine in small or hidden amounts', 2: 'Leave it out', 3: 'Hates it — never use it' };

export function TasteView() {
  const { data: dislikes, reload } = useAsync(() => api.get('/dislikes'), []);
  const { data: settings, setData: setSettings } = useAsync(() => api.get('/settings'), []);
  const [item, setItem] = useState('');
  const [sev, setSev] = useState(2);
  const [saving, setSaving] = useState(false);
  const add = async (e) => {
    e.preventDefault();
    if (!item.trim()) return;
    try { await api.post('/dislikes', { item: item.trim(), severity: sev }); setItem(''); reload(true); }
    catch (err) { errorToast(err); }
  };
  const change = async (d, severity) => {
    try { await api.post('/dislikes', { item: d.item, severity }); reload(true); } catch (err) { errorToast(err); }
  };
  const remove = async (d) => {
    try { await api.del('/dislikes/' + d.id); reload(true); toast(`Removed ${d.item}`); } catch (err) { errorToast(err); }
  };
  const saveProfile = async () => {
    setSaving(true);
    try { const s = await api.put('/settings', { profile: settings.profile }); setSettings(s); toast('Profile saved'); }
    catch (err) { errorToast(err); }
    setSaving(false);
  };
  return html`<section class="view taste">
    <${SubHead} title="Taste profile" sub="Claude reads this every time it plans." />
    <h2 class="sec">Dislikes</h2>
    <form class="dislike-add" onSubmit=${add}>
      <input value=${item} onInput=${(e) => setItem(e.target.value)} placeholder="Ingredient or dish, e.g. mushrooms" aria-label="Disliked item" />
      <${Segmented} small=${true} options=${SEV} value=${sev} onChange=${setSev} />
      <button class="btn" type="submit" disabled=${!item.trim()}>Add</button>
    </form>
    <p class="muted small-print">Mild: ${SEV_HELP[1].toLowerCase()}. Avoid: ${SEV_HELP[2].toLowerCase()}. Never: hates it.</p>
    <ul class="dislike-list">${(dislikes || []).map((d) => html`<li key=${d.id}>
      <div><b>${d.item}</b>${d.note && html`<small class="muted">${d.note}</small>`}</div>
      <${Segmented} small=${true} options=${SEV} value=${d.severity} onChange=${(s) => change(d, s)} />
      <button class="icon-btn" aria-label=${'Remove ' + d.item} onClick=${() => remove(d)}><${Icon} name="trash" size=${18} /></button>
    </li>`)}</ul>
    ${dislikes && dislikes.length === 0 && html`<p class="muted">No dislikes yet.</p>`}

    <h2 class="sec">Notes for Claude</h2>
    ${settings && html`<div class="form">
      <textarea rows="12" value=${settings.profile} onInput=${(e) => setSettings({ ...settings, profile: e.target.value })} aria-label="Food profile"></textarea>
      <button class="btn primary" onClick=${saveProfile} disabled=${saving}>Save notes</button>
    </div>`}
  </section>`;
}

// ------------------------------------------------------------------ requests

export function RequestsView() {
  const [status, setStatus] = useState('open');
  const { data, reload } = useAsync(() => api.get('/requests?status=' + status), [status]);
  const dismiss = async (r) => {
    try {
      await api.patch('/requests/' + r.id, { status: 'dismissed' });
      if (store.boot && status === 'open') store.boot.open_requests = Math.max(0, store.boot.open_requests - 1);
      reload(true); toast('Request withdrawn');
    } catch (e) { errorToast(e); }
  };
  return html`<section class="view">
    <${SubHead} title="Change requests" sub="Claude handles open requests at the start of your next planning chat." />
    <div class="filters"><${Segmented} small=${true} value=${status} onChange=${setStatus}
      options=${[['open', 'Open'], ['done', 'Done'], ['dismissed', 'Withdrawn']]} /></div>
    ${data && data.length === 0 && html`<${Empty} title=${status === 'open' ? 'No open requests' : 'Nothing here'}>
      ${status === 'open' ? 'Open a meal in your week and choose “Ask for a change”.' : ''}</${Empty}>`}
    <ul class="req-list">${(data || []).map((r) => html`<li key=${r.id}>
      <b>${r.meal_label || 'Recipe'}</b>
      <p>${r.kind === 'replace_meal' ? 'Wants a different meal' : r.kind === 'swap_ingredients' ? 'Swap: ' + r.ingredients.join(', ') : 'Change request'}${r.reason ? ' — ' + r.reason : ''}</p>
      ${r.resolution && html`<p class="muted">Claude: ${r.resolution}</p>`}
      <small class="muted">${fmtShort(r.created_at.slice(0, 10))}</small>
      ${r.status === 'open' && html`<button class="btn ghost small" onClick=${() => dismiss(r)}>Withdraw</button>`}
    </li>`)}</ul>
  </section>`;
}

// ------------------------------------------------------------------ ratings

export function RatingsView() {
  const { data } = useAsync(() => api.get('/ratings'), []);
  const label = { too_small: 'portion too small', right: 'portion right', too_big: 'portion too big', easy: 'easy', ok: 'OK effort', hard: 'hard',
    yes: 'make again', maybe: 'maybe again', no: "don't repeat" };
  return html`<section class="view">
    <${SubHead} title="Ratings" />
    ${data && data.length === 0 && html`<${Empty} title="No ratings yet">Open a meal in your week and rate it after eating.</${Empty}>`}
    <ul class="rating-list">${(data || []).map((r) => html`<li key=${r.id}>
      <div class="rl-top">${r.recipe_id ? html`<a href=${'#/recipe/' + r.recipe_id}><b>${r.recipe_title}</b></a>` : html`<b>${r.recipe_title}</b>`}
        <${Stars} value=${r.stars} onChange=${() => {}} size=${16} /></div>
      <small class="muted">${r.meal_date ? fmtDay(r.meal_date) : fmtShort(r.created_at.slice(0, 10))}${[r.would_repeat, r.effort, r.portion].filter(Boolean).map((x) => ', ' + label[x]).join('')}</small>
      ${r.comment && html`<p>${r.comment}</p>`}
    </li>`)}</ul>
  </section>`;
}

// ------------------------------------------------------------------ shopping history

export function HistoryView() {
  const { data } = useAsync(() => api.get('/trips'), []);
  return html`<section class="view">
    <${SubHead} title="Shopping trips" />
    ${data && data.length === 0 && html`<${Empty} title="No trips logged yet">Tick items on your list and tap “Done shopping”.</${Empty}>`}
    <ul class="menu">${(data || []).map((t) => html`<li key=${t.id}><a href=${'#/putaway/' + t.id}>
      <${Icon} name="bag" /><span><b>${fmtDay(t.completed_at.slice(0, 10))}${t.store ? ' · ' + t.store : ''}</b>
      <small class="muted">${t.item_count} items${t.total_spent ? ` · €${t.total_spent.toFixed(2)}` : ''}</small></span>
      <${Icon} name="right" size=${18} cls="chev" /></a></li>`)}</ul>
  </section>`;
}

// ------------------------------------------------------------------ expiry defaults

export function ExpiryView() {
  const { data: cats, reload } = useAsync(() => api.get('/categories'), []);
  const [editing, setEditing] = useState(null);
  const d = (n) => n == null ? '—' : n >= 60 ? Math.round(n / 30) + ' mo' : n + ' d';
  return html`<section class="view expiry">
    <${SubHead} title="Expiry and storage" sub="Used when you finish shopping, unless Claude or you set a specific date." />
    <table class="exp-table">
      <thead><tr><th scope="col">Kind of food</th><th scope="col">Fridge</th><th scope="col">Freezer</th><th scope="col">Cupboard</th></tr></thead>
      <tbody>${(cats || []).map((c) => html`<tr key=${c.key} onClick=${() => setEditing(c)} tabindex="0"
          onKeyDown=${(e) => e.key === 'Enter' && setEditing(c)}>
        <th scope="row">${c.label}<small class="muted">goes in the ${c.default_location === 'pantry' ? 'cupboard' : c.default_location}</small></th>
        <td class=${c.default_location === 'fridge' ? 'def' : ''}>${d(c.fridge_days)}</td>
        <td class=${c.default_location === 'freezer' ? 'def' : ''}>${d(c.freezer_days)}</td>
        <td class=${c.default_location === 'pantry' ? 'def' : ''}>${d(c.pantry_days)}</td></tr>`)}</tbody>
    </table>
    ${editing && html`<${CategorySheet} c=${editing} close=${() => setEditing(null)} reload=${() => reload(true)} />`}
  </section>`;
}

function CategorySheet({ c, close, reload }) {
  const [v, setV] = useState({ ...c });
  const num = (k) => html`<input type="number" min="0" value=${v[k] ?? ''} onInput=${(e) => setV({ ...v, [k]: e.target.value === '' ? null : Number(e.target.value) })} />`;
  const save = async () => {
    try {
      await api.patch('/categories/' + c.key, { default_location: v.default_location, fridge_days: v.fridge_days, freezer_days: v.freezer_days,
        pantry_days: v.pantry_days, opened_days: v.opened_days, advice: v.advice });
      if (store.boot) store.boot.categories = await api.get('/categories');
      close(); reload(); toast('Saved');
    } catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${c.label}>
    <div class="form">
      <${Field} label="Normally goes in"><${Segmented} small=${true} value=${v.default_location} onChange=${(x) => setV({ ...v, default_location: x })}
        options=${[['fridge', 'Fridge'], ['freezer', 'Freezer'], ['pantry', 'Cupboard']]} /></${Field}>
      <div class="grid-3">
        <${Field} label="Fridge (days)">${num('fridge_days')}</${Field}>
        <${Field} label="Freezer (days)">${num('freezer_days')}</${Field}>
        <${Field} label="Cupboard (days)">${num('pantry_days')}</${Field}>
      </div>
      <${Field} label="After opening (days)">${num('opened_days')}</${Field}>
      <${Field} label="Storage advice"><textarea rows="4" value=${v.advice || ''} onInput=${(e) => setV({ ...v, advice: e.target.value })}></textarea></${Field}>
      <button class="btn primary wide" onClick=${save}>Save</button>
    </div>
  </${Sheet}>`;
}

// ------------------------------------------------------------------ Claude connection

export function ClaudeView() {
  const url = location.origin + '/mcp';
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); toast('Copied'); } catch { toast('Select the address and copy it', 'error'); }
  };
  const revoke = async () => {
    if (!confirm('Disconnect Claude? You will need to connect again from Claude settings.')) return;
    try { await api.post('/connector/revoke'); toast('Claude disconnected'); } catch (e) { errorToast(e); }
  };
  return html`<section class="view">
    <${SubHead} title="Connect Claude" />
    <ol class="howto">
      <li>In Claude, open <b>Settings → Connectors</b> and choose <b>Add custom connector</b>.</li>
      <li>Name it <b>Meal Planner</b> and paste this address:
        <div class="copy-row"><code>${url}</code><button class="btn small" onClick=${copy}>Copy</button></div></li>
      <li>Claude opens a page from this app: enter your password and tap <b>Allow access</b>.</li>
      <li>In a chat, turn the connector on and ask, for example: <i>“Plan next week's meals.”</i></li>
    </ol>
    <div class="action-list compact"><button class="action danger" onClick=${revoke}><${Icon} name="close" /><span>Disconnect Claude</span></button></div>
  </section>`;
}
