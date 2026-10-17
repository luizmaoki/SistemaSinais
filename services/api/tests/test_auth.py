"""Security checks through the real HTTP OIDC transport and RSA verifier."""
import asyncio
import base64
import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.jose import JsonWebKey, JsonWebToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import DEMO_TENANT_ID, DEMO_USER_ID, FLOW_COOKIE, SESSION_COOKIE, token_hash
from app.auth_routes import consume_flow
from app.config import Settings, get_settings
from app.database import Base, build_engine, utcnow
from app.ingestion import evaluate_alerts
from app.main import app
from app.models import Alert, AlertRule, Asset, AuthFlow, AuthSession, User
from app.oidc import OIDCClient, OIDCError, public_endpoint, transport_endpoint

ISSUER = "http://localhost:18080/realms/capital"
PREFIX = "/api/v1/auth"


def encoded_hash(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:16]).rstrip(b"=").decode()


def oidc_settings(**overrides):
    values = dict(
        APP_ENV="test", auth_mode="oidc", demo_mode=True, oidc_issuer=ISSUER,
        oidc_client_id="capital-web", auth_public_base_url="http://localhost:3000",
        cors_origins="http://localhost:3000", session_cookie_secure=False,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(scope="module")
def signing_keys():
    return [
        JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "fixture-rsa"})
        for _ in range(2)
    ]


class ProviderFixture:
    def __init__(self, settings, key):
        self.settings, self.key = settings, key
        self.claim_overrides = {}
        self.remove_claims = []
        self.token_error = False
        self.algorithm = "RS256"
        self.sign_key = key
        self.headers = {}
        self.requests = []
        self.token_requests = 0
        self.nonce = None
        self.challenge = None
        self.id_token = None
        self.metadata = {
            "issuer": settings.oidc_issuer,
            "authorization_endpoint": settings.oidc_issuer + "/protocol/openid-connect/auth",
            "token_endpoint": settings.oidc_issuer + "/protocol/openid-connect/token",
            "jwks_uri": settings.oidc_issuer + "/protocol/openid-connect/certs",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=self.metadata)
        if request.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": [self.key.as_dict(is_private=False)]})
        assert request.method == "POST" and request.url.path.endswith("/token")
        self.token_requests += 1
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["redirect_uri"] == [self.settings.callback_url]
        verifier = form["code_verifier"][0]
        actual = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        assert actual == self.challenge
        if self.settings.oidc_client_secret:
            assert request.headers["authorization"].startswith("Basic ")
            assert "client_secret" not in form
        else:
            assert form["client_id"] == [self.settings.oidc_client_id]
            assert "authorization" not in request.headers
        if self.token_error:
            return httpx.Response(400, json={"error_description": "NEVER_EXPOSE_PROVIDER_SECRET"})
        now = int(utcnow().timestamp())
        self.claims = {
            "iss": self.settings.oidc_issuer, "sub": "person-1",
            "aud": self.settings.oidc_client_id, "azp": self.settings.oidc_client_id,
            "iat": now, "exp": now + 300, "nonce": self.nonce, "name": "Pessoa OIDC",
            "at_hash": encoded_hash("fixture-access"), "c_hash": encoded_hash(form["code"][0]),
            "role": "admin", "tenant_id": DEMO_TENANT_ID,
        }
        self.claims.update(self.claim_overrides)
        for field in self.remove_claims:
            self.claims.pop(field, None)
        self.id_token = JsonWebToken([self.algorithm]).encode(
            {"alg": self.algorithm, "kid": "fixture-rsa", **self.headers}, self.claims, self.sign_key,
        ).decode()
        return httpx.Response(200, json={
            "id_token": self.id_token, "access_token": "fixture-access",
            "refresh_token": "NEVER_PERSIST_REFRESH", "token_type": "Bearer",
        })


@pytest.fixture
def oidc(client, monkeypatch, signing_keys):
    settings = oidc_settings()
    provider = ProviderFixture(settings, signing_keys[0])
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr("app.main.settings", settings)
    monkeypatch.setattr(
        "app.auth_routes.OIDCClient",
        lambda configuration: OIDCClient(configuration, transport=httpx.MockTransport(provider)),
    )
    return client, provider, settings


def set_cookie(client, name, value, path):
    client.cookies.set(name, value, domain="testserver.local", path=path)


def start_login(oidc):
    client, provider, _ = oidc
    response = client.get(PREFIX + "/login?next=https://evil.example", follow_redirects=False)
    assert response.status_code == 302
    parts = urlsplit(response.headers["location"])
    assert parts.scheme == "http" and parts.netloc == "localhost:18080"
    values = {name: items[0] for name, items in parse_qs(parts.query).items()}
    provider.nonce = values["nonce"]
    provider.challenge = values["code_challenge"]
    return values, response


def finish_login(oidc, values=None, **query):
    client, _, settings = oidc
    if values is None:
        values, _ = start_login(oidc)
    params = {"state": values["state"], "code": "fixture-code", "iss": settings.oidc_issuer, **query}
    return client.get(PREFIX + "/callback", params=params, follow_redirects=False)


def session_data(oidc):
    assert finish_login(oidc).headers["location"] == "/dashboard"
    result = oidc[0].get(PREFIX + "/session")
    assert result.status_code == 200
    return result.json()


def test_demo_contract_and_logout(client):
    assert client.get(PREFIX + "/config").json() == {
        "auth_mode": "demo", "configured": True, "demo_available": True, "login_path": PREFIX + "/login",
    }
    session = client.get(PREFIX + "/session").json()
    assert session["mode"] == "DEMO" and session["auth_mode"] == "demo"
    assert session["csrf_token"] is None and session["tenant_id"] == DEMO_TENANT_ID
    assert client.post(PREFIX + "/logout", json={}).json() == {"logged_out": True}


def test_oidc_has_no_anonymous_demo_or_bearer_fallback(oidc):
    client, _, _ = oidc
    config = client.get(PREFIX + "/config").json()
    assert config["configured"] is True and config["demo_available"] is False
    assert config["auth_mode"] == "oidc"
    for path in (PREFIX + "/session", "/api/v1/assets", "/api/v1/watchlists", "/api/v1/alerts"):
        assert client.get(path, headers={
            "Authorization": "Bearer arbitrary", "X-User-ID": DEMO_USER_ID,
        }).status_code == 401
    assert client.get("/api/v1/health").status_code == 200


def test_pkce_browser_binding_and_hashed_flow(oidc, db):
    client, _, settings = oidc
    values, response = start_login(oidc)
    assert values["response_type"] == "code"
    assert values["code_challenge_method"] == "S256" and values["prompt"] == "login"
    assert values["redirect_uri"] == settings.callback_url
    assert values["scope"] == "openid profile" and "next" not in values
    binding = client.cookies[FLOW_COOKIE]
    assert binding != values["state"] and binding != values["nonce"]
    flow = db.get(AuthFlow, token_hash(values["state"]))
    assert flow.binding_hash == token_hash(binding) and len(flow.code_verifier) == 86
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1/auth" in cookie
    assert "code_verifier" not in response.headers["location"]


def test_success_identity_session_rotation_and_no_provider_tokens(oidc, db):
    client, provider, _ = oidc
    result = finish_login(oidc)
    assert result.headers["location"] == "/dashboard"
    cookie = next(value for value in result.headers.get_list("set-cookie") if value.startswith(SESSION_COOKIE + "="))
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api/v1;" in cookie
    assert FLOW_COOKIE not in client.cookies
    opaque = client.cookies[SESSION_COOKIE]
    saved = db.get(AuthSession, token_hash(opaque))
    assert saved.id_hash != opaque and saved.expires_at.timestamp() <= provider.claims["exp"]
    data = client.get(PREFIX + "/session").json()
    assert data["mode"] == "AUTHENTICATED" and data["auth_mode"] == "oidc"
    assert data["role"] == "owner" and data["user"]["name"] == "Pessoa OIDC"
    assert data["tenant_id"] != DEMO_TENANT_ID and data["user"]["id"] != DEMO_USER_ID
    assert len(data["csrf_token"]) == 43 and data["expires_at"]
    assert client.get("/api/v1/watchlists").json()["items"] == []
    stored = repr([dict(row) for table in (AuthSession.__table__, AuthFlow.__table__, User.__table__)
                   for row in db.execute(select(table)).mappings()])
    for secret in (provider.id_token, "fixture-access", "NEVER_PERSIST_REFRESH", opaque):
        assert secret not in stored
    assert finish_login(oidc).headers["location"] == "/dashboard"
    assert client.cookies[SESSION_COOKIE] != opaque
    assert db.get(AuthSession, token_hash(opaque)) is None
    assert db.scalar(select(func.count()).select_from(User).where(User.oidc_subject == "person-1")) == 1


def test_state_replay_wrong_browser_and_expiry(oidc, db):
    client, provider, _ = oidc
    values, _ = start_login(oidc)
    binding = client.cookies[FLOW_COOKIE]
    client.cookies.clear()
    set_cookie(client, FLOW_COOKIE, values["state"], "/api/v1/auth")
    assert finish_login(oidc, values).headers["location"] == "/login?auth_error=login_failed"
    assert provider.token_requests == 0
    set_cookie(client, FLOW_COOKIE, binding, "/api/v1/auth")
    assert finish_login(oidc, values).headers["location"] == "/dashboard"
    set_cookie(client, FLOW_COOKIE, binding, "/api/v1/auth")
    assert finish_login(oidc, values).headers["location"] == "/login?auth_error=login_failed"
    assert provider.token_requests == 1
    values, _ = start_login(oidc)
    db.get(AuthFlow, token_hash(values["state"])).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert finish_login(oidc, values).headers["location"] == "/login?auth_error=login_failed"
    assert provider.token_requests == 1


@pytest.mark.parametrize("query", [
    {"code": ""}, {"iss": "https://evil.example"}, {"error": "access_denied"},
    {"code": "x" * 4097}, {"code": "\ninvalid"},
])
def test_bad_callback_consumes_flow_without_exchange(oidc, db, query):
    values, _ = start_login(oidc)
    assert finish_login(oidc, values, **query).headers["location"] == "/login?auth_error=login_failed"
    assert oidc[1].token_requests == 0
    assert db.scalar(select(AuthFlow).where(AuthFlow.state_hash == token_hash(values["state"]))) is None


def test_duplicate_callback_params_rejected(oidc):
    values, _ = start_login(oidc)
    result = oidc[0].get(PREFIX + "/callback", params=[
        ("state", values["state"]), ("code", "one"), ("code", "two"),
    ], follow_redirects=False)
    assert result.headers["location"] == "/login?auth_error=login_failed" and oidc[1].token_requests == 0


@pytest.mark.parametrize("claim,value", [
    ("iss", "https://evil.example"), ("aud", "another-client"),
    ("aud", ["capital-web", 123]), ("aud", []), ("azp", "another-client"), ("azp", ""),
    ("nonce", "wrong-nonce"), ("sub", ""), ("sub", 123), ("sub", "x" * 256),
    ("exp", 1), ("exp", "300"), ("exp", True), ("iat", 1), ("iat", True),
    ("iat", 99999999999), ("at_hash", "x" * 22), ("at_hash", ""),
    ("c_hash", "x" * 22), ("c_hash", ""), ("nbf", 99999999999),
])
def test_bad_id_token_claims_never_create_session(oidc, db, claim, value):
    oidc[1].claim_overrides[claim] = value
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"
    assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
    assert db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize("missing", ["iss", "sub", "aud", "exp", "iat", "nonce"])
def test_missing_required_claims_rejected(oidc, missing):
    oidc[1].remove_claims = [missing]
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"


def test_multiple_audience_requires_matching_azp(oidc):
    oidc[1].claim_overrides["aud"] = ["capital-web", "other"]
    oidc[1].remove_claims = ["azp"]
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"
    oidc[1].remove_claims = []
    assert finish_login(oidc).headers["location"] == "/dashboard"


def test_bad_signature_disallowed_algorithm_and_embedded_key_rejected(oidc, signing_keys):
    provider = oidc[1]
    provider.sign_key = signing_keys[1]
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"
    provider.sign_key = b"symmetric-test-secret-with-adequate-length"
    provider.algorithm = "HS256"
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"
    provider.sign_key, provider.algorithm = signing_keys[0], "RS256"
    provider.headers["jku"] = "https://evil.example/keys"
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"


def test_csrf_rbac_revocation_and_expiration(oidc, db):
    client, _, _ = oidc
    data = session_data(oidc)
    csrf = {"X-CSRF-Token": data["csrf_token"], "Origin": "http://localhost:3000"}
    body = {"name": "Private"}
    assert client.post("/api/v1/watchlists", json=body).status_code == 403
    assert client.post("/api/v1/watchlists", json=body, headers={"X-CSRF-Token": "x" * 43}).status_code == 403
    assert client.post("/api/v1/watchlists", json=body, headers={**csrf, "Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/v1/watchlists", json=body, headers={**csrf, "Origin": ""}).status_code == 403
    created = client.post("/api/v1/watchlists", json=body, headers=csrf)
    assert created.status_code == 201
    db.get(User, data["user"]["id"]).role = "viewer"
    db.commit()
    assert client.get("/api/v1/watchlists").status_code == 200
    asset = db.scalar(select(Asset))
    writes = [
        ("post", "/api/v1/watchlists", body),
        ("post", f"/api/v1/watchlists/{created.json()['id']}/assets", {"asset_id": asset.id}),
        ("delete", f"/api/v1/watchlists/{created.json()['id']}/assets/{asset.id}", None),
        ("post", "/api/v1/alert-rules", {"asset_id": asset.id, "threshold": 1, "direction": "above"}),
        ("patch", "/api/v1/alert-rules/00000000-0000-4000-8000-000000000100", {"enabled": False}),
    ]
    for method, path, payload in writes:
        assert client.request(method, path, json=payload, headers=csrf).status_code == 403
    assert client.post(PREFIX + "/logout", json={}).status_code == 403
    opaque = client.cookies[SESSION_COOKIE]
    assert client.post(PREFIX + "/logout", json={}, headers=csrf).json() == {"logged_out": True}
    assert SESSION_COOKIE not in client.cookies
    set_cookie(client, SESSION_COOKIE, opaque, "/api/v1")
    assert client.get(PREFIX + "/session").status_code == 401
    session_data(oidc)
    opaque = client.cookies[SESSION_COOKIE]
    db.get(AuthSession, token_hash(opaque)).expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    result = client.get(PREFIX + "/session")
    assert result.status_code == 401 and result.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert db.get(AuthSession, token_hash(opaque)) is None


def test_personal_data_isolated_for_two_oidc_users(oidc, db):
    client, provider, _ = oidc
    first = session_data(oidc)
    csrf1 = {"X-CSRF-Token": first["csrf_token"]}
    asset = db.scalar(select(Asset).where(Asset.symbol == "NVDA"))
    watchlist = client.post("/api/v1/watchlists", json={"name": "Personal One"}, headers=csrf1).json()
    rule = client.post("/api/v1/alert-rules", headers=csrf1, json={
        "asset_id": asset.id, "threshold": 1, "direction": "above",
    }).json()
    assert len(client.get("/api/v1/alerts").json()["items"]) == 1
    provider.claim_overrides.update(sub="person-2", name="Pessoa OIDC")
    second = session_data(oidc)
    assert first["user"]["id"] != second["user"]["id"] and first["tenant_id"] != second["tenant_id"]
    csrf2 = {"X-CSRF-Token": second["csrf_token"], "X-Tenant-ID": first["tenant_id"], "X-User-ID": first["user"]["id"]}
    for path in ("/api/v1/watchlists", "/api/v1/alert-rules", "/api/v1/alerts"):
        assert client.get(path, headers=csrf2).json()["items"] == []
    assert client.post(f"/api/v1/watchlists/{watchlist['id']}/assets", json={"asset_id": asset.id}, headers=csrf2).status_code == 404
    assert client.delete(f"/api/v1/watchlists/{watchlist['id']}/assets/{asset.id}", headers=csrf2).status_code == 404
    assert client.patch(f"/api/v1/alert-rules/{rule['id']}", json={"enabled": False}, headers=csrf2).status_code == 404
    assert client.post("/api/v1/watchlists", json={"name": "Spoof", "tenant_id": first["tenant_id"]}, headers=csrf2).status_code == 422


def test_inactive_account_denied_and_worker_skips_rules(oidc, db):
    client, _, _ = oidc
    data = session_data(oidc)
    user = db.get(User, data["user"]["id"])
    asset = db.scalar(select(Asset).where(Asset.symbol == "NVDA"))
    db.add(AlertRule(tenant_id=user.tenant_id, user_id=user.id, asset_id=asset.id,
                     threshold=1, direction="above", source_id="demo"))
    user.active = False
    db.commit()
    assert client.get(PREFIX + "/session").status_code == 403
    assert evaluate_alerts(db) == 0
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"


def test_unknown_role_and_demo_identity_cannot_receive_oidc_session(oidc, db):
    data = session_data(oidc)
    user = db.get(User, data["user"]["id"])
    user.role = "admin"
    db.commit()
    assert oidc[0].get("/api/v1/assets").status_code == 403
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"
    user.role, user.tenant_id = "owner", DEMO_TENANT_ID
    db.commit()
    assert oidc[0].get("/api/v1/assets").status_code == 401
    assert finish_login(oidc).headers["location"] == "/login?auth_error=login_failed"


def test_upstream_failure_is_generic_and_consumes_state(oidc, capsys):
    oidc[1].token_error = True
    values, _ = start_login(oidc)
    binding = oidc[0].cookies[FLOW_COOKIE]
    result = finish_login(oidc, values)
    assert result.headers["location"] == "/login?auth_error=login_failed"
    assert "NEVER_EXPOSE_PROVIDER_SECRET" not in result.text + str(result.headers) + capsys.readouterr().out
    set_cookie(oidc[0], FLOW_COOKIE, binding, "/api/v1/auth")
    assert finish_login(oidc, values).headers["location"] == "/login?auth_error=login_failed"
    assert oidc[1].token_requests == 1


def test_atomic_flow_consumption_across_sessions(tmp_path):
    engine = build_engine("sqlite:///" + str(tmp_path / "parallel.db"))
    Base.metadata.create_all(engine)
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with Session(engine) as db:
        db.add(AuthFlow(state_hash=token_hash(state), binding_hash=token_hash(binding),
                        nonce=secrets.token_urlsafe(32), code_verifier=secrets.token_urlsafe(64),
                        expires_at=utcnow() + timedelta(minutes=5)))
        db.commit()
    barrier = Barrier(2)

    def consume(_):
        with Session(engine) as db:
            barrier.wait()
            return consume_flow(db, state, binding) is not None

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(consume, range(2))) == [False, True]
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", [
    "http://evil.example/token", ISSUER + "-evil/token", ISSUER + "/../token",
    ISSUER + "/%2e%2e/token", ISSUER + "//token", ISSUER + "/token?redirect=evil",
    "http://localhost:18080@evil.example/realms/capital/token",
])
def test_discovery_endpoint_scope_cannot_escape_issuer(url):
    with pytest.raises(OIDCError):
        public_endpoint(url, oidc_settings())


def test_internal_mapping_rewrites_only_configured_prefix():
    settings = oidc_settings(oidc_internal_base_url="http://keycloak:8080/realms/capital")
    assert transport_endpoint(ISSUER + "/protocol/token", settings) == "http://keycloak:8080/realms/capital/protocol/token"
    with pytest.raises(OIDCError):
        transport_endpoint(ISSUER + "-evil/token", settings)
    settings.environment = "production"
    with pytest.raises(OIDCError):
        transport_endpoint(ISSUER + "/protocol/token", settings)


@pytest.mark.parametrize("kind", ["redirect", "oversize", "invalid_json", "not_object", "timeout"])
def test_transport_has_bounded_responses_and_no_redirects(kind):
    seen = []

    def handler(request):
        seen.append(request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://evil.example/"})
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 65_537)
        if kind == "invalid_json":
            return httpx.Response(200, content=b"{invalid")
        if kind == "not_object":
            return httpx.Response(200, json=[])
        raise httpx.ReadTimeout("private server detail")

    async def run():
        async with OIDCClient(oidc_settings(), transport=httpx.MockTransport(handler)) as provider:
            await provider.discovery()

    with pytest.raises(OIDCError):
        asyncio.run(run())
    assert len(seen) == 1


@pytest.mark.parametrize("key,value", [
    ("issuer", "https://wrong.example"), ("jwks_uri", "http://evil.example/certs"),
    ("token_endpoint", ISSUER + "-evil/token"), ("authorization_endpoint", "http://evil.example/auth"),
    ("code_challenge_methods_supported", ["plain"]), ("id_token_signing_alg_values_supported", ["HS256"]),
    ("response_types_supported", ["token"]),
])
def test_discovery_metadata_invalid_fails_closed(oidc, key, value):
    oidc[1].metadata[key] = value
    response = oidc[0].get(PREFIX + "/login", follow_redirects=False)
    assert response.headers["location"] == "/login?auth_error=login_failed"


def production_settings(**overrides):
    values = dict(
        APP_ENV="production", auth_mode="oidc", demo_mode=False, oidc_issuer="https://id.example/realm",
        oidc_client_id="capital-web", oidc_client_secret="fixture-client-secret",
        auth_public_base_url="https://app.example", cors_origins="https://app.example",
        allowed_hosts="app.example,api", session_cookie_secure=True,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_valid_config_and_secret_hidden():
    settings = production_settings()
    settings.assert_auth_ready()
    assert settings.demo_available is False and "fixture-client-secret" not in repr(settings)


@pytest.mark.parametrize("values", [
    {"demo_mode": True}, {"session_cookie_secure": False}, {"oidc_client_secret": ""},
    {"oidc_issuer": "http://localhost:18080/realm"},
    {"oidc_issuer": "https://id.example/realm#fragment"},
    {"auth_public_base_url": "http://app.example"},
    {"cors_origins": "*"}, {"cors_origins": "https://another.example"},
    {"allowed_hosts": "*"}, {"allowed_hosts": ""},
    {"oidc_internal_base_url": "http://keycloak:8080/realm"},
])
def test_production_invalid_config_fails_closed(values):
    with pytest.raises(RuntimeError):
        production_settings(**values).assert_auth_ready()


def test_explicit_hosts_required_in_production():
    settings = production_settings()
    settings.__pydantic_fields_set__.discard("allowed_hosts")
    with pytest.raises(RuntimeError, match="explicit allowed hosts"):
        settings.assert_auth_ready()


@pytest.mark.parametrize("environment,demo_mode", [("production", True), ("production", False), ("test", False)])
def test_demo_is_never_a_production_bypass(environment, demo_mode):
    with pytest.raises(RuntimeError):
        Settings(_env_file=None, APP_ENV=environment, auth_mode="demo", demo_mode=demo_mode).assert_auth_ready()

