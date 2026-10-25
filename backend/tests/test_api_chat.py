from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import API, chat


def test_chat_sse_order_citations_and_message_order(client: TestClient, admin_headers, seeded_kb):
    result = chat(
        client,
        admin_headers,
        "星辰 X9 支持 IP68 防水吗？",
        kb_ids=[seeded_kb["kb"]["id"]],
    )
    names = [name for name, _ in result["events"]]
    assert names[0] == "meta"
    assert "sources" in names and "token" in names
    assert names[-1] == "done"
    assert names.index("sources") < names.index("token") < names.index("done")

    assert "IP68" in result["answer"]
    assert result["sources"], "检索应返回引用片段"
    assert result["done"]["used_citations"], "回答应标注有效引用编号"

    conversation_id = result["done"]["conversation_id"]
    messages = client.get(f"{API}/conversations/{conversation_id}/messages", headers=admin_headers)
    assert messages.status_code == 200
    items = messages.json()["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assistant = items[1]
    assert assistant["citations"], "引用快照应持久化"
    assert any(citation["used"] for citation in assistant["citations"])

    citations = client.get(f"{API}/messages/{assistant['id']}/citations", headers=admin_headers)
    assert citations.status_code == 200
    assert len(citations.json()) >= 1


def test_semantic_cache_hit_on_repeat(client: TestClient, admin_headers, seeded_kb):
    client.delete(f"{API}/admin/cache", headers=admin_headers)
    question = "星辰 X9 的整机保修期是多久？"
    first = chat(client, admin_headers, question, kb_ids=[seeded_kb["kb"]["id"]], use_cache=True)
    assert first["done"]["cache_hit"] is False
    assert "3 年" in first["answer"]

    second = chat(client, admin_headers, question, kb_ids=[seeded_kb["kb"]["id"]], use_cache=True)
    assert second["done"]["cache_hit"] is True
    assert any(name == "cache" for name, _ in second["events"])
    assert second["answer"] == first["answer"]


def test_feedback_upsert_and_delete(client: TestClient, admin_headers, seeded_kb):
    result = chat(client, admin_headers, "星辰 X9 的售价是多少？", kb_ids=[seeded_kb["kb"]["id"]])
    conversation_id = result["done"]["conversation_id"]
    items = client.get(f"{API}/conversations/{conversation_id}/messages", headers=admin_headers).json()["items"]
    assistant = next(item for item in items if item["role"] == "assistant")

    up = client.post(f"{API}/messages/{assistant['id']}/feedback", headers=admin_headers, json={"rating": 1})
    assert up.status_code == 200
    items = client.get(f"{API}/conversations/{conversation_id}/messages", headers=admin_headers).json()["items"]
    assert next(item for item in items if item["id"] == assistant["id"])["feedback"] == 1

    down = client.post(f"{API}/messages/{assistant['id']}/feedback", headers=admin_headers, json={"rating": -1})
    assert down.status_code == 200
    items = client.get(f"{API}/conversations/{conversation_id}/messages", headers=admin_headers).json()["items"]
    assert next(item for item in items if item["id"] == assistant["id"])["feedback"] == -1

    deleted = client.delete(f"{API}/messages/{assistant['id']}/feedback", headers=admin_headers)
    assert deleted.status_code == 200


def test_user_conversation_isolation(client: TestClient, admin_headers, demo_headers, seeded_kb):
    kb_id = seeded_kb["kb"]["id"]
    demo_chat = chat(client, demo_headers, "星辰 X9 多少钱？", kb_ids=[kb_id])
    demo_conv = demo_chat["done"]["conversation_id"]

    admin_chat = chat(client, admin_headers, "星辰 X9 防水等级？", kb_ids=[kb_id])
    admin_conv = admin_chat["done"]["conversation_id"]

    assert client.get(f"{API}/conversations/{demo_conv}/messages", headers=admin_headers).status_code == 404
    assert client.get(f"{API}/conversations/{admin_conv}/messages", headers=demo_headers).status_code == 404

    admin_ids = {c["id"] for c in client.get(f"{API}/conversations", headers=admin_headers).json()["items"]}
    demo_ids = {c["id"] for c in client.get(f"{API}/conversations", headers=demo_headers).json()["items"]}
    assert demo_conv not in admin_ids
    assert admin_conv not in demo_ids


def test_conversation_crud_and_persistence(client: TestClient, demo_headers, seeded_kb):
    created = client.post(
        f"{API}/conversations",
        headers=demo_headers,
        json={"title": "pytest 会话", "kb_ids": [seeded_kb["kb"]["id"]]},
    )
    assert created.status_code == 201
    conv = created.json()

    renamed = client.patch(f"{API}/conversations/{conv['id']}", headers=demo_headers, json={"title": "pytest 重命名"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "pytest 重命名"

    listed = client.get(f"{API}/conversations", headers=demo_headers, params={"q": "重命名"})
    assert listed.status_code == 200
    assert any(item["id"] == conv["id"] for item in listed.json()["items"])

    messages = client.get(f"{API}/conversations/{conv['id']}/messages", headers=demo_headers)
    assert messages.status_code == 200 and messages.json()["items"] == []

    assert client.delete(f"{API}/conversations/{conv['id']}", headers=demo_headers).status_code == 200
    assert client.get(f"{API}/conversations/{conv['id']}/messages", headers=demo_headers).status_code == 404
