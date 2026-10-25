from __future__ import annotations

import time

from fastapi.testclient import TestClient

API = "/api/v1"


def test_admin_login_me_and_demo_rbac(client: TestClient, admin_headers, demo_headers):
    me = client.get(f"{API}/auth/me", headers=admin_headers)
    assert me.status_code == 200
    assert me.json()["role"] == "admin"

    demo_me = client.get(f"{API}/auth/me", headers=demo_headers)
    assert demo_me.status_code == 200
    assert demo_me.json()["role"] == "user"

    assert client.get(f"{API}/admin/kbs", headers=demo_headers).status_code == 403
    assert client.get(f"{API}/admin/kbs", headers=admin_headers).status_code == 200


def test_register_change_password_and_token_invalidation(client: TestClient):
    username = f"pytest_user_{time.time_ns()}"
    password = "oldpass123"
    register = client.post(
        f"{API}/auth/register",
        json={"username": username, "password": password, "display_name": "测试用户"},
    )
    assert register.status_code == 201, register.text
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert register.json()["user"]["role"] == "user"

    assert client.get(f"{API}/auth/me", headers=headers).status_code == 200

    changed = client.post(
        f"{API}/auth/password",
        headers=headers,
        json={"old_password": password, "new_password": "newpass456"},
    )
    assert changed.status_code == 200, changed.text

    # token_version bump invalidates the previously issued access token
    assert client.get(f"{API}/auth/me", headers=headers).status_code == 401

    old_login = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert old_login.status_code == 401
    new_login = client.post(f"{API}/auth/login", json={"username": username, "password": "newpass456"})
    assert new_login.status_code == 200


def test_register_rejects_short_password(client: TestClient):
    response = client.post(
        f"{API}/auth/register",
        json={"username": f"short_{time.time_ns()}", "password": "123"},
    )
    assert response.status_code == 422


def test_refresh_rotation(client: TestClient):
    login = client.post(f"{API}/auth/login", json={"username": "demo", "password": "demo123"})
    assert login.status_code == 200
    old_cookie = client.cookies.get("rag_refresh_token")
    assert old_cookie

    refreshed = client.post(f"{API}/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    # JWT access tokens can be identical when issued within the same second;
    # the rotation guarantee is about the opaque refresh token.
    assert refreshed.json()["access_token"]
    assert client.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    ).status_code == 200
    new_cookie = client.cookies.get("rag_refresh_token")
    assert new_cookie and new_cookie != old_cookie

    # The rotated token itself remains usable exactly once.
    assert client.post(f"{API}/auth/refresh").status_code == 200


def test_failed_login_is_audited(client: TestClient, admin_headers):
    response = client.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401
    logs = client.get(f"{API}/admin/audit-logs", headers=admin_headers, params={"action": "auth.login_failed"})
    assert logs.status_code == 200
    assert logs.json()["total"] >= 1


def test_admin_cannot_demote_self(client: TestClient, admin_headers):
    me = client.get(f"{API}/auth/me", headers=admin_headers).json()
    response = client.patch(f"{API}/admin/users/{me['id']}", headers=admin_headers, json={"role": "user"})
    assert response.status_code == 400


def test_health_and_metrics(client: TestClient):
    assert client.get("/healthz").status_code == 200
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["components"]["database"] == "ok"
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "rag_http_requests_total" in metrics.text


def test_auth_edge_cases(client: TestClient):
    username = f"edge_{time.time_ns()}"
    assert client.post(
        f"{API}/auth/register", json={"username": username, "password": "edgepass123"}
    ).status_code == 201
    assert client.post(
        f"{API}/auth/register", json={"username": username, "password": "edgepass123"}
    ).status_code == 409

    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.post(f"{API}/auth/login", json={"username": username, "password": "wrong"}).status_code == 401

    login = client.post(f"{API}/auth/login", json={"username": username, "password": "edgepass123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    wrong_old = client.post(
        f"{API}/auth/password",
        headers=headers,
        json={"old_password": "not-the-password", "new_password": "another123"},
    )
    assert wrong_old.status_code == 400
    assert client.post(f"{API}/auth/logout", headers=headers).status_code == 200

    client.cookies.clear()
    assert client.post(f"{API}/auth/refresh").status_code == 401


def test_chat_rejects_private_kb_without_permission(client: TestClient, demo_headers, private_kb):
    response = client.post(
        f"{API}/chat/stream",
        headers=demo_headers,
        json={"question": "测试", "kb_ids": [private_kb["id"]]},
    )
    assert response.status_code == 403
