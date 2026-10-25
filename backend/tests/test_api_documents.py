from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.conftest import API, chat, wait_task


def _create_kb(client: TestClient, headers, name: str, public: bool = True) -> dict:
    response = client.post(
        f"{API}/admin/kbs",
        headers=headers,
        json={"name": name, "description": "pytest", "is_public": public},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _upload_text(client: TestClient, headers, kb_id: str, filename: str, content: str):
    return client.post(
        f"{API}/admin/kbs/{kb_id}/documents",
        headers=headers,
        files={"files": (filename, content.encode("utf-8"), "text/plain")},
    )


def test_upload_dedupe_reindex_query_delete(client: TestClient, admin_headers):
    kb = _create_kb(client, admin_headers, f"pytest 摄入库 {time.time_ns()}")
    content = "银河 Z1 平板售价 6666 元，整机保修 5 年。\n银河 Z1 支持 33W 快充。"
    first = _upload_text(client, admin_headers, kb["id"], "galaxy_z1.txt", content)
    assert first.status_code == 201, first.text
    item = first.json()["items"][0]
    document_id = item["document"]["id"]
    task = wait_task(client, admin_headers, item["task"]["id"])
    assert task["status"] == "completed", task

    document = client.get(f"{API}/admin/documents/{document_id}", headers=admin_headers)
    assert document.status_code == 200
    assert document.json()["status"] == "ready"
    assert document.json()["chunk_count"] > 0

    duplicate = _upload_text(client, admin_headers, kb["id"], "galaxy_z1_copy.txt", content)
    assert duplicate.status_code == 201
    assert "galaxy_z1_copy.txt" in duplicate.json()["duplicates"]
    assert duplicate.json()["items"] == []

    reindex = client.post(f"{API}/admin/documents/{document_id}/reindex", headers=admin_headers)
    assert reindex.status_code == 200, reindex.text
    reindex_task = wait_task(client, admin_headers, reindex.json()["task"]["id"])
    assert reindex_task["status"] == "completed", reindex_task
    assert client.get(f"{API}/admin/documents/{document_id}", headers=admin_headers).json()["status"] == "ready"

    answer = chat(client, admin_headers, "银河 Z1 售价多少？", kb_ids=[kb["id"]], use_cache=False)
    assert "6666" in answer["answer"]
    assert answer["sources"]

    assert client.delete(f"{API}/admin/documents/{document_id}", headers=admin_headers).status_code == 200
    listed = client.get(f"{API}/admin/kbs/{kb['id']}/documents", headers=admin_headers)
    assert listed.status_code == 200 and listed.json()["total"] == 0

    assert client.delete(f"{API}/admin/kbs/{kb['id']}", headers=admin_headers).status_code == 200


def test_private_kb_permission_grant_and_revoke(
    client: TestClient, admin_headers, demo_headers, demo_user_id, private_kb
):
    kb_id = private_kb["id"]
    demo_ids = {item["id"] for item in client.get(f"{API}/kbs", headers=demo_headers).json()}
    assert kb_id not in demo_ids
    assert client.get(f"{API}/kbs/{kb_id}", headers=demo_headers).status_code == 403

    granted = client.put(
        f"{API}/admin/kbs/{kb_id}/permissions",
        headers=admin_headers,
        json={"user_ids": [demo_user_id]},
    )
    assert granted.status_code == 200
    demo_ids = {item["id"] for item in client.get(f"{API}/kbs", headers=demo_headers).json()}
    assert kb_id in demo_ids
    assert client.get(f"{API}/kbs/{kb_id}", headers=demo_headers).status_code == 200

    revoked = client.put(
        f"{API}/admin/kbs/{kb_id}/permissions",
        headers=admin_headers,
        json={"user_ids": []},
    )
    assert revoked.status_code == 200
    assert client.get(f"{API}/kbs/{kb_id}", headers=demo_headers).status_code == 403


def test_url_import_rejects_ssrf(client: TestClient, admin_headers, private_kb):
    response = client.post(
        f"{API}/admin/kbs/{private_kb['id']}/documents/url",
        headers=admin_headers,
        json={"url": "http://127.0.0.1:8000/healthz", "title": "ssrf"},
    )
    assert response.status_code == 400
    assert "不允许" in response.json()["detail"] or "本机" in response.json()["detail"]

    invalid_scheme = client.post(
        f"{API}/admin/kbs/{private_kb['id']}/documents/url",
        headers=admin_headers,
        json={"url": "file:///etc/passwd"},
    )
    assert invalid_scheme.status_code == 422


def test_upload_rejects_disallowed_extension(client: TestClient, admin_headers):
    kb = _create_kb(client, admin_headers, f"pytest 校验库 {time.time_ns()}")
    response = client.post(
        f"{API}/admin/kbs/{kb['id']}/documents",
        headers=admin_headers,
        files={"files": ("malware.exe", b"MZ...", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "不支持" in response.json()["detail"]
    client.delete(f"{API}/admin/kbs/{kb['id']}", headers=admin_headers)
