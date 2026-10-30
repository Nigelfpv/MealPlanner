// App shell: boot data, hash router, bottom navigation and the running-timer dock.

import { html, render, useEffect, useState } from '../vendor/preact-htm.js';
import { api } from './api.js';
import { setTables } from './units.js';
import { TimerDock } from './dock.js';
import { Icon, Toasts, Empty, store } from './ui.js';
import { PlanView } from './plan.js';
import { ShopView, PutAwayView } from './shop.js';
import { PantryView } from './pantry.js';
import { RecipesView, RecipeView, ConvertView } from './recipes.js';
import { MoreView, TasteView, RequestsView, RatingsView, HistoryView, ExpiryView, ClaudeView } from './more.js';

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '') || 'plan';
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean);
  const query = Object.fromEntries(new URLSearchParams(qs || ''));
  return { parts, query };
}

function useRoute() {
  const [route, setRoute] = useState(parseHash());
  useEffect(() => {
    const on = () => { setRoute(parseHash()); window.scrollTo(0, 0); };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return route;
}

const TABS = [
  ['plan', 'week', 'Week'],
  ['shop', 'cart', 'Shop'],
  ['pantry', 'pantry', 'Pantry'],
  ['recipes', 'book', 'Recipes'],
  ['more', 'more', 'More'],
];

function view({ parts, query }) {
  const [a, b] = parts;
  switch (a) {
    case 'plan': return html`<${PlanView} query=${query} />`;
    case 'shop': return html`<${ShopView} />`;
    case 'putaway': return html`<${PutAwayView} id=${b} key=${b} />`;
    case 'pantry': return html`<${PantryView} />`;
    case 'recipes': return html`<${RecipesView} />`;
    case 'recipe': return html`<${RecipeView} id=${b} query=${query} key=${b} />`;
    case 'convert': return html`<${ConvertView} />`;
    case 'more':
      if (b === 'taste') return html`<${TasteView} />`;
      if (b === 'requests') return html`<${RequestsView} />`;
      if (b === 'ratings') return html`<${RatingsView} />`;
      if (b === 'history') return html`<${HistoryView} />`;
      if (b === 'expiry') return html`<${ExpiryView} />`;
      if (b === 'claude') return html`<${ClaudeView} />`;
      return html`<${MoreView} />`;
    default: return html`<${Empty} title="Page not found"><a href="#/plan">Go to this week</a></${Empty}>`;
  }
}

const TAB_FOR = { putaway: 'shop', recipe: 'recipes', convert: 'recipes' };

function App() {
  const route = useRoute();
  const [boot, setBoot] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.get('/bootstrap').then((b) => { store.boot = b; setTables(b.units); setBoot(b); }).catch(setErr);
  }, []);
  // refresh the open-request count when moving between pages
  useEffect(() => {
    if (!store.boot) return;
    api.get('/requests?status=open').then((r) => { store.boot.open_requests = r.length; }).catch(() => {});
  }, [route.parts[0]]);

  const active = TAB_FOR[route.parts[0]] || route.parts[0] || 'plan';
  return html`<div class="app">
    <a class="skip" href="#main">Skip to content</a>
    <main id="main">
      ${err && html`<${Empty} title="Couldn't start the app">${err.message}</${Empty}>`}
      ${boot && view(route)}
    </main>
    <${TimerDock} global=${true} />
    <nav class="tabbar" aria-label="Main">
      ${TABS.map(([key, icon, label]) => html`<a href=${'#/' + key} class=${active === key ? 'on' : ''} aria-current=${active === key ? 'page' : null} key=${key}>
        <${Icon} name=${icon} size=${24} /><span>${label}</span></a>`)}
    </nav>
    <${Toasts} />
  </div>`;
}

render(html`<${App} />`, document.getElementById('root'));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
