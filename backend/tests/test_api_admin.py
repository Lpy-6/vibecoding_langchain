from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.conftest import API, chat, wait_task


def test_admin_kb_update_and_document_queries(client: TestClient, admin_headers):
    created = client.post(
        f"{API}/admin/kbs",
        headers=admin_headers,
        json={"name": f"pytest 管理库 {time.time_ns()}", "description": "old", "is_public": True},
    )
    assert created.status_code == 201, created.text
    kb = created.json()
    updated = client.patch(
        f"{API}/admin/kbs/{kb['id']}",
        headers=admin_headers,
        json={"description": "updated", "is_public": False},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "updated"
    assert updated.json()["is_public"] is False
    assert any(item["id"] == kb["id"] for item in client.get(f"{API}/admin/kbs", headers=admin_headers).json())

    upload = client.post(
        f"{API}/admin/kbs/{kb['id']}/documents",
        headers=admin_headers,
        files={"files": ("pytest_admin_doc.txt", b"admin document 8888", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    item = upload.json()["items"][0]
    document_id = item["document"]["id"]
    task = wait_task(client, admin_headers, item["task"]["id"])
    assert task["status"] == "completed"

    listed = client.get(
        f"{API}/admin/kbs/{kb['id']}/documents",
        headers=admin_headers,
        params={"q": "pytest_admin", "status": "ready"},
    )
    assert listed.status_code == 200 and listed.json()["total"] == 1

    chunks = client.get(
        f"{API}/admin/documents/{document_id}/chunks",
        headers=admin_headers,
        params={"chunk_type": "parent"},
    )
    assert chunks.status_code == 200 and chunks.json()["total"] >= 1

    assert client.get(f"{API}/admin/tasks/not-a-real-task", headers=admin_headers).status_code == 404
    assert client.get(f"{API}/admin/documents/not-a-real-doc", headers=admin_headers).status_code == 404
    assert client.delete(f"{API}/admin/documents/not-a-real-doc", headers=admin_headers).status_code == 404

    assert client.delete(f"{API}/admin/documents/{document_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"{API}/admin/kbs/{kb['id']}", headers=admin_headers).status_code == 200


def test_admin_user_lifecycle(client: TestClient, admin_headers):
    username = f"pflow_{time.time_ns()}"
    password = "flowpass123"
    created = client.post(
        f"{API}/auth/register",
        json={"username": username, "password": password, "display_name": "流程用户"},
    )
    assert created.status_code == 201
    users = client.get(f"{API}/admin/users", headers=admin_headers, params={"q": username}).json()["items"]
    assert len(users) == 1
    user_id = users[0]["id"]

    renamed = client.patch(
        f"{API}/admin/users/{user_id}", headers=admin_headers, json={"display_name": "已改名"}
    )
    assert renamed.status_code == 200 and renamed.json()["display_name"] == "已改名"

    assert client.patch(
        f"{API}/admin/users/{user_id}", headers=admin_headers, json={"is_active": False}
    ).status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": username, "password": password}).status_code == 403

    assert client.patch(
        f"{API}/admin/users/{user_id}", headers=admin_headers, json={"is_active": True}
    ).status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": username, "password": password}).status_code == 200

    reset = client.post(
        f"{API}/admin/users/{user_id}/reset-password",
        headers=admin_headers,
        json={"new_password": "resetpass456"},
    )
    assert reset.status_code == 200
    assert client.post(f"{API}/auth/login", json={"username": username, "password": password}).status_code == 401

    promoted = client.patch(f"{API}/admin/users/{user_id}", headers=admin_headers, json={"role": "admin"})
    assert promoted.status_code == 200
    login = client.post(f"{API}/auth/login", json={"username": username, "password": "resetpass456"})
    assert login.status_code == 200
    new_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get(f"{API}/admin/kbs", headers=new_headers).status_code == 200

    demoted = client.patch(f"{API}/admin/users/{user_id}", headers=admin_headers, json={"role": "user"})
    assert demoted.status_code == 200
    login = client.post(f"{API}/auth/login", json={"username": username, "password": "resetpass456"})
    new_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get(f"{API}/admin/kbs", headers=new_headers).status_code == 403


def test_admin_stats_feedback_audit_and_cache(client: TestClient, admin_headers, seeded_kb):
    result = chat(client, admin_headers, "星辰 X9 的保修有几年？", kb_ids=[seeded_kb["kb"]["id"]])
    conv_id = result["done"]["conversation_id"]
    messages = client.get(f"{API}/conversations/{conv_id}/messages", headers=admin_headers).json()["items"]
    assistant = next(item for item in messages if item["role"] == "assistant")
    assert client.post(
        f"{API}/messages/{assistant['id']}/feedback", headers=admin_headers, json={"rating": 1}
    ).status_code == 200

    overview = client.get(f"{API}/admin/stats/overview", headers=admin_headers)
    assert overview.status_code == 200
    body = overview.json()
    assert body["answers"] >= 1
    assert body["users"]["total"] >= 2
    assert body["cache"]["entries"] >= 0
    assert len(body["daily_questions"]) == 7

    qa = client.get(f"{API}/admin/stats/qa", headers=admin_headers)
    assert qa.status_code == 200 and qa.json()["total"] >= 1
    feedback = client.get(f"{API}/admin/feedback", headers=admin_headers)
    assert feedback.status_code == 200 and feedback.json()["total"] >= 1
    audit = client.get(f"{API}/admin/audit-logs", headers=admin_headers)
    assert audit.status_code == 200 and audit.json()["total"] >= 1

    cache_stats = client.get(f"{API}/admin/cache/stats", headers=admin_headers)
    assert cache_stats.status_code == 200
    assert client.delete(f"{API}/admin/cache", headers=admin_headers).status_code == 200

    system = client.get(f"{API}/admin/system", headers=admin_headers)
    assert system.status_code == 200
    assert system.json()["llm_mode"] == "mock"
    assert system.json()["embedding_provider"] == "offline-hashing-v1"
    assert system.json()["prompt_version"]
