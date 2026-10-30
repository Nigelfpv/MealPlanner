// Week plan: days as Delft tiles, lunch/dinner slots, drag or tap to move,
// cook (with pantry deduction), rate, request changes.

import { html, useState, useRef, useEffect } from '../vendor/preact-htm.js';
import { api } from './api.js';
import { format } from './units.js';
import {
  Icon, Sheet, Stars, Segmented, Field, Empty, useAsync, toast, errorToast, store,
  addDays, todayISO, fmtShort, parseISO, SLOT_LABEL,
} from './ui.js';

const BASE_SLOTS = ['lunch', 'dinner'];

function mondayOf(s) {
  const d = parseISO(s);
  const wd = (d.getDay() + 6) % 7;
  return addDays(s, -wd);
}

export function PlanView({ query }) {
  const start = mondayOf(query.start || todayISO());
  const { data: week, loading, error, reload } = useAsync(() => api.get('/plan?start=' + start), [start]);
  const [sheet, setSheet] = useState(null); // {type, meal, date, slot}
  const [moving, setMoving] = useState(null); // meal being moved by tapping
  const [showNotes, setShowNotes] = useState(false);
  const openReq = store.boot ? store.boot.open_requests : 0;

  const go = (s) => { location.hash = '#/plan?start=' + s; };
  const thisMonday = mondayOf(todayISO());

  async function moveTo(meal, date, slot) {
    if (meal.date === date && meal.slot === slot) return;
    try {
      await api.post(`/meals/${meal.id}/move`, { date, slot });
      setMoving(null);
      reload(true);
      toast(`Moved ${meal.display_title} to ${SLOT_LABEL[slot].toLowerCase()} on ${fmtShort(date)}`, 'info',
        { label: 'Undo', run: async () => { await api.post(`/meals/${meal.id}/move`, { date: meal.date, slot: meal.slot }); reload(true); } });
    } catch (e) { errorToast(e); }
  }

  const title = start === thisMonday ? 'This week' : start === addDays(thisMonday, 7) ? 'Next week'
    : start === addDays(thisMonday, -7) ? 'Last week' : `Week of ${fmtShort(start)}`;

  return html`<section class="view plan">
    <header class="page-head">
      <div>
        <h1>${title}</h1>
        <p class="muted">${fmtShort(start)} – ${fmtShort(addDays(start, 6))}</p>
      </div>
      <div class="head-actions">
        <button class="icon-btn" aria-label="Previous week" onClick=${() => go(addDays(start, -7))}><${Icon} name="left" /></button>
        ${start !== thisMonday && html`<button class="btn small ghost" onClick=${() => go(thisMonday)}>Today</button>`}
        <button class="icon-btn" aria-label="Next week" onClick=${() => go(addDays(start, 7))}><${Icon} name="right" /></button>
      </div>
    </header>

    ${openReq > 0 && html`<a class="notice" href="#/more/requests"><${Icon} name="chat" />
      <span>${openReq} change request${openReq > 1 ? 's' : ''} waiting for your next planning chat with Claude</span></a>`}

    ${week && week.summary && html`<div class=${'week-notes' + (showNotes ? ' open' : '')}>
      <button class="link" onClick=${() => setShowNotes(!showNotes)} aria-expanded=${showNotes}>
        ${showNotes ? 'Hide' : 'Show'} notes from Claude</button>
      ${showNotes && html`<p class="pre">${week.summary}</p>`}
    </div>`}

    ${moving && html`<div class="move-banner" role="status">
      <span>Tap a slot to move <b>${moving.display_title}</b>. A meal already there swaps places.</span>
      <button class="btn small" onClick=${() => setMoving(null)}>Cancel</button>
    </div>`}

    ${error && html`<${Empty} title="Couldn't load the plan">${error.message}</${Empty}>`}
    ${!week && loading && html`<p class="muted pad">Loading…</p>`}
    ${week && html`<${Days} week=${week} moving=${moving} onTapSlot=${(date, slot) => moving ? moveTo(moving, date, slot) : setSheet({ type: 'add', date, slot })}
        onTapMeal=${(m) => moving ? moveTo(moving, m.date, m.slot) : setSheet({ type: 'meal', meal: m })}
        onDrop=${moveTo} />`}
    ${week && week.meals.length === 0 && html`<${Empty} title="Nothing planned for this week yet">
      Ask Claude in a chat to plan this week, or tap a slot to add a meal yourself.</${Empty}>`}

    <${MealSheet} sheet=${sheet} close=${() => setSheet(null)} reload=${() => reload(true)}
      startMove=${(m) => { setSheet(null); setMoving(m); }} open=${setSheet} />
  </section>`;
}

function Days({ week, moving, onTapSlot, onTapMeal, onDrop }) {
  const today = todayISO();
  const todayRef = useRef(null);
  const drag = useDrag(onDrop);
  useEffect(() => {
    if (todayRef.current && week.days.some((d) => d.date === today)) {
      todayRef.current.scrollIntoView({ block: 'start', behavior: 'instant' });
      window.scrollBy(0, -70);
    }
  }, [week.start]);

  return html`<ol class="days">
    ${week.days.map((day) => {
      const meals = week.meals.filter((m) => m.date === day.date);
      const slots = [...BASE_SLOTS];
      ['breakfast', 'snack'].forEach((s) => { if (meals.some((m) => m.slot === s)) slots.splice(s === 'breakfast' ? 0 : slots.length, 0, s); });
      const d = parseISO(day.date);
      const isToday = day.date === today;
      return html`<li class=${'day' + (isToday ? ' today' : '') + (day.date < today ? ' past' : '')}
          ref=${isToday ? todayRef : null} key=${day.date}>
        <div class="tile" aria-hidden="true">
          <span class="tile-wd">${day.label.split(' ')[0]}</span>
          <span class="tile-num">${d.getDate()}</span>
        </div>
        <div class="slots">
          <h3 class="sr-only">${day.label}</h3>
          ${slots.map((slot) => {
            const here = meals.filter((m) => m.slot === slot);
            return html`<div class=${'slot' + (moving ? ' target' : '')} data-date=${day.date} data-slot=${slot} key=${slot}>
              <span class="slot-label">${SLOT_LABEL[slot]}</span>
              <div class="slot-meals">
                ${here.length === 0 && html`<button class="slot-empty" onClick=${() => onTapSlot(day.date, slot)}>
                  ${moving ? 'Move here' : 'Add meal'}</button>`}
                ${here.map((m) => html`<${MealRow} meal=${m} key=${m.id} onTap=${() => onTapMeal(m)}
                  drag=${drag} dragging=${moving && moving.id === m.id} />`)}
              </div>
            </div>`;
          })}
        </div>
      </li>`;
    })}
  </ol>`;
}

function MealRow({ meal, onTap, drag, dragging }) {
  const r = meal.rating;
  return html`<div class=${'meal ' + meal.status + (dragging ? ' dragging' : '') + (meal.is_leftover ? ' leftover' : '')}>
    <button class="meal-main" onClick=${onTap}>
      <span class="meal-title">${meal.display_title}</span>
      <span class="meal-meta">
        ${meal.status === 'cooked' && html`<span class="tag ok"><${Icon} name="check" size=${14} /> Cooked</span>`}
        ${meal.status === 'eaten' && html`<span class="tag ok">Eaten</span>`}
        ${meal.status === 'skipped' && html`<span class="tag">Skipped</span>`}
        ${meal.is_leftover && html`<span class="tag">Leftovers</span>`}
        ${!meal.is_leftover && meal.recipe_id && meal.servings > 1 && html`<span>Cook ${format(meal.servings, 'pc')} portions</span>`}
        ${r && r.stars && html`<span class="rated" aria-label=${r.stars + ' stars'}><${Icon} name="star" size=${14} fill=${true} />${r.stars}</span>`}
        ${meal.open_requests.length > 0 && html`<span class="tag warn">Change requested</span>`}
      </span>
    </button>
    <span class="grip" aria-hidden="true" onPointerDown=${(e) => drag.start(e, meal)}>
      <svg width="16" height="22" viewBox="0 0 16 22"><g fill="currentColor">${[3, 9, 15].map((y) => html`<circle cx="5" cy=${y + 2} r="1.6"/><circle cx="11" cy=${y + 2} r="1.6"/>`)}</g></svg>
    </span>
  </div>`;
}

/** Pointer-based drag (works for touch, pen and mouse) using a handle with touch-action:none. */
function useDrag(onDrop) {
  const st = useRef(null);
  function start(e, meal) {
    e.preventDefault();
    const row = e.currentTarget.closest('.meal');
    const rect = row.getBoundingClientRect();
    const ghost = row.cloneNode(true);
    ghost.classList.add('ghost');
    ghost.style.width = rect.width + 'px';
    document.body.appendChild(ghost);
    st.current = { meal, ghost, dx: e.clientX - rect.left, dy: e.clientY - rect.top, over: null, y: e.clientY, raf: 0 };
    row.classList.add('drag-source');
    place(e.clientX, e.clientY);
    const move = (ev) => { place(ev.clientX, ev.clientY); };
    const up = (ev) => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      cancelAnimationFrame(st.current.raf);
      row.classList.remove('drag-source');
      ghost.remove();
      const over = st.current.over;
      if (over) over.classList.remove('drop-over');
      st.current = null;
      if (over && ev.type === 'pointerup') onDrop(meal, over.dataset.date, over.dataset.slot);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
    const scroll = () => {
      if (!st.current) return;
      const y = st.current.y;
      if (y < 90) window.scrollBy(0, -10);
      else if (y > window.innerHeight - 150) window.scrollBy(0, 10);
      st.current.raf = requestAnimationFrame(scroll);
    };
    st.current.raf = requestAnimationFrame(scroll);
    if (navigator.vibrate) navigator.vibrate(15);
  }
  function place(x, y) {
    const s = st.current;
    if (!s) return;
    s.y = y;
    s.ghost.style.transform = `translate(${x - s.dx}px, ${y - s.dy}px)`;
    s.ghost.style.visibility = 'hidden';
    const el = document.elementFromPoint(x, y);
    s.ghost.style.visibility = '';
    const slot = el && el.closest('[data-slot]');
    if (slot !== s.over) {
      if (s.over) s.over.classList.remove('drop-over');
      if (slot) slot.classList.add('drop-over');
      s.over = slot;
    }
  }
  return { start };
}

// ------------------------------------------------------------------ sheets

function MealSheet({ sheet, close, reload, startMove, open }) {
  if (!sheet) return null;
  if (sheet.type === 'add') return html`<${AddMealSheet} sheet=${sheet} close=${close} reload=${reload} />`;
  if (sheet.type === 'rate') return html`<${RateSheet} meal=${sheet.meal} close=${close} reload=${reload} />`;
  if (sheet.type === 'cook') return html`<${CookSheet} meal=${sheet.meal} close=${close} reload=${reload} open=${open} />`;
  if (sheet.type === 'change') return html`<${ChangeSheet} meal=${sheet.meal} close=${close} reload=${reload} />`;
  const m = sheet.meal;
  const act = async (fn, msg) => {
    try { await fn(); close(); reload(); if (msg) toast(msg); } catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${m.display_title}>
    <p class="muted sheet-sub">${SLOT_LABEL[m.slot]} on ${fmtShort(m.date)}${m.notes ? ' · ' + m.notes : ''}</p>
    ${m.rating && html`<div class="rating-summary"><${Stars} value=${m.rating.stars} onChange=${() => open({ type: 'rate', meal: m })} size=${20} />
      ${m.rating.comment && html`<p class="muted">“${m.rating.comment}”</p>`}</div>`}
    ${m.open_requests.map((r) => html`<p class="notice small"><${Icon} name="chat" size=${18} />
      <span>You asked: ${r.kind === 'replace_meal' ? 'a different meal' : 'swap ' + (r.ingredients || []).join(', ')}${r.reason ? ' — ' + r.reason : ''}</span></p>`)}
    <div class="action-list">
      ${m.recipe_id && html`<a class="action" href=${'#/recipe/' + m.recipe_id + '?servings=' + (m.is_leftover ? '' : (m.servings || ''))} onClick=${close}>
        <${Icon} name="book" /><span>Open recipe</span></a>`}
      ${m.status === 'planned' && !m.is_leftover && m.recipe_id && html`<button class="action" onClick=${() => open({ type: 'cook', meal: m })}>
        <${Icon} name="check" /><span>Mark as cooked<small>Updates what's left in your pantry</small></span></button>`}
      ${m.status === 'planned' && (m.is_leftover || !m.recipe_id) && html`<button class="action" onClick=${() => act(() => api.patch('/meals/' + m.id, { status: 'eaten' }), 'Marked as eaten')}>
        <${Icon} name="check" /><span>Mark as eaten</span></button>`}
      <button class="action" onClick=${() => open({ type: 'rate', meal: m })}><${Icon} name="star" />
        <span>${m.rating ? 'Change rating' : 'Rate this meal'}</span></button>
      <button class="action" onClick=${() => startMove(m)}><${Icon} name="move" /><span>Move or swap<small>Or drag the handle on the right</small></span></button>
      <button class="action" onClick=${() => open({ type: 'change', meal: m })}><${Icon} name="swap" />
        <span>Ask for a change<small>Swap ingredients or get a different meal</small></span></button>
      ${m.status === 'planned' && html`<button class="action" onClick=${() => act(() => api.patch('/meals/' + m.id, { status: 'skipped' }), 'Marked as skipped')}>
        <${Icon} name="undo" /><span>Skip this meal</span></button>`}
      ${m.status !== 'planned' && html`<button class="action" onClick=${() => act(() => api.patch('/meals/' + m.id, { status: 'planned' }), 'Back to planned')}>
        <${Icon} name="undo" /><span>Set back to planned</span></button>`}
      <button class="action danger" onClick=${() => { if (confirm('Remove this meal from the plan?')) act(() => api.del('/meals/' + m.id), 'Removed'); }}>
        <${Icon} name="trash" /><span>Remove from plan</span></button>
    </div>
  </${Sheet}>`;
}

function AddMealSheet({ sheet, close, reload }) {
  const [q, setQ] = useState('');
  const [title, setTitle] = useState('');
  const [servings, setServings] = useState(store.boot ? store.boot.settings.default_servings : 1);
  const { data: recipes } = useAsync(() => api.get('/recipes?q=' + encodeURIComponent(q)), [q]);
  const add = async (body) => {
    try {
      await api.post('/meals', { date: sheet.date, slot: sheet.slot, servings, ...body });
      close(); reload(); toast('Added to the plan');
    } catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${`Add ${SLOT_LABEL[sheet.slot].toLowerCase()} · ${fmtShort(sheet.date)}`}>
    <${Field} label="Portions to cook"><input type="number" min="0.5" step="0.5" value=${servings}
      onInput=${(e) => setServings(Number(e.target.value))} /></${Field}>
    <${Field} label="Pick a saved recipe"><input type="search" placeholder="Search recipes" value=${q}
      onInput=${(e) => setQ(e.target.value)} /></${Field}>
    <ul class="pick-list">
      ${(recipes || []).slice(0, 30).map((r) => html`<li key=${r.id}><button onClick=${() => add({ recipe_id: r.id })}>
        <span>${r.title}</span>${r.avg_stars && html`<span class="rated"><${Icon} name="star" size=${14} fill=${true} />${r.avg_stars}</span>`}
      </button></li>`)}
      ${recipes && recipes.length === 0 && html`<li class="muted pad">No recipes found.</li>`}
    </ul>
    <form class="inline-form" onSubmit=${(e) => { e.preventDefault(); if (title.trim()) add({ title: title.trim() }); }}>
      <${Field} label="…or just write what you'll eat"><input placeholder="e.g. Eat out, Frozen pizza" value=${title}
        onInput=${(e) => setTitle(e.target.value)} /></${Field}>
      <button class="btn" type="submit" disabled=${!title.trim()}>Add</button>
    </form>
  </${Sheet}>`;
}

const REPEAT = [['yes', 'Yes'], ['maybe', 'Maybe'], ['no', 'No']];
const EFFORT = [['easy', 'Easy'], ['ok', 'OK'], ['hard', 'Hard']];
const PORTION = [['too_small', 'Too small'], ['right', 'Right'], ['too_big', 'Too big']];

function RateSheet({ meal, close, reload }) {
  const r = meal.rating || {};
  const [v, setV] = useState({ stars: r.stars || 0, would_repeat: r.would_repeat || null, effort: r.effort || null,
    portion: r.portion || null, comment: r.comment || '' });
  const set = (k) => (x) => setV({ ...v, [k]: x });
  const save = async () => {
    if (!v.stars) { toast('Pick 1 to 5 stars first', 'error'); return; }
    try { await api.post('/ratings', { meal_id: meal.id, ...v }); close(); reload(); toast('Rating saved'); }
    catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title=${'Rate ' + meal.display_title}>
    <div class="rate-form">
      <${Stars} value=${v.stars} onChange=${set('stars')} size=${36} />
      <${Field} label="Make it again?"><${Segmented} options=${REPEAT} value=${v.would_repeat} onChange=${set('would_repeat')} /></${Field}>
      <${Field} label="Effort"><${Segmented} options=${EFFORT} value=${v.effort} onChange=${set('effort')} /></${Field}>
      <${Field} label="Portion size"><${Segmented} options=${PORTION} value=${v.portion} onChange=${set('portion')} /></${Field}>
      <${Field} label="Comment for Claude" hint="What to change next time, what you liked">
        <textarea rows="3" value=${v.comment} onInput=${(e) => set('comment')(e.target.value)}
          placeholder="e.g. Too salty, loved the sauce, needs more cheese"></textarea></${Field}>
      <button class="btn primary wide" onClick=${save}>Save rating</button>
    </div>
  </${Sheet}>`;
}

function CookSheet({ meal, close, reload, open }) {
  const { data: props, loading } = useAsync(() => api.get(`/meals/${meal.id}/deductions`), [meal.id]);
  const [edits, setEdits] = useState({});
  const [off, setOff] = useState({});
  const submit = async () => {
    const deductions = (props || []).filter((p) => !off[p.pantry_id + p.ingredient])
      .map((p) => ({ pantry_id: p.pantry_id, deduct: edits[p.pantry_id + p.ingredient] ?? p.deduct }));
    try {
      await api.post(`/meals/${meal.id}/cooked`, { deductions });
      close(); reload();
      toast('Marked as cooked', 'info', { label: 'Rate it', run: () => open({ type: 'rate', meal }) });
    } catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title="Mark as cooked">
    ${loading && html`<p class="muted">Checking your pantry…</p>`}
    ${props && props.length > 0 && html`<p class="muted">These amounts come off your pantry. Change them if you used more or less.</p>
      <ul class="deduct-list">${props.map((p) => {
        const k = p.pantry_id + p.ingredient;
        return html`<li key=${k} class=${off[k] ? 'off' : ''}>
          <label class="check"><input type="checkbox" checked=${!off[k]} onChange=${() => setOff({ ...off, [k]: !off[k] })} />
            <span><b>${p.pantry_name}</b><small class="muted">have ${format(p.have, p.unit)}</small></span></label>
          <span class="deduct-amt"><input type="number" inputmode="decimal" step="any" value=${edits[k] ?? p.deduct}
            onInput=${(e) => setEdits({ ...edits, [k]: Number(e.target.value) })} aria-label=${'Amount of ' + p.pantry_name} />
            <span>${p.unit === 'pc' ? 'pcs' : p.unit}</span></span>
        </li>`;
      })}</ul>`}
    ${props && props.length === 0 && html`<p class="muted">None of this recipe's ingredients are logged in your pantry, so nothing will be deducted.</p>`}
    <button class="btn primary wide" onClick=${submit} disabled=${loading}>Mark as cooked</button>
  </${Sheet}>`;
}

const SEVERITY = [[1, 'Mild'], [2, 'Avoid'], [3, 'Never']];

function ChangeSheet({ meal, close, reload }) {
  const [kind, setKind] = useState(meal.recipe_id ? 'swap_ingredients' : 'replace_meal');
  const [chosen, setChosen] = useState({});
  const [reason, setReason] = useState('');
  const { data: recipe } = useAsync(() => meal.recipe_id ? api.get('/recipes/' + meal.recipe_id) : Promise.resolve(null), [meal.recipe_id]);
  const toggle = (name) => setChosen((c) => { const n = { ...c }; if (n[name]) delete n[name]; else n[name] = { dislike: false, severity: 2 }; return n; });
  const upd = (name, patch) => setChosen((c) => ({ ...c, [name]: { ...c[name], ...patch } }));
  const submit = async () => {
    const names = Object.keys(chosen);
    if (kind === 'swap_ingredients' && names.length === 0) { toast('Pick at least one ingredient to swap', 'error'); return; }
    try {
      await api.post('/requests', {
        meal_id: meal.id, kind, reason: reason.trim() || null,
        ingredients: kind === 'swap_ingredients' ? names : [],
        dislikes: names.filter((n) => chosen[n].dislike).map((n) => ({ item: n, severity: chosen[n].severity })),
      });
      if (store.boot) store.boot.open_requests += 1;
      close(); reload(); toast('Saved. Claude will pick this up in your next planning chat.');
    } catch (e) { errorToast(e); }
  };
  return html`<${Sheet} open=${true} onClose=${close} title="Ask for a change">
    <p class="muted sheet-sub">${meal.display_title} · ${SLOT_LABEL[meal.slot]} on ${fmtShort(meal.date)}</p>
    <${Segmented} options=${[['swap_ingredients', 'Swap ingredients'], ['replace_meal', 'Different meal']]} value=${kind} onChange=${setKind} />
    ${kind === 'swap_ingredients' && recipe && html`<ul class="swap-list">${recipe.ingredients.map((i) => html`<li key=${i.id}>
      <label class="check"><input type="checkbox" checked=${!!chosen[i.name]} onChange=${() => toggle(i.name)} />
        <span>${i.name}</span></label>
      ${chosen[i.name] && html`<div class="swap-opts">
        <label class="check small"><input type="checkbox" checked=${chosen[i.name].dislike} onChange=${() => upd(i.name, { dislike: !chosen[i.name].dislike })} />
          <span>I don't like it</span></label>
        ${chosen[i.name].dislike && html`<${Segmented} small=${true} options=${SEVERITY} value=${chosen[i.name].severity} onChange=${(s) => upd(i.name, { severity: s })} />`}
      </div>`}
    </li>`)}</ul>`}
    ${kind === 'replace_meal' && recipe && html`<p class="muted">Also mark ingredients you don't like, so Claude avoids them next time:</p>
      <ul class="swap-list">${recipe.ingredients.map((i) => html`<li key=${i.id}>
        <label class="check"><input type="checkbox" checked=${!!(chosen[i.name] && chosen[i.name].dislike)}
          onChange=${() => chosen[i.name] ? toggle(i.name) : setChosen((c) => ({ ...c, [i.name]: { dislike: true, severity: 2 } }))} />
          <span>${i.name}</span></label>
        ${chosen[i.name] && html`<div class="swap-opts"><${Segmented} small=${true} options=${SEVERITY} value=${chosen[i.name].severity} onChange=${(s) => upd(i.name, { severity: s })} /></div>`}
      </li>`)}</ul>`}
    <p class="muted small-print">Mild: fine in small or hidden amounts. Avoid: leave it out. Never: you hate it.</p>
    <${Field} label="Anything else Claude should know?">
      <textarea rows="3" value=${reason} onInput=${(e) => setReason(e.target.value)} placeholder="e.g. Too much work on a weekday, use pork instead"></textarea>
    </${Field}>
    <button class="btn primary wide" onClick=${submit}>Send request</button>
  </${Sheet}>`;
}
