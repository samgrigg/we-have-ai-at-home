"""Read-only Kroger catalog access. No customer OAuth or cart operations."""

import threading
import time

import httpx


class KrogerError(ValueError):
    pass


class KrogerClient:
    def __init__(self, client_id, client_secret, location_id="70600153", transport=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.location_id = location_id
        self.transport = transport
        self._token = None
        self._expires = 0
        self._lock = threading.Lock()

    def search(self, term):
        if not self.client_id or not self.client_secret:
            raise KrogerError("Smith’s product search is not configured yet.")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=5),
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with self._lock:
                    if not self._token or time.monotonic() >= self._expires:
                        response = client.post(
                            "https://api.kroger.com/v1/connect/oauth2/token",
                            auth=(self.client_id, self.client_secret.get_secret_value()),
                            data={"grant_type": "client_credentials", "scope": "product.compact"},
                        )
                        if response.status_code != 200:
                            raise KrogerError(
                                "Kroger authentication failed. Check the server credentials "
                                "and product API access."
                            )
                        payload = response.json()
                        self._token = payload["access_token"]
                        self._expires = time.monotonic() + max(
                            0, min(float(payload["expires_in"]), 86400) - 60
                        )
                    token = self._token
                response = client.get(
                    "https://api.kroger.com/v1/products",
                    headers={"Authorization": "Bearer " + token},
                    params={
                        "filter.term": term,
                        "filter.locationId": self.location_id,
                        "filter.limit": 30,
                    },
                )
                if response.status_code != 200:
                    if response.status_code == 401:
                        with self._lock:
                            self._expires = 0
                    raise KrogerError("Kroger product search is unavailable. Try again later.")
                products = response.json()["data"]
                if not isinstance(products, list):
                    raise ValueError()
                return products[:30]
        except KrogerError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise KrogerError(
                "Kroger product search could not be completed. Try again later."
            ) from exc
