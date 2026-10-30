// Running-timer bar, shown above the tab bar and inside cook mode.

import { html, useEffect, useRef } from '../vendor/preact-htm.js';
import { useTimers, remaining, fmt, pause, resume, remove, addTime, stopRinging } from './timers.js';
import { Icon } from './ui.js';

export function TimerDock({ global = false }) {
  const timers = useTimers();
  const ref = useRef(null);
  useEffect(() => {
    if (!global) return;
    const h = ref.current ? ref.current.offsetHeight : 0;
    document.documentElement.style.setProperty('--dock-h', h + 'px');
  });
  if (!timers.length) return null;
  return html`<div class="timer-dock" role="region" aria-label="Running timers" ref=${ref}>
    ${timers.map((t) => {
      const left = remaining(t);
      return html`<div class=${'dock-timer ' + t.state} key=${t.id}>
        <a class="dt-label" href=${t.recipeId ? '#/recipe/' + t.recipeId : '#/recipes'}>
          <span class="dt-time">${t.state === 'done' ? "Time's up" : fmt(left)}</span>
          <span class="dt-name">${t.label}</span>
        </a>
        ${t.state === 'done'
          ? html`<button class="btn small primary" onClick=${() => { stopRinging(); remove(t.id); }}>Stop</button>
                 <button class="btn small" onClick=${() => addTime(t.id, 60)}>+1 min</button>`
          : html`<button class="icon-btn" aria-label=${t.state === 'running' ? 'Pause' : 'Resume'} onClick=${() => t.state === 'running' ? pause(t.id) : resume(t.id)}>
                   <${Icon} name=${t.state === 'running' ? 'pause' : 'play'} size=${20} /></button>
                 <button class="icon-btn" aria-label="Add a minute" onClick=${() => addTime(t.id, 60)}><span class="plus1">+1</span></button>
                 <button class="icon-btn" aria-label="Cancel timer" onClick=${() => remove(t.id)}><${Icon} name="close" size=${20} /></button>`}
      </div>`;
    })}
  </div>`;
}
