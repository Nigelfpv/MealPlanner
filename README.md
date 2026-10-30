# Meal Planner

A self-hosted meal planner for one: weekly menu, shopping list, recipes with timers and unit conversion, a pantry
with expiry dates, ratings and dislikes. Claude connects to it as a **custom connector** and writes the whole week in one
chat: menu, recipes, shopping list (with Dutch names, offers, storage advice and shelf life).

- **Week**: lunch and dinner per day. Drag the ⋮⋮ handle (or use *Move or swap*) to move meals; dropping on a taken
  slot swaps them. Mark as cooked (deducts ingredients from the pantry), rate, or ask Claude for a change
  (swap ingredients / different meal, and mark disliked ingredients with severity).
- **Shop**: grouped by aisle, Dutch names, store filter, every amount editable (500 ml → 1 kg). *Done shopping* logs the
  trip, moves ticked items to the pantry with a purchase date and an automatic expiry date, and shows where to
  put everything away.
- **Pantry**: what's left, where it is, when it expires. Moving something to the freezer resets its expiry date.
- **Recipes**: scale portions, show amounts as written / in ml & g / in grams, tap any amount to convert, a timer on
  every step, cook mode (big text, screen stays on).
- **More**: taste profile (dislikes + notes Claude reads), change requests, ratings, shopping trips, default
  expiry/storage per kind of food (editable), connect Claude, export all data.

## Deploy on TrueNAS SCALE

### 1. Image

Every push to `main` runs the tests and builds `ghcr.io/nigelfpv/mealplanner:latest` (GitHub → Actions).
The image is private by default, so TrueNAS needs to be allowed to pull it. Pick one:

- **Simplest:** make the package public: GitHub → your profile → *Packages* → `mealplanner` → *Package settings* →
  *Change visibility* → Public. The image contains only the code (no password, no data).
- **Keep it private:** create a classic personal access token with only `read:packages`, then in TrueNAS go to
  *Apps → Discover Apps → ⋮ → Manage Container Images → Pull Image*, image `ghcr.io/nigelfpv/mealplanner:latest`,
  username `Nigelfpv`, password = the token. Repeat that pull before each update.

### 2. Dataset

Create a dataset for the app's data, e.g. `POOL/apps/mealplanner`, with the *Apps* preset (owner `apps`, uid 568).
Everything lives in it: `mealplanner.db` (SQLite) and `secret_key`. Add it to a periodic snapshot task.

### 3. App

*Apps → Discover Apps → ⋮ → Install via YAML*, name it `mealplanner`, paste [`docker-compose.yml`](docker-compose.yml) and change:

- `APP_PASSWORD` – the password for the web app and for connecting Claude. Use a long one: the app is public.
- the volume path `/mnt/POOL/apps/mealplanner` – your dataset's path.
- the host port `8420` if it's taken.

### 4. Nginx Proxy Manager

DuckDNS already resolves `comida.mmrdrive.duckdns.org` to the same IP as `mmrdrive.duckdns.org`, so no DNS change is needed.
Add a **Proxy Host**:

| Field | Value |
|---|---|
| Domain | `comida.mmrdrive.duckdns.org` |
| Scheme / Forward host / Port | `http` / your TrueNAS LAN IP / `8420` |
| Block common exploits | on |
| SSL tab | Request a new Let's Encrypt certificate, *Force SSL*, *HTTP/2* |

Don't put an access list on it: Claude connects from Anthropic's servers, not from your network.

Check: `https://comida.mmrdrive.duckdns.org` shows the sign-in page, and
`https://comida.mmrdrive.duckdns.org/.well-known/oauth-authorization-server` shows JSON.

### 5. Phone

Open the site in Chrome on Android, sign in, then *⋮ → Add to Home screen* (installs it as an app). Allow
notifications the first time you start a timer so it can alert you.

### 6. Connect Claude

claude.ai → *Settings → Connectors → Add custom connector*: name `Meal Planner`, URL
`https://comida.mmrdrive.duckdns.org/mcp`. Connect → the app's sign-in page opens → password → *Allow access*.
In a chat, make sure the connector is on and ask e.g. *"Plan next week's meals"*.
To cut Claude off: *More → Connect Claude → Disconnect Claude* (revokes every token).

## Updating

Push to `main` → wait for the green check in GitHub Actions → TrueNAS: *Apps → mealplanner → Edit → Save*
(`pull_policy: always` pulls the new image). Data stays in the dataset; the database schema is created/updated at start-up.

## Troubleshooting

- **The domain doesn't open at home but works on mobile data**: your router doesn't do NAT loopback. Add a local DNS
  override for `comida.mmrdrive.duckdns.org` → TrueNAS/NPM IP, or use the LAN address `http://TRUENAS-IP:8420`.
- **Claude says it can't connect**: open the `/.well-known/oauth-authorization-server` URL above; its URLs must start with
  `https://comida.mmrdrive.duckdns.org`. If not, `BASE_URL` is wrong.
- **Timers don't ring with the screen off**: keep the app open while cooking; it keeps the screen on while a timer
  runs. Notifications need permission (Android settings → Apps → Chrome → Notifications).

## Development

```bash
pip install -r requirements-dev.txt
DATA_DIR=./data APP_PASSWORD=dev BASE_URL=http://localhost:8000 uvicorn app.main:app --reload
python -m pytest -q tests
python tests/oauth_flow.py http://localhost:8000 dev   # end-to-end OAuth + MCP check
```

Python 3.12, FastAPI, SQLite, MCP Python SDK (pinned to 1.x). The front end is plain ES modules with Preact + htm
(vendored in `app/static/vendor`, no build step).
