import pytest
from fastapi.testclient import TestClient

import app.core.url_safety as url_safety
from app.main import app as fastapi_app


@pytest.fixture()
def client(monkeypatch):
    # Scan creation must not depend on Redis (rate limiting) or a running
    # Dramatiq broker (enqueue) in unit tests.
    import app.api.v1.scans as scans_module

    monkeypatch.setattr(scans_module, "enqueue_scan", lambda scan_id: None)
    monkeypatch.setattr(scans_module, "enforce_scan_creation_rate_limit", lambda user_id: None)
    return TestClient(fastapi_app)


def _resolve_to_public_ip(monkeypatch, ip="93.184.216.34"):
    monkeypatch.setattr(url_safety, "resolve_hostname", lambda hostname, resolver=None: [ip])


def _resolve_to_private_ip(monkeypatch, ip="10.0.0.5"):
    monkeypatch.setattr(url_safety, "resolve_hostname", lambda hostname, resolver=None: [ip])


def _login(client, email, password="correct-horse-battery-staple"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp


# --- auth --------------------------------------------------------------------------


def test_login_success_allows_authenticated_request(client, user):
    _login(client, user.email)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == user.email


def test_login_wrong_password_rejected(client, user):
    resp = client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"})
    assert resp.status_code == 401


def test_me_requires_authentication(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


# --- scan creation -------------------------------------------------------------------


def test_create_scan_requires_authorization_acknowledgment(client, user):
    _login(client, user.email)
    resp = client.post(
        "/api/v1/scans",
        json={"target_input": "example.com", "max_pages": 10, "authorization_acknowledgment": False},
    )
    assert resp.status_code == 422


def test_create_scan_succeeds_for_public_domain(client, user, monkeypatch):
    _resolve_to_public_ip(monkeypatch)
    _login(client, user.email)
    resp = client.post(
        "/api/v1/scans",
        json={
            "target_input": "example.com",
            "notes": "Evaluating for acquisition.",
            "max_pages": 10,
            "authorization_acknowledgment": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["normalized_domain"] == "example.com"
    assert body["status"] == "queued"
    assert body["user_id"] is not None


def test_create_scan_rejects_target_resolving_to_private_ip(client, user, monkeypatch):
    _resolve_to_private_ip(monkeypatch)
    _login(client, user.email)
    resp = client.post(
        "/api/v1/scans",
        json={"target_input": "internal.example.com", "max_pages": 10, "authorization_acknowledgment": True},
    )
    assert resp.status_code == 422
    assert "private or reserved" in resp.json()["detail"]


def test_create_scan_rejects_localhost(client, user):
    _login(client, user.email)
    resp = client.post(
        "/api/v1/scans",
        json={"target_input": "http://localhost:8000/", "max_pages": 10, "authorization_acknowledgment": True},
    )
    assert resp.status_code == 422


def test_create_scan_rejects_invalid_max_pages(client, user):
    _login(client, user.email)
    resp = client.post(
        "/api/v1/scans",
        json={"target_input": "example.com", "max_pages": 17, "authorization_acknowledgment": True},
    )
    assert resp.status_code == 422


# --- ownership / authorization ------------------------------------------------------


def test_user_cannot_view_another_users_scan(client, user, admin_user, monkeypatch, db):
    _resolve_to_public_ip(monkeypatch)
    _login(client, user.email)
    create_resp = client.post(
        "/api/v1/scans",
        json={"target_input": "example.com", "max_pages": 10, "authorization_acknowledgment": True},
    )
    scan_id = create_resp.json()["id"]

    other_client = TestClient(fastapi_app)
    _login(other_client, admin_user.email)
    # Admins CAN view any scan.
    resp = other_client.get(f"/api/v1/scans/{scan_id}")
    assert resp.status_code == 200


def test_non_owner_non_admin_cannot_view_scan(client, user, organization, db, monkeypatch):
    from app.models.user import User
    from app.security.passwords import hash_password

    other_user = User(
        organization_id=organization.id,
        email="another-member@example.com",
        hashed_password=hash_password("correct-horse-battery-staple"),
        full_name="Other Member",
        role="member",
        is_active=True,
    )
    db.add(other_user)
    db.commit()

    _resolve_to_public_ip(monkeypatch)
    _login(client, user.email)
    create_resp = client.post(
        "/api/v1/scans",
        json={"target_input": "example.com", "max_pages": 10, "authorization_acknowledgment": True},
    )
    scan_id = create_resp.json()["id"]

    other_client = TestClient(fastapi_app)
    _login(other_client, other_user.email)
    resp = other_client.get(f"/api/v1/scans/{scan_id}")
    assert resp.status_code == 403


def test_list_scans_only_returns_own_by_default(client, user, monkeypatch):
    _resolve_to_public_ip(monkeypatch)
    _login(client, user.email)
    client.post(
        "/api/v1/scans",
        json={"target_input": "example.com", "max_pages": 10, "authorization_acknowledgment": True},
    )
    resp = client.get("/api/v1/scans")
    assert resp.status_code == 200
    scans = resp.json()
    assert len(scans) == 1
    assert all(s["normalized_domain"] == "example.com" for s in scans)


def test_scan_endpoints_require_authentication():
    anon_client = TestClient(fastapi_app)
    assert anon_client.get("/api/v1/scans").status_code == 401
    assert anon_client.post("/api/v1/scans", json={}).status_code == 401


def test_health_endpoint_is_public():
    anon_client = TestClient(fastapi_app)
    resp = anon_client.get("/health")
    assert resp.status_code in (200, 503)
    assert "checks" in resp.json()
