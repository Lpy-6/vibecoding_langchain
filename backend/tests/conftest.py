"""
Shared test fixtures.

Critical: environment variables MUST be set before importing app.* so tests use
an isolated temporary SQLite database and the offline mock answer generator
(never the real DashScope API or the demo database).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="rag-pytest-"))
os.environ.update(
    {
        "DATA_DIR": str(TEST_DATA_DIR),
        "LLM_MODE": "mock",
        "DASHSCOPE_API_KEY": "",
        "JWT_SECRET": "pytest-only-secret-key-please-change-1234567890",
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD": "123456",
        "SEED_DEMO_USER": "true",
        "RATE_LIMIT_CHAT_PER_MIN": "10000",
        "RATE_LIMIT_LOGIN_PER_MIN": "10000",
        "RATE_LIMIT_REGISTER_PER_MIN": "10000",
        "INGEST_WORKERS": "2",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

API = "/api/v1"


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "admin", "123456")


@pytest.fixture(scope="session")
def demo_headers(client: TestClient) -> dict[str, str]:
    return _login(client, "demo", "demo123")


@pytest.fixture(scope="session")
def demo_user_id(client: TestClient, admin_headers: dict[str, str]) -> str:
    response = client.get(f"{API}/admin/users", headers=admin_headers, params={"q": "demo"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    return items[0]["id"]


def parse_sse(response) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event: str | None = None
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line == "":
            if event and data_lines:
                events.append((event, json.loads("\n".join(data_lines))))
            event, data_lines = None, []
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if event and data_lines:
        events.append((event, json.loads("\n".join(data_lines))))
    return events


def chat(
    client: TestClient,
    headers: dict[str, str],
    question: str,
    kb_ids: list[str] | None = None,
    conversation_id: str | None = None,
    use_cache: bool = False,
) -> dict:
    payload = {
        "question": question,
        "kb_ids": kb_ids or [],
        "conversation_id": conversation_id,
        "use_cache": use_cache,
    }
    with client.stream("POST", f"{API}/chat/stream", headers=headers, json=payload) as response:
        assert response.status_code == 200, response.read().decode("utf-8", errors="replace")
        events = parse_sse(response)
    tokens = [data.get("delta", "") for name, data in events if name == "token"]
    sources = next((data.get("sources", []) for name, data in events if name == "sources"), [])
    done = next((data for name, data in events if name == "done"), {})
    return {"events": events, "answer": "".join(tokens), "sources": sources, "done": done}


def wait_task(client: TestClient, headers: dict[str, str], task_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"{API}/admin/tasks/{task_id}", headers=headers)
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"completed", "failed"}:
            return task
        time.sleep(0.2)
    raise AssertionError(f"任务 {task_id} 在 {timeout}s 内未完成")


@pytest.fixture(scope="session")
def seeded_kb(client: TestClient, admin_headers: dict[str, str]) -> dict:
    """A public KB with one ingested document, shared by chat/retrieval tests."""
    response = client.post(
        f"{API}/admin/kbs",
        headers=admin_headers,
        json={"name": "pytest 商品知识库", "description": "automated tests", "is_public": True},
    )
    assert response.status_code == 201, response.text
    kb = response.json()
    content = (
        "星辰 X9 旗舰手机售价 8888 元，整机保修 3 年。\n"
        "星辰 X9 支持 IP68 防尘防水、NFC 和 5G 双卡双待。\n"
        "七天无理由退货需商品完好、配件齐全，退回运费由买家承担。"
    )
    upload = client.post(
        f"{API}/admin/kbs/{kb['id']}/documents",
        headers=admin_headers,
        files={"files": ("pytest_product.txt", content.encode("utf-8"), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    item = upload.json()["items"][0]
    task = wait_task(client, admin_headers, item["task"]["id"])
    assert task["status"] == "completed", task
    chunks = client.get(f"{API}/admin/documents/{item['document']['id']}/chunks", headers=admin_headers)
    assert chunks.status_code == 200 and chunks.json()["total"] > 0
    return {"kb": kb, "document": item["document"], "content": content}


@pytest.fixture(scope="session")
def private_kb(client: TestClient, admin_headers: dict[str, str]) -> dict:
    response = client.post(
        f"{API}/admin/kbs",
        headers=admin_headers,
        json={"name": "pytest 私有知识库", "description": "permission tests", "is_public": False},
    )
    assert response.status_code == 201, response.text
    return response.json()


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
