// Recipes: library, recipe page (servings, unit modes, per-ingredient converter,
// step timers, cook mode) and the stand-alone unit converter.

import { html, useState, useEffect, useMemo } from '../vendor/preact-htm.js';
import { api } from './api.js';
import * as U from './units.js';
import { startTimer, findByKey, remaining, fmt, pause, resume, useTimers } from './timers.js';
import { Icon, Sheet, Segmented, Field, Empty, useAsync, toast, errorToast, Stars, fmtShort } from './ui.js';
import { TimerDock } from './dock.js';

export function RecipesView() {
  const [q, setQ] = useState('');
  const [archived, setArchived] = useState(false);
  const { data } = useAsync(() => api.get(`/recipes?q=${encodeURIComponent(q)}&archived=${archived}`), [q, archived]);
  return html`<section class="view recipes">
    <header class="page-head">
      <div><h1>Recipes</h1><p class="muted">${data ? data.length + ' saved' : ''}</p></div>
      <div class="head-actions"><a class="btn small ghost" href="#/convert"><${Icon} name="scale" size=${18} /> Convert units</a></div>
    </header>
    <div class="search-row"><input type="search" placeholder="Search by name or ingredient" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search recipes" /></div>
    ${data && data.length === 0 && html`<${Empty} title=${q ? 'No recipes match' : 'No recipes yet'}>Recipes appear here when Claude plans your week.</${Empty}>`}
    <ul class="recipe-list">${(data || []).map((r) => html`<li key=${r.id}><a href=${'#/recipe/' + r.id} class=${r.archived ? 'archived' : ''}>
      <span class="rl-title">${r.title}</span>
      <span class="rl-meta muted">
        ${r.avg_stars && html`<span class="rated"><${Icon} name="star" size=${14} fill=${true} />${r.avg_stars}</span>`}
        ${(r.prep_minutes || r.cook_minutes) && html`<span>${(r.prep_minutes || 0) + (r.cook_minutes || 0)} min</span>`}
        ${r.times_cooked && html`<span>cooked ${r.times_cooked}×</span>`}
        ${(r.tags || []).slice(0, 3).map((t) => html`<span class="tag">${t}</span>`)}
      </span></a></li>`)}</ul>
    <label class="check small pad"><input type="checkbox" checked=${archived} onChange=${() => setArchived(!archived)} /><span>Show archived recipes</span></label>
  </section>`;
}

const MODES = [['original', 'As written'], ['metric', 'ml & g'], ['weight', 'Grams']];

function loadMode() { try { return localStorage.getItem('mp_unit_mode') || 'original'; } catch { return 'original'; } }

export function RecipeView({ id, query }) {
  const { data: r, error, reload } = useAsync(() => api.get('/recipes/' + id), [id]);
  const [servings, setServings] = useState(null);
  const [mode, setModeState] = useState(loadMode());
  const [convert, setConvert] = useState(null);
  const [ticked, setTicked] = useState({});
  const [cook, setCook] = useState(false);
  const [asking, setAsking] = useState(false);
  useTimers();
  useEffect(() => { if (r) setServings(Number(query.servings) || r.servings); }, [r && r.id]);
  const setMode = (m) => { setModeState(m); try { localStorage.setItem('mp_unit_mode', m); } catch { /* */ } };

  if (error) return html`<section class="view"><${Empty} title="Couldn't load this recipe">${error.message}</${Empty}></section>`;
  if (!r || servings == null) return html`<section class="view"><p class="muted pad">Loading…</p></section>`;

  const factor = servings / (r.servings || 1);
  const amount = (ing) => {
    if (ing.quantity == null) return '';
    const { q, unit } = U.inMode(ing.quantity * factor, ing.unit, mode, ing.density, ing.unit_weight);
    return U.format(q, unit);
  };
  const groups = [];
  r.ingredients.forEach((ing, idx) => {
    let g = groups.find((x) => x.name === (ing.group || ''));
    if (!g) groups.push(g = { name: ing.group || '', items: [] });
    g.items.push({ ...ing, idx });
  });
  const archive = async () => {
    try { await api.patch('/recipes/' + r.id, { archived: !r.archived }); reload(true); toast(r.archived ? 'Restored' : 'Archived'); }
    catch (e) { errorToast(e); }
  };

  return html`<section class="view recipe">
    <header class="page-head">
      <div>
        <button class="link back" onClick=${() => history.back()}><${Icon} name="left" size=${18} /> Back</button>
        <h1>${r.title}</h1>
        <p class="muted recipe-meta">
          ${r.prep_minutes && html`<span>Prep ${r.prep_minutes} min</span>`}
          ${r.cook_minutes && html`<span>Cook ${r.cook_minutes} min</span>`}
          ${r.avg_stars && html`<span class="rated"><${Icon} name="star" size=${14} fill=${true} />${r.avg_stars} (${r.ratings})</span>`}
        </p>
      </div>
    </header>
    ${r.description && html`<p class="lede">${r.description}</p>`}

    <div class="recipe-controls">
      <div class="servings" role="group" aria-label="Portions">
        <button class="icon-btn boxed" aria-label="Fewer portions" onClick=${() => setServings(Math.max(0.5, servings - (servings > 1 ? 1 : 0.5)))}><${Icon} name="minus" /></button>
        <span><b>${U.trimNum(servings, 1)}</b> portion${servings === 1 ? '' : 's'}</span>
        <button class="icon-btn boxed" aria-label="More portions" onClick=${() => setServings(servings + (servings >= 1 ? 1 : 0.5))}><${Icon} name="plus" /></button>
      </div>
      <${Segmented} small=${true} options=${MODES} value=${mode} onChange=${setMode} />
    </div>

    <h2 class="sec">Ingredients</h2>
    ${groups.map((g) => html`<div class="ing-group" key=${g.name}>
      ${g.name && html`<h3>${g.name}</h3>`}
      <ul class="ingredients">${g.items.map((ing) => html`<li key=${ing.id} class=${ticked[ing.id] ? 'ticked' : ''}>
        <button class="tick small" role="checkbox" aria-checked=${!!ticked[ing.id]} aria-label=${'Got ' + ing.name}
          onClick=${() => setTicked({ ...ticked, [ing.id]: !ticked[ing.id] })}>${ticked[ing.id] && html`<${Icon} name="check" size=${16} />`}</button>
        <button class="amount" onClick=${() => ing.quantity != null && setConvert(ing)} disabled=${ing.quantity == null}
          aria-label=${'Convert ' + ing.name}>${amount(ing) || '—'}</button>
        <span class="ing-name">${ing.name}${ing.prep && html`<span class="muted">, ${ing.prep}</span>`}${ing.optional && html` <span class="tag">optional</span>`}</span>
      </li>`)}</ul>
    </div>`)}
    <p class="muted small-print">Tap an amount to convert it.</p>

    <div class="steps-head"><h2 class="sec">Steps</h2>
      <button class="btn small" onClick=${() => setCook(true)}><${Icon} name="play" size=${16} /> Cook mode</button></div>
    <ol class="steps">${r.steps.map((s, i) => html`<li key=${i}>
      <span class="step-num" aria-hidden="true">${i + 1}</span>
      <div class="step-body">
        <p>${renderStep(s.text, r.ingredients, amount)}</p>
        <${StepTimers} recipe=${r} step=${s} index=${i} />
      </div>
    </li>`)}</ol>

    ${r.notes && html`<h2 class="sec">Tips</h2><p class="pre">${r.notes}</p>`}
    ${r.storage_notes && html`<h2 class="sec">Leftovers</h2><p class="pre">${r.storage_notes}</p>`}
    ${r.equipment && r.equipment.length > 0 && html`<h2 class="sec">You'll need</h2><p>${r.equipment.join(', ')}</p>`}

    ${r.ratings_list.length > 0 && html`<h2 class="sec">Your ratings</h2>
      <ul class="rating-list">${r.ratings_list.map((x) => html`<li key=${x.id}>
        <${Stars} value=${x.stars} onChange=${() => {}} size=${16} />
        <span class="muted">${fmtShort(x.created_at.slice(0, 10))}</span>
        ${x.comment && html`<p>${x.comment}</p>`}
      </li>`)}</ul>`}

    <div class="action-list compact">
      <button class="action" onClick=${() => setAsking(true)}><${Icon} name="chat" /><span>Ask Claude to change this recipe</span></button>
      <button class="action" onClick=${archive}><${Icon} name="book" /><span>${r.archived ? 'Restore recipe' : 'Archive recipe'}<small>Archived recipes aren't suggested again</small></span></button>
    </div>

    ${convert && html`<${ConvertSheet} ing=${convert} qty=${convert.quantity * factor} close=${() => setConvert(null)} />`}
    ${cook && html`<${CookMode} r=${r} amount=${amount} close=${() => setCook(false)} />`}
    ${asking && html`<${AskSheet} r=${r} close=${() => setAsking(false)} />`}
  </section>`;
}

function renderStep(text, ingredients, amount) {
  const parts = String(text).split(/\[\[(\d+)\]\]/g);
  return parts.map((p, i) => {
    if (i % 2 === 0) return p;
    const ing = ingredients[Number(p) - 1];
    if (!ing) return `[[${p}]]`;
    const a = amount(ing);
    return html`<span class="inline-ing">${a ? a + ' ' : ''}${ing.name}</span>`;
  });
}

function StepTimers({ recipe, step, index }) {
  if (!step.timers || !step.timers.length) return null;
  return html`<div class="step-timers">${step.timers.map((t, j) => {
    const key = `${recipe.id}:${index}:${j}`;
    const run = findByKey(key);
    const left = run ? remaining(run) : t.seconds;
    const state = run ? run.state : 'idle';
    const onClick = () => {
      if (!run || state === 'done') startTimer({ key, label: t.label, seconds: t.seconds, recipeId: recipe.id, recipeTitle: recipe.title });
      else if (state === 'running') pause(run.id);
      else resume(run.id);
    };
    return html`<button class=${'timer-btn ' + state} onClick=${onClick} key=${key}
      aria-label=${`${state === 'running' ? 'Pause' : 'Start'} timer ${t.label}`}>
      <${Icon} name=${state === 'running' ? 'pause' : 'play'} size=${16} />
      <span class="t-time">${fmt(state === 'done' ? 0 : left)}</span><span class="t-label">${t.label}</span>
    </button>`;
  })}</div>`;
}

function ConvertSheet({ ing, qty, close }) {
  const opts = U.optionsFor(ing.unit, ing.density, ing.unit_weight);
  return html`<${Sheet} open=${true} onClose=${close} title=${'Convert ' + ing.name}>
    <ul class="conv-list">${opts.map((u) => {
      const v = U.convert(qty, ing.unit, u, ing.density, ing.unit_weight);
      return v == null ? null : html`<li key=${u} class=${U.norm(ing.unit) === u ? 'current' : ''}><span>${U.format(v, u) || U.trimNum(v, 2)}</span>${u === 'pc' ? html`<span class="muted">pieces</span>` : ''}</li>`;
    })}</ul>
    <p class="muted small-print">${ing.density ? `Using ${ing.density} g per ml for ${ing.name}. ` : ''}${ing.unit_weight ? `One piece ≈ ${ing.unit_weight} g. ` : ''}1 tsp = 5 ml, 1 tbsp = 15 ml, 1 cup = 240 ml.</p>
  </${Sheet}>`;
}

function CookMode({ r, amount, close }) {
  const [i, setI] = useState(0);
  const s = r.steps[i];
  useEffect(() => {
    let lock = null;
    (async () => { try { if ('wakeLock' in navigator) lock = await navigator.wakeLock.request('screen'); } catch { /* */ } })();
    const onKey = (e) => {
      if (e.key === 'ArrowRight') setI((x) => Math.min(r.steps.length - 1, x + 1));
      if (e.key === 'ArrowLeft') setI((x) => Math.max(0, x - 1));
      if (e.key === 'Escape') close();
    };
    document.addEventListener('keydown', onKey);
    document.body.classList.add('no-scroll');
    return () => { if (lock) lock.release().catch(() => {}); document.removeEventListener('keydown', onKey); document.body.classList.remove('no-scroll'); };
  }, []);
  if (!s) return null;
  return html`<div class="cook-mode" role="dialog" aria-modal="true" aria-label=${'Cooking ' + r.title}>
    <div class="cm-head">
      <span class="muted">Step ${i + 1} of ${r.steps.length}</span>
      <button class="icon-btn" onClick=${close} aria-label="Close cook mode"><${Icon} name="close" /></button>
    </div>
    <div class="cm-progress" aria-hidden="true"><span style=${{ width: ((i + 1) / r.steps.length) * 100 + '%' }}></span></div>
    <div class="cm-body">
      <p class="cm-text">${renderStep(s.text, r.ingredients, amount)}</p>
      <${StepTimers} recipe=${r} step=${s} index=${i} />
    </div>
    <${TimerDock} />
    <div class="cm-nav">
      <button class="btn" disabled=${i === 0} onClick=${() => setI(i - 1)}><${Icon} name="left" /> Back</button>
      ${i < r.steps.length - 1
        ? html`<button class="btn primary" onClick=${() => setI(i + 1)}>Next step <${Icon} name="right" /></button>`
        : html`<button class="btn primary" onClick=${close}>Done</button>`}
    </div>
  </div>`;
}

function AskSheet({ r, close }) {
  const [reason, setReason] = useState('');
  const send = async () => {
    if (!reason.trim()) { toast('Write what you want changed', 'error'); return; }
    try { await api.post('/requests', { recipe_id: r.id, kind: 'other', reason: reason.trim() }); close(); toast('Saved. Claude will pick this up in your next planning chat.'); }
    catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title="Ask Claude to change this recipe">
    <${Field} label="What should change?"><textarea rows="4" value=${reason} onInput=${(e) => setReason(e.target.value)}
      placeholder="e.g. Make it spicier, fewer pans, explain step 3 better"></textarea></${Field}>
    <button class="btn primary wide" onClick=${send}>Send request</button>
  </${Sheet}>`;
}

// ------------------------------------------------------------------ stand-alone converter

export function ConvertView() {
  const T = U.tables();
  const [qty, setQty] = useState(1);
  const [unit, setUnit] = useState('tbsp');
  const [name, setName] = useState('salt');
  const [custom, setCustom] = useState('');
  const { data: catalog } = useAsync(() => api.get('/ingredients'), []);
  const known = useMemo(() => {
    const names = new Set(Object.keys(T.densities || {}));
    (catalog || []).forEach((c) => { if (c.density) names.add(c.name.toLowerCase()); });
    return [...names].sort();
  }, [catalog]);
  const cat = (catalog || []).find((c) => c.name.toLowerCase() === name.toLowerCase());
  const density = custom !== '' ? Number(custom) : (cat && cat.density) || U.defaultDensity(name);
  const unitWeight = (cat && cat.unit_weight) || U.defaultUnitWeight(name);
  const all = ['g', 'kg', 'oz', 'lb', 'ml', 'l', 'tsp', 'tbsp', 'cup', 'floz', 'pc'];
  return html`<section class="view convert">
    <header class="page-head"><div>
      <button class="link back" onClick=${() => history.back()}><${Icon} name="left" size=${18} /> Back</button>
      <h1>Convert units</h1></div></header>
    <div class="conv-inputs">
      <input type="number" inputmode="decimal" step="any" value=${qty} onInput=${(e) => setQty(Number(e.target.value))} aria-label="Amount" />
      <select value=${unit} onChange=${(e) => setUnit(e.target.value)} aria-label="From unit">
        ${all.map((u) => html`<option value=${u}>${u === 'pc' ? 'pieces' : U.label(u)}</option>`)}</select>
      <input list="known-ingredients" value=${name} onInput=${(e) => { setName(e.target.value); setCustom(''); }} aria-label="Ingredient" placeholder="Ingredient" />
      <datalist id="known-ingredients">${known.map((k) => html`<option value=${k} />`)}</datalist>
    </div>
    <${Field} label="Density (g per ml)" hint=${density ? `Using ${U.trimNum(density, 2)} g/ml${custom === '' ? ' for ' + name : ''}` : 'Unknown for this ingredient — enter one to convert between weight and volume'}>
      <input type="number" inputmode="decimal" step="any" value=${custom} placeholder=${density ? U.trimNum(density, 2) : ''} onInput=${(e) => setCustom(e.target.value)} />
    </${Field}>
    <ul class="conv-list big">${all.filter((u) => u !== unit).map((u) => {
      const v = U.convert(qty, unit, u, density, unitWeight);
      return v == null ? null : html`<li key=${u}><span>${U.format(v, u) || U.trimNum(v, 2)}</span>${u === 'pc' ? html`<span class="muted">pieces (≈${unitWeight} g each)</span>` : ''}</li>`;
    })}</ul>
    <p class="muted small-print">1 tsp = 5 ml, 1 tbsp = 15 ml, 1 cup = 240 ml, 1 oz = 28.35 g.</p>
  </section>`;
}
