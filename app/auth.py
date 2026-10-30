"""Password login for the web UI and a small OAuth 2.1 server for Claude's connector."""

import hmac
import html
import json
import secrets
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from . import config, db

COOKIE = "mp_session"
SCOPE = "mealplanner"

_signer: TimestampSigner | None = None


def signer() -> TimestampSigner:
    global _signer
    if _signer is None:
        _signer = TimestampSigner(config.secret_key(), salt="mealplanner-session")
    return _signer


# --------------------------------------------------------------------------- password + rate limiting

_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILS, WINDOW = 8, 15 * 60


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check_password(request: Request, password: str) -> bool:
    ip = client_ip(request)
    now = time.time()
    _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW]
    if len(_failures[ip]) >= MAX_FAILS:
        raise HTTPException(429, "Too many wrong passwords. Try again in 15 minutes.")
    if config.APP_PASSWORD and hmac.compare_digest(password.encode(), config.APP_PASSWORD.encode()):
        _failures.pop(ip, None)
        return True
    _failures[ip].append(now)
    return False


def make_session_cookie() -> str:
    return signer().sign(b"miguel").decode()


def session_valid(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    if not token:
        return False
    try:
        signer().unsign(token, max_age=config.SESSION_DAYS * 86400)
        return True
    except (BadSignature, SignatureExpired):
        return False


def require_session(request: Request):
    if not session_valid(request):
        raise HTTPException(401, "Not logged in")


def set_session_cookie(response, request: Request):
    # Secure when the request came in over HTTPS (through the proxy), so plain-HTTP LAN access still works.
    secure = request.url.scheme == "https"
    response.set_cookie(COOKIE, make_session_cookie(), max_age=config.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")


# --------------------------------------------------------------------------- OAuth provider

class OAuthProvider:
    """Single-user OAuth authorisation server backed by SQLite.

    Claude registers itself (dynamic client registration), sends the user to
    /oauth/login where the app password is entered, and gets tokens back.
    """

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with db.session() as conn:
            r = conn.execute("SELECT data FROM oauth_clients WHERE client_id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(r["data"]) if r else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with db.session() as conn:
            conn.execute("INSERT OR REPLACE INTO oauth_clients(client_id, data, created_at) VALUES(?,?,?)",
                         (client_info.client_id, client_info.model_dump_json(), db.now_iso()))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        req_id = secrets.token_urlsafe(24)
        with db.session() as conn:
            conn.execute("DELETE FROM oauth_pending WHERE created_at < ?", (time.time() - 3600,))
            conn.execute("INSERT INTO oauth_pending(id, client_id, params, created_at) VALUES(?,?,?,?)",
                         (req_id, client.client_id, params.model_dump_json(), time.time()))
        return f"{config.BASE_URL}/oauth/login?req={req_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        with db.session() as conn:
            r = conn.execute("SELECT data, expires_at FROM oauth_codes WHERE code=?", (authorization_code,)).fetchone()
        if not r or r["expires_at"] < time.time():
            return None
        code = AuthorizationCode.model_validate_json(r["data"])
        return code if code.client_id == client.client_id else None

    def _issue(self, conn, client_id: str, scopes: list[str], resource: str | None) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        now = int(time.time())
        a_exp = now + config.ACCESS_TOKEN_DAYS * 86400
        r_exp = now + config.REFRESH_TOKEN_DAYS * 86400
        conn.execute("INSERT INTO oauth_tokens(token,kind,client_id,scopes,resource,expires_at,pair,created_at)"
                     " VALUES(?,?,?,?,?,?,?,?)",
                     (access, "access", client_id, json.dumps(scopes), resource, a_exp, refresh, db.now_iso()))
        conn.execute("INSERT INTO oauth_tokens(token,kind,client_id,scopes,resource,expires_at,pair,created_at)"
                     " VALUES(?,?,?,?,?,?,?,?)",
                     (refresh, "refresh", client_id, json.dumps(scopes), resource, r_exp, access, db.now_iso()))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=a_exp - now,
                          scope=" ".join(scopes), refresh_token=refresh)

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with db.session() as conn:
            deleted = conn.execute("DELETE FROM oauth_codes WHERE code=?", (authorization_code.code,)).rowcount
            if not deleted:
                raise TokenError("invalid_grant", "authorization code already used")
            return self._issue(conn, client.client_id, authorization_code.scopes or [SCOPE],
                               authorization_code.resource)

    def _load_token(self, token: str, kind: str):
        with db.session() as conn:
            r = conn.execute("SELECT * FROM oauth_tokens WHERE token=? AND kind=?", (token, kind)).fetchone()
        if not r or (r["expires_at"] and r["expires_at"] < time.time()):
            return None
        return dict(r)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        r = self._load_token(refresh_token, "refresh")
        if not r or r["client_id"] != client.client_id:
            return None
        return RefreshToken(token=r["token"], client_id=r["client_id"], scopes=json.loads(r["scopes"] or "[]"),
                            expires_at=r["expires_at"], resource=r["resource"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken,
                                     scopes: list[str]) -> OAuthToken:
        with db.session() as conn:
            old = conn.execute("SELECT pair FROM oauth_tokens WHERE token=?", (refresh_token.token,)).fetchone()
            conn.execute("DELETE FROM oauth_tokens WHERE token=?", (refresh_token.token,))
            if old and old["pair"]:
                conn.execute("DELETE FROM oauth_tokens WHERE token=?", (old["pair"],))
            return self._issue(conn, client.client_id, scopes or refresh_token.scopes or [SCOPE],
                               refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        r = self._load_token(token, "access")
        if not r:
            return None
        return AccessToken(token=r["token"], client_id=r["client_id"], scopes=json.loads(r["scopes"] or "[]"),
                           expires_at=r["expires_at"], resource=r["resource"])

    async def revoke_token(self, token) -> None:
        with db.session() as conn:
            r = conn.execute("SELECT pair FROM oauth_tokens WHERE token=?", (token.token,)).fetchone()
            conn.execute("DELETE FROM oauth_tokens WHERE token=?", (token.token,))
            if r and r["pair"]:
                conn.execute("DELETE FROM oauth_tokens WHERE token=?", (r["pair"],))


def complete_authorization(req_id: str) -> str:
    """Turn a pending /authorize request into an authorization code; returns the redirect URL."""
    with db.session() as conn:
        r = conn.execute("SELECT * FROM oauth_pending WHERE id=?", (req_id,)).fetchone()
        if not r or r["created_at"] < time.time() - 3600:
            raise HTTPException(400, "This sign-in link has expired. Start the connection again from Claude.")
        params = AuthorizationParams.model_validate_json(r["params"])
        code = AuthorizationCode(
            code=secrets.token_urlsafe(32),
            scopes=params.scopes or [SCOPE],
            expires_at=time.time() + 600,
            client_id=r["client_id"],
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        conn.execute("INSERT INTO oauth_codes(code, data, expires_at) VALUES(?,?,?)",
                     (code.code, code.model_dump_json(), code.expires_at))
        conn.execute("DELETE FROM oauth_pending WHERE id=?", (req_id,))
    return construct_redirect_uri(str(params.redirect_uri), code=code.code, state=params.state)


def pending_client_name(req_id: str) -> str | None:
    with db.session() as conn:
        r = conn.execute("SELECT client_id FROM oauth_pending WHERE id=?", (req_id,)).fetchone()
        if not r:
            return None
        c = conn.execute("SELECT data FROM oauth_clients WHERE client_id=?", (r["client_id"],)).fetchone()
    if not c:
        return "An app"
    return json.loads(c["data"]).get("client_name") or "An app"


def revoke_all_tokens():
    with db.session() as conn:
        conn.execute("DELETE FROM oauth_tokens")


# --------------------------------------------------------------------------- tiny HTML pages

def page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>
<link rel="stylesheet" href="/static/styles.css"></head>
<body class="plain"><main class="auth-card">{body}</main></body></html>"""


def login_form(action: str, heading: str, sub: str, error: str = "", hidden: dict | None = None,
               button: str = "Sign in", password: bool = True) -> str:
    hidden_inputs = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
                            for k, v in (hidden or {}).items())
    err = f'<p class="auth-error">{html.escape(error)}</p>' if error else ""
    pw = ('<label class="field"><span>Password</span><input type="password" name="password" '
          'autocomplete="current-password" required autofocus></label>') if password else ""
    return page(heading, f"""
<div class="auth-logo">🍳</div><h1>{html.escape(heading)}</h1><p class="muted">{sub}</p>{err}
<form method="post" action="{html.escape(action)}">{hidden_inputs}{pw}
<button class="btn primary wide" type="submit">{html.escape(button)}</button></form>""")
