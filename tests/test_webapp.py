import os
from fastapi.testclient import TestClient
import pytest
from unittest.mock import patch, MagicMock

# Set env var to enable the web app logic
os.environ['WEB_ENABLED'] = 'true'

# It's important to import the app *after* the env var is set
from src.webapp.server import app

@pytest.fixture
def client():
    """Test client for the FastAPI app."""
    return TestClient(app)

# --- Basic Page Rendering Tests ---

@patch('src.webapp.services.get_dashboard_stats')
def test_read_root(mock_get_stats, client):
    mock_get_stats.return_value = {'total_articles': 100, 'last_published_date': '2025-08-14', 'dlq_count': 5}
    response = client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text

def test_list_articles(client):
    response = client.get("/articles")
    assert response.status_code == 200
    # Calendar view is rendered instead of list
    assert "Календарь" in response.text or "calendar-grid" in response.text

def test_health_check(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _reload_app_with_env(env_overrides):
    from importlib import reload
    import src.webapp.server as server_module
    with patch.dict(os.environ, env_overrides, clear=False):
        reload(server_module)
        return TestClient(server_module.app)

@patch('src.webapp.services.get_duplicate_groups')
def test_list_duplicates(mock_get_duplicates, client):
    mock_get_duplicates.return_value = []
    response = client.get("/duplicates")
    assert response.status_code == 200
    assert "Группы дубликатов" in response.text

@patch('src.webapp.services.get_dlq_items')
def test_list_dlq(mock_get_dlq, client):
    mock_get_dlq.return_value = []
    response = client.get("/dlq")
    assert response.status_code == 200
    assert "Dead Letter Queue" in response.text

# --- New Tests from Action Plan ---

def test_static_css_loads(client):
    """Tests that the static CSS file is served correctly."""
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    # Check for key variables instead of exact formatting
    assert "--bg:" in response.text
    assert "--fg:" in response.text
    assert "body" in response.text

def test_security_headers_are_present(client):
    """Tests that security headers are added by the middleware."""
    response = client.get("/")
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"

@patch('src.webapp.services.get_month_calendar_data')
def test_articles_calendar_params(mock_get_calendar, client):
    """Tests that calendar params are passed to the service layer."""
    mock_get_calendar.return_value = {"year": 2025, "month": 2, "weeks": []}
    response = client.get("/articles?year=2025&month=2")
    assert response.status_code == 200
    mock_get_calendar.assert_called_with(2025, 2)

@patch.dict(os.environ, {"WEB_BASIC_AUTH_USER": "testuser", "WEB_BASIC_AUTH_PASSWORD": "testpass"})
def test_auth_is_enforced():
    """Tests that authentication is enforced when credentials are set."""
    # Need to re-import the app within the patched context
    from src.webapp.server import app
    client = TestClient(app)
    
    response = client.get("/")
    assert response.status_code == 401
    
    with patch('src.webapp.services.get_dashboard_stats') as mock_get_stats:
        mock_get_stats.return_value = {'total_articles': 0, 'last_published_date': 'N/A', 'dlq_count': 0}
        response_authed = client.get("/", auth=("testuser", "testpass"))
        assert response_authed.status_code == 200


def test_api_key_auth_enforced_when_enabled():
    env = {
        "WEB_ENABLED": "true",
        "WEB_API_ENABLED": "true",
        "WEB_API_KEY": "secret123",
        # No Basic auth
        "WEB_BASIC_AUTH_USER": "",
        "WEB_BASIC_AUTH_PASSWORD": "",
    }
    from importlib import reload
    import src.webapp.server as server_module
    with patch.dict(os.environ, env, clear=False):
        reload(server_module)
        client = TestClient(server_module.app)

        # Without key -> 401
        resp_no_key = client.get("/api/articles")
        assert resp_no_key.status_code == 401

        # With wrong key -> 401
        resp_bad = client.get("/api/articles", headers={"X-API-Key": "bad"})
        assert resp_bad.status_code == 401

        # With correct key in X-API-Key -> 200 (empty DB still OK)
        resp_ok = client.get("/api/articles", headers={"X-API-Key": "secret123"})
        assert resp_ok.status_code in (200, 204)

        # With Authorization: Api-Key <key>
        resp_ok2 = client.get("/api/articles", headers={"Authorization": "Api-Key secret123"})
        assert resp_ok2.status_code in (200, 204)


def test_api_routes_public_when_key_not_set():
    # Enable API but do not set key -> public access
    env = {
        "WEB_ENABLED": "true",
        "WEB_API_ENABLED": "true",
        "WEB_API_KEY": "",
        # No Basic auth
        "WEB_BASIC_AUTH_USER": "",
        "WEB_BASIC_AUTH_PASSWORD": "",
    }
    from importlib import reload
    import src.webapp.server as server_module
    with patch.dict(os.environ, env, clear=False):
        reload(server_module)
        client = TestClient(server_module.app)
        resp = client.get("/api/articles")
        assert resp.status_code in (200, 204)