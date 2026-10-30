"""FastAPI application: web UI, JSON API, login, and the MCP endpoint for Claude."""

import contextlib
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, db
from .api import router as api_router
from .mcp_server import build_mcp

STATIC = Path(__file__).parent / "static"
log = logging.getLogger("mealplanner")


def create_app() -> FastAPI:
    db.init_db()
    if not config.APP_PASSWORD:
        log.warning("APP_PASSWORD is not set — nobody can log in until you set it.")

    mcp = build_mcp()
    mcp_app = mcp.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="Meal Planner", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(api_router)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ------------------------------------------------------------------ pages

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        if not auth.session_valid(request):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"ok": True}

    @app.get("/login", include_in_schema=False)
    def login_page(request: Request, next: str = "/"):
        if auth.session_valid(request):
            return RedirectResponse(next if next.startswith("/") else "/", status_code=303)
        return HTMLResponse(auth.login_form("/login", "Meal Planner", "Sign in to plan your week.",
                                           hidden={"next": next}))

    @app.post("/login", include_in_schema=False)
    def login(request: Request, password: str = Form(""), next: str = Form("/")):
        if not auth.check_password(request, password):
            return HTMLResponse(auth.login_form("/login", "Meal Planner", "Sign in to plan your week.",
                                                "Wrong password.", hidden={"next": next}), status_code=401)
        resp = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/",
                                status_code=303)
        auth.set_session_cookie(resp, request)
        return resp

    @app.post("/logout", include_in_schema=False)
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE, path="/")
        return resp

    # ------------------------------------------------------------------ OAuth sign-in page for Claude

    @app.get("/oauth/login", include_in_schema=False)
    def oauth_login_page(request: Request, req: str):
        name = auth.pending_client_name(req)
        if name is None:
            return HTMLResponse(auth.page("Link expired", "<h1>Link expired</h1><p class='muted'>Start the "
                                                          "connection again from Claude.</p>"), status_code=400)
        sub = f"<b>{name}</b> wants to read and edit your menus, recipes, shopping list and pantry."
        logged_in = auth.session_valid(request)
        return HTMLResponse(auth.login_form("/oauth/login", "Connect to Meal Planner", sub, hidden={"req": req},
                                            button="Allow access", password=not logged_in))

    @app.post("/oauth/login", include_in_schema=False)
    def oauth_login(request: Request, req: str = Form(...), password: str = Form("")):
        if not auth.session_valid(request) and not auth.check_password(request, password):
            name = auth.pending_client_name(req) or "An app"
            sub = f"<b>{name}</b> wants to read and edit your menus, recipes, shopping list and pantry."
            return HTMLResponse(auth.login_form("/oauth/login", "Connect to Meal Planner", sub, "Wrong password.",
                                                hidden={"req": req}, button="Allow access"), status_code=401)
        return RedirectResponse(auth.complete_authorization(req), status_code=302)

    @app.post("/api/connector/revoke", include_in_schema=False)
    def revoke(request: Request):
        auth.require_session(request)
        auth.revoke_all_tokens()
        return {"ok": True}

    # Some clients look for the protected-resource document at the root path too.
    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    def protected_resource_root():
        return JSONResponse({
            "resource": f"{config.BASE_URL}/mcp",
            "authorization_servers": [f"{config.BASE_URL}/"],
            "scopes_supported": [auth.SCOPE],
            "bearer_methods_supported": ["header"],
        })

    @app.exception_handler(401)
    async def unauthorized(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Not logged in"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)

    # MCP endpoint (/mcp) plus the OAuth endpoints (/authorize, /token, /register, /.well-known/...)
    app.mount("/", mcp_app)
    return app


app = create_app()
