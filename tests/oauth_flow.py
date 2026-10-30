"""End-to-end OAuth + MCP check against a running server (used by tests and for manual checks).

Usage: python tests/oauth_flow.py http://localhost:8411 PASSWORD
"""

import base64
import hashlib
import json
import secrets
import sys
from urllib.parse import parse_qs, urlparse

import httpx


def oauth_token(base: str, password: str, auth_method: str = "client_secret_post", client=None) -> dict:
    c = client or httpx.Client(base_url=base, follow_redirects=False, timeout=20)
    meta = c.get("/.well-known/oauth-authorization-server").json()
    redirect = "https://claude.ai/api/mcp/auth_callback"
    reg = c.post(meta["registration_endpoint"], json={
        "client_name": "Claude", "redirect_uris": [redirect], "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"], "token_endpoint_auth_method": auth_method}).json()
    assert "client_id" in reg, reg
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(8)
    r = c.get(meta["authorization_endpoint"], params={
        "response_type": "code", "client_id": reg["client_id"], "redirect_uri": redirect,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "scope": "mealplanner", "resource": f"{base}/mcp"})
    assert r.status_code in (302, 307), (r.status_code, r.text)
    login_url = r.headers["location"]
    req_id = parse_qs(urlparse(login_url).query)["req"][0]
    page = c.get(f"/oauth/login?req={req_id}")
    assert page.status_code == 200 and "Allow access" in page.text, page.text[:300]
    if 'type="password"' in page.text:  # not already logged in to the web app
        bad = c.post("/oauth/login", data={"req": req_id, "password": "wrong"})
        assert bad.status_code == 401
    r = c.post("/oauth/login", data={"req": req_id, "password": password})
    assert r.status_code == 302, (r.status_code, r.text[:300])
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["state"][0] == state
    data = {"grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": redirect,
            "client_id": reg["client_id"], "code_verifier": verifier}
    if reg.get("client_secret"):
        data["client_secret"] = reg["client_secret"]
    tok = c.post(meta["token_endpoint"], data=data)
    assert tok.status_code == 200, tok.text
    tok = tok.json()
    # refresh works and rotates
    rdata = {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": reg["client_id"]}
    if reg.get("client_secret"):
        rdata["client_secret"] = reg["client_secret"]
    ref = c.post(meta["token_endpoint"], data=rdata)
    assert ref.status_code == 200, ref.text
    return ref.json()


def mcp_call(c: httpx.Client, token: str, method: str, params: dict | None = None, id_: int = 1):
    r = c.post("/mcp", headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
                                "MCP-Protocol-Version": "2025-06-18"},
               json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    assert r.status_code == 200, (r.status_code, r.text[:500])
    body = r.json()
    assert "error" not in body, body
    return body["result"]


def tool(c, token, name, args=None):
    res = mcp_call(c, token, "tools/call", {"name": name, "arguments": args or {}})
    text = res["content"][0]["text"]
    if res.get("isError"):
        raise RuntimeError(f"{name}: {text}")
    return json.loads(text)


if __name__ == "__main__":
    base, pw = sys.argv[1], sys.argv[2]
    c = httpx.Client(base_url=base, follow_redirects=False, timeout=20)
    for method in ("client_secret_post", "none"):
        t = oauth_token(base, pw, method, c)
        print(method, "-> token ok")
    init = mcp_call(c, t["access_token"], "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    print("server:", init["serverInfo"], "protocol:", init["protocolVersion"])
    tools = mcp_call(c, t["access_token"], "tools/list")["tools"]
    print(len(tools), "tools:", ", ".join(x["name"] for x in tools))
    ctx = tool(c, t["access_token"], "get_planning_context")
    print("context keys:", list(ctx))
