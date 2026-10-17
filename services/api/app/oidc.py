"""Bounded OIDC transport and strict ID-token verification.

Provider tokens exist only in request memory. Only a hash of the separate local
session credential is persisted by auth_routes; JWTs never become API credentials.
"""

import asyncio
import json
import math
from urllib.parse import urlsplit

import httpx
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from authlib.oidc.core import CodeIDToken
from authlib.oidc.core.claims import HybridIDToken
from joserfc.errors import ClaimError

from app.config import Settings, valid_url
from app.database import utcnow


class OIDCError(Exception):
    """A deliberately generic error: never include tokens or upstream responses."""


def public_endpoint(url: str, settings: Settings) -> str:
    """All discovered endpoints must stay under the configured issuer prefix."""
    issuer = settings.oidc_issuer.rstrip("/")
    if not isinstance(url, str) or not valid_url(url) or not url.startswith(issuer + "/"):
        raise OIDCError()
    expected, actual = urlsplit(issuer), urlsplit(url)
    if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
        raise OIDCError()
    return url


def transport_endpoint(url: str, settings: Settings) -> str:
    url = public_endpoint(url, settings)
    if settings.oidc_internal_base_url:
        # Never rewrite arbitrary hosts. Configuration permits this only locally;
        # validating here also protects callers that bypass startup validation.
        if settings.environment not in {"development", "test"}:
            raise OIDCError()
        if not valid_url(settings.oidc_internal_base_url):
            raise OIDCError()
        prefix = settings.oidc_issuer.rstrip("/")
        return settings.oidc_internal_base_url.rstrip("/") + url[len(prefix):]
    return url


class OIDCClient:
    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0), follow_redirects=False, trust_env=False,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.client.aclose()

    async def request_json(self, method: str, url: str, *, data=None, auth=None, max_bytes=65_536) -> dict:
        try:
            # The total deadline also stops a slow trickle that never hits the
            # per-read HTTP timeout; stream limits include decompressed bytes.
            async with asyncio.timeout(10):
                async with self.client.stream(
                    method, transport_endpoint(url, self.settings), data=data, auth=auth,
                    headers={"Accept": "application/json"},
                ) as response:
                    if response.status_code != 200:
                        raise OIDCError()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise OIDCError()
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise OIDCError()
                    return result
        except (httpx.HTTPError, TimeoutError, ValueError, UnicodeError):
            raise OIDCError() from None

    async def discovery(self) -> dict:
        metadata = await self.request_json(
            "GET", self.settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
        )
        if metadata.get("issuer") != self.settings.oidc_issuer:
            raise OIDCError()
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            public_endpoint(metadata.get(key), self.settings)
        for key, required in (
            ("response_types_supported", "code"),
            ("code_challenge_methods_supported", "S256"),
            ("id_token_signing_alg_values_supported", "RS256"),
        ):
            values = metadata.get(key)
            if not isinstance(values, list) or required not in values:
                raise OIDCError()
        if self.settings.oidc_client_secret and "client_secret_basic" not in metadata.get(
            "token_endpoint_auth_methods_supported", ["client_secret_basic"]
        ):
            raise OIDCError()
        return metadata

    async def exchange(self, metadata: dict, code: str, verifier: str, nonce: str) -> dict:
        data = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": self.settings.callback_url, "code_verifier": verifier,
        }
        auth = None
        if self.settings.oidc_client_secret:
            auth = httpx.BasicAuth(self.settings.oidc_client_id, self.settings.oidc_client_secret)
        else:
            data["client_id"] = self.settings.oidc_client_id
        tokens = await self.request_json("POST", metadata["token_endpoint"], data=data, auth=auth)
        if (
            not isinstance(tokens.get("id_token"), str) or not 0 < len(tokens["id_token"]) <= 32_768
            or not isinstance(tokens.get("access_token"), str)
            or not 0 < len(tokens["access_token"]) <= 32_768
            or not tokens["access_token"].isascii()
            or not isinstance(tokens.get("token_type"), str) or tokens["token_type"].lower() != "bearer"
        ):
            raise OIDCError()
        jwks = await self.request_json("GET", metadata["jwks_uri"], max_bytes=131_072)
        return validate_id_token(tokens["id_token"], jwks, self.settings, nonce, code, tokens["access_token"])


def validate_id_token(token: str, jwks: dict, settings: Settings, nonce: str, code: str, access_token: str) -> dict:
    """Verify RS256 signature, OIDC claims and optional token/code hashes."""
    try:
        if not isinstance(token, str) or not 0 < len(token) <= 32_768 or token.count(".") != 2:
            raise OIDCError()
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not 0 < len(keys) <= 32:
            raise OIDCError()

        def signing_key(header, _payload):
            if header.get("alg") != "RS256" or any(key in header for key in ("jku", "jwk", "x5u")):
                raise OIDCError()
            kid = header.get("kid")
            if kid is not None and (not isinstance(kid, str) or not kid or len(kid) > 255):
                raise OIDCError()
            candidates = [
                item for item in keys if isinstance(item, dict) and item.get("kty") == "RSA"
                and item.get("use", "sig") == "sig" and item.get("alg", "RS256") == "RS256"
                and ("key_ops" not in item or "verify" in item["key_ops"])
                and (kid is None or item.get("kid") == kid)
            ]
            if len(candidates) != 1:
                raise OIDCError()
            key = JsonWebKey.import_key(candidates[0])
            if key.get_op_key("verify").key_size < 2048:
                raise OIDCError()
            return key

        claims = JsonWebToken(["RS256"]).decode(
            token, signing_key, claims_cls=CodeIDToken,
            claims_options={
                "iss": {"essential": True, "value": settings.oidc_issuer},
                "aud": {"essential": True, "value": settings.oidc_client_id},
            },
            claims_params={"nonce": nonce, "client_id": settings.oidc_client_id,
                           "code": code, "access_token": access_token},
        )
        now = utcnow().timestamp()
        for field in ("exp", "iat"):
            value = claims.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise OIDCError()
        if (
            claims["exp"] <= now or claims["exp"] <= claims["iat"]
            or claims["iat"] < now - settings.oidc_flow_ttl_seconds - 30
        ):
            raise OIDCError()
        subject = claims.get("sub")
        if (
            not isinstance(subject, str) or not subject or len(subject) > 255
            or any(ord(char) < 32 for char in subject)
        ):
            raise OIDCError()
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if (
            not isinstance(audiences, list) or not 0 < len(audiences) <= 16
            or any(not isinstance(item, str) or not item for item in audiences)
            or settings.oidc_client_id not in audiences
            or (len(audiences) > 1 and claims.get("azp") != settings.oidc_client_id)
            or ("azp" in claims and claims["azp"] != settings.oidc_client_id)
        ):
            raise OIDCError()
        for field in ("at_hash", "c_hash"):
            if field in claims and (not isinstance(claims[field], str) or len(claims[field]) != 22):
                raise OIDCError()
        claims.validate(now=now, leeway=30)
        # CodeIDToken validates at_hash; c_hash is optional in the code flow,
        # but its presence still requires verification against the redeemed code.
        if "c_hash" in claims:
            HybridIDToken.validate_c_hash(claims)
        return dict(claims)
    except (JoseError, ClaimError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise OIDCError() from None
