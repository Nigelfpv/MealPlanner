// Unit conversion and pretty formatting. Tables come from /api/bootstrap so the
// browser and the server use exactly the same numbers.

let T = { mass: {}, volume: {}, count: { pc: 1 }, labels: {}, aliases: {}, densities: {}, unit_weights: {} };

export function setTables(t) { T = t; }
export function tables() { return T; }

export function norm(u) {
  if (u == null) return 'pc';
  let s = String(u).trim().toLowerCase().replace(/\.$/, '');
  if (s in T.mass || s in T.volume || s in T.count) return s;
  if (s in T.aliases) return T.aliases[s];
  if (s.endsWith('s') && s.slice(0, -1) in T.aliases) return T.aliases[s.slice(0, -1)];
  return s;
}

export function dim(u) {
  u = norm(u);
  if (u in T.mass) return 'mass';
  if (u in T.volume) return 'volume';
  if (u in T.count) return 'count';
  return null;
}

export function label(u) {
  u = norm(u);
  return T.labels[u] || u;
}

function keywordLookup(table, name) {
  const n = (name || '').toLowerCase().trim();
  if (!n) return null;
  if (n in table) return table[n];
  const keys = Object.keys(table).sort((a, b) => b.length - a.length);
  for (const k of keys) {
    const re = new RegExp('\\b' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(e?s)?\\b');
    if (re.test(n)) return table[k];
  }
  return null;
}
export const defaultDensity = (name) => keywordLookup(T.densities, name);
export const defaultUnitWeight = (name) => keywordLookup(T.unit_weights, name);

export function convert(q, from, to, density, unitWeight) {
  if (q == null || isNaN(q)) return null;
  const f = norm(from), t = norm(to);
  if (f === t) return q;
  const fd = dim(f), td = dim(t);
  if (!fd || !td) return null;
  let amount = q * (fd === 'mass' ? T.mass[f] : fd === 'volume' ? T.volume[f] : T.count[f]);
  if (fd !== td) {
    let grams = null;
    if (fd === 'mass') grams = amount;
    else if (fd === 'volume' && density) grams = amount * density;
    else if (fd === 'count' && unitWeight) grams = amount * unitWeight;
    if (grams == null) return null;
    if (td === 'mass') amount = grams;
    else if (td === 'volume' && density) amount = grams / density;
    else if (td === 'count' && unitWeight) amount = grams / unitWeight;
    else return null;
  }
  const table = td === 'mass' ? T.mass : td === 'volume' ? T.volume : T.count;
  return amount / table[t];
}

/** Units this amount can be shown in. */
export function optionsFor(unit, density, unitWeight) {
  const d = dim(unit);
  const out = [];
  const mass = ['g', 'kg', 'oz', 'lb'];
  const vol = ['ml', 'l', 'tsp', 'tbsp', 'cup', 'floz'];
  if (d === 'mass') { out.push(...mass); if (density) out.push(...vol); if (unitWeight) out.push('pc'); }
  else if (d === 'volume') { out.push(...vol); if (density) out.push(...mass); }
  else if (d === 'count') { out.push('pc'); if (unitWeight) out.push('g', 'kg', 'oz'); }
  else out.push(norm(unit));
  return [...new Set(out)];
}

const FRACTIONS = [[0, ''], [0.25, '¼'], [1 / 3, '⅓'], [0.5, '½'], [2 / 3, '⅔'], [0.75, '¾'], [1, '']];

function fractional(q) {
  const whole = Math.floor(q);
  const rest = q - whole;
  let best = FRACTIONS[0], diff = 9;
  for (const f of FRACTIONS) { const d = Math.abs(rest - f[0]); if (d < diff) { diff = d; best = f; } }
  if (diff > 0.08) return trimNum(q, 2);
  const w = best[0] === 1 ? whole + 1 : whole;
  if (!w && !best[1]) return trimNum(q, 2);
  if (!best[1]) return String(w);
  return (w ? w : '') + best[1];
}

export function trimNum(q, dp = 1) {
  const s = Number(q).toFixed(dp);
  return s.includes('.') ? s.replace(/\.?0+$/, '') : s;
}

/** Turn an amount + unit into readable text, choosing kg/l for big numbers. */
export function format(q, unit) {
  if (q == null || q === '') return '';
  let u = norm(unit);
  if (u === 'g' && q >= 1000) { q = q / 1000; u = 'kg'; }
  if (u === 'ml' && q >= 1000) { q = q / 1000; u = 'l'; }
  let num;
  if (['tsp', 'tbsp', 'cup', 'pc', 'clove', 'can', 'pack', 'slice', 'bunch', 'jar', 'handful', 'sprig', 'bag', 'bottle'].includes(u)) {
    num = fractional(q);
  } else if (u === 'g' || u === 'ml') {
    num = q < 10 ? trimNum(q, 1) : String(Math.round(q));
  } else {
    num = trimNum(q, q < 10 ? 2 : 1);
  }
  if (u === 'pc') return num;
  return `${num} ${plural(u, q)}`;
}

const PLURAL = { clove: 'cloves', can: 'cans', slice: 'slices', pack: 'packs', jar: 'jars', bunch: 'bunches', cup: 'cups',
  pinch: 'pinches', handful: 'handfuls', sprig: 'sprigs', bag: 'bags', bottle: 'bottles' };
export function plural(u, q) {
  return q > 1 && PLURAL[u] ? PLURAL[u] : label(u);
}

/** Display an amount according to the recipe page's unit mode. */
export function inMode(q, unit, mode, density, unitWeight) {
  if (q == null) return { q, unit };
  const d = dim(unit);
  const u = norm(unit);
  if (mode === 'metric') {
    if (d === 'volume' && u !== 'ml' && u !== 'l') return { q: convert(q, u, 'ml'), unit: 'ml' };
    if (d === 'mass' && (u === 'oz' || u === 'lb')) return { q: convert(q, u, 'g'), unit: 'g' };
  }
  if (mode === 'weight') {
    if (d === 'volume' && density) return { q: convert(q, u, 'g', density), unit: 'g' };
    if (d === 'mass' && u !== 'g' && u !== 'kg') return { q: convert(q, u, 'g'), unit: 'g' };
    if (d === 'count' && unitWeight) return { q: convert(q, u, 'g', density, unitWeight), unit: 'g' };
  }
  return { q, unit: u };
}
