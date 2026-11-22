from fastapi.testclient import TestClient

from household.api import create_app
from household.config import Settings


def test_signin_entry_points_redirect_to_configured_host_before_setting_state():
    app = create_app(
        Settings(
            _env_file=None,
            database_url="postgresql://unused",
            family_allowed_emails=",".join(f"member{i}@example.com" for i in range(5)),
            google_client_id="test-client",
            google_client_secret="test-secret",
            session_secret="test-secret-with-at-least-32-characters",
            public_base_url="http://localhost:8001",
        )
    )
    with TestClient(app, base_url="https://alternate.example") as c:
        for path in ["/", "/signin", "/auth/login"]:
            response = c.get(path, follow_redirects=False)
            assert response.status_code == 303
            assert response.headers["location"] == "http://localhost:8001" + path
            assert "household_oauth=" not in response.headers.get("set-cookie", "")
