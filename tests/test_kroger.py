import httpx
import pytest
from pydantic import SecretStr

from household.kroger import KrogerClient, KrogerError


def test_client_uses_catalog_only_and_caches_token():
    calls = []

    def endpoint(request):
        calls.append(request)
        if request.url.path.endswith("/token"):
            assert request.method == "POST"
            assert request.content == b"grant_type=client_credentials&scope=product.compact"
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 1800})
        assert request.method == "GET" and request.url.path == "/v1/products"
        assert request.url.params["filter.locationId"] == "70600153"
        return httpx.Response(200, json={"data": []})

    api = KrogerClient("id", SecretStr("secret"), transport=httpx.MockTransport(endpoint))
    assert api.search("heavy cream") == []
    assert api.search("milk") == []
    assert len([r for r in calls if r.url.path.endswith("/token")]) == 1


def test_errors_never_expose_provider_body_or_tokens():
    def endpoint(request):
        return httpx.Response(401, text="private-secret private-token")

    api = KrogerClient("id", SecretStr("secret"), transport=httpx.MockTransport(endpoint))
    with pytest.raises(KrogerError) as error:
        api.search("milk")
    assert "private" not in str(error.value)
