import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from authlib.integrations.httpx_client._compat import httpx2
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import RSAKey


@pytest.mark.parametrize(
    "invalid", [None, "nonce", "audience", "issuer", "expired", "signature", "state"]
)
def test_real_oidc_validation_with_controlled_google_endpoints(app, invalid):
    key = RSAKey.generate_key(parameters={"kid": "test-key"})
    authorization = {}
    exchanged = []

    def endpoint(request):
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(
                200,
                json={
                    "issuer": "https://accounts.google.com",
                    "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_endpoint": "https://oauth2.googleapis.com/token",
                    "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
            )
        if url.endswith("/certs"):
            return httpx2.Response(200, json={"keys": [key.as_dict()]})
        assert url == "https://oauth2.googleapis.com/token"
        params = parse_qs(request.content.decode())
        exchanged.append(params)
        verifier = params["code_verifier"][0]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        assert challenge == authorization["code_challenge"][0]
        now = int(time.time())
        claims = {
            "iss": "https://accounts.google.com",
            "aud": "test-client",
            "sub": "google-0",
            "iat": now,
            "exp": now + 600,
            "nonce": authorization["nonce"][0],
            "email": "member0@example.com",
            "email_verified": True,
            "name": "Member 0",
        }
        if invalid == "nonce":
            claims["nonce"] = "wrong"
        if invalid == "audience":
            claims["aud"] = "another-client"
        if invalid == "issuer":
            claims["iss"] = "https://attacker.example"
        if invalid == "expired":
            claims["exp"] = now - 1000
        signing_key = (
            RSAKey.generate_key(parameters={"kid": "test-key"}) if invalid == "signature" else key
        )
        token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, signing_key)
        return httpx2.Response(
            200,
            json={
                "access_token": "fixture-access-token",
                "token_type": "Bearer",
                "expires_in": 600,
                "id_token": token,
            },
        )

    app.state.oauth.google.client_kwargs["transport"] = httpx2.MockTransport(endpoint)
    with TestClient(app, base_url="http://localhost:8001") as c:
        login = c.get("/auth/login", follow_redirects=False)
        assert login.status_code == 302
        authorization.update(parse_qs(urlsplit(login.headers["location"]).query))
        assert authorization["code_challenge_method"] == ["S256"]
        assert set(authorization["scope"][0].split()) == {"openid", "email", "profile"}
        state = "wrong-state" if invalid == "state" else authorization["state"][0]
        callback = c.get(f"/auth/callback?code=fixture-code&state={state}", follow_redirects=False)
        if invalid:
            assert callback.status_code == 400
            assert c.get("/api/me").status_code == 401
        else:
            assert callback.status_code == 303
            assert c.get("/api/me").json()["display_name"] == "Member 0"
            assert "HttpOnly" in callback.headers["set-cookie"]
        if invalid == "state":
            assert not exchanged
