# Notes for working on this repo

Miguel's self-hosted meal planner (TrueNAS SCALE, behind Nginx Proxy Manager at https://comida.mmrdrive.duckdns.org).
He uses it from an Android phone. Single user. Claude reaches it through the MCP endpoint `/mcp` as a claude.ai custom
connector (OAuth with the app password).

## Layout

- `app/services.py` – all domain logic (recipes, meals, ratings, dislikes, change requests, shopping, pantry,
  expiry, aggregation, planning context). Both the REST API and the MCP tools call into it; put new logic here.
- `app/api.py` – JSON API for the web app (`/api/*`, session cookie).
- `app/mcp_server.py` – MCP tools for Claude. Tools return JSON strings; raise `ServiceError` for readable errors.
- `app/auth.py` – password login, rate limiting, single-user OAuth provider (SQLite-backed) for the MCP SDK.
- `app/db.py` – schema (`CREATE TABLE IF NOT EXISTS`), first-run seed (expiry categories, profile, dislikes).
  Schema changes: add an `ALTER TABLE` migration keyed on `meta.schema_version` — never drop data.
- `app/units.py` – unit tables + conversions; sent to the browser via `/api/bootstrap` so JS and Python agree.
- `app/static/` – no build step. `js/app.js` (router/shell), `plan.js`, `shop.js`, `pantry.js`, `recipes.js`,
  `more.js`, `timers.js` (+ `dock.js`), `ui.js` (shared components), `units.js`. Preact + htm vendored.

## Rules

- Keep `mcp` pinned to 1.x (2.x renamed FastMCP and changed APIs).
- The OAuth issuer must be https (or localhost in tests) — tests use `BASE_URL=http://localhost`.
- Run `python -m pytest -q tests` before pushing; CI runs the same and only builds the image if tests pass.
- UI: mobile-first, plain sentence-case copy, Delft-tile look (cobalt `#1e3f8f` on tile white), Bricolage Grotesque
  for headings, Atkinson Hyperlegible Next for text. Check pages at 412×915 with Playwright before pushing UI changes.
- Bump `CACHE` in `app/static/sw.js` when changing static files in a way that must reach phones immediately
  (the service worker is network-first, so normally not needed).
