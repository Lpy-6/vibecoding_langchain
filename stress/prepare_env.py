"""
压测环境准备：对运行在 8001 端口的隔离后端灌入种子知识库并批量注册压测用户。

前置：由 run_stress.bat 以压测环境变量（DATA_DIR=data_stress、LLM_MODE=mock 等）启动后端后调用。

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe stress/prepare_env.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

BASE = os.environ.get("STRESS_BASE", "http://127.0.0.1:8001")
API = f"{BASE}/api/v1"
USER_COUNT = int(os.environ.get("STRESS_USER_COUNT", "100"))
USER_PASSWORD = "Stress@123456"
TOKENS_PATH = Path(__file__).parent / "tokens.json"
DOC_TIMEOUT_SECONDS = 120


def login(client: httpx.Client, username: str, password: str) -> str:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()["access_token"]


def seed_knowledge_base(client: httpx.Client, admin_headers: dict) -> str:
    from scripts.seed_demo import _write_demo_files

    kbs = client.get("/kbs", headers=admin_headers).json()
    for kb in kbs:
        if kb["name"] == "商品知识库" and kb.get("doc_count", 0) > 0:
            print(f"知识库已存在：{kb['id']}（{kb.get('doc_count')} 文档）")
            return kb["id"]

    if any(kb["name"] == "商品知识库" for kb in kbs):
        kb_id = next(kb["id"] for kb in kbs if kb["name"] == "商品知识库")
    else:
        created = client.post(
            "/admin/kbs",
            headers=admin_headers,
            json={"name": "商品知识库", "description": "压测用电商商品知识库", "is_public": True},
        )
        created.raise_for_status()
        kb_id = created.json()["id"]

    files = _write_demo_files()
    task_ids: list[str] = []
    for title, (path, _source_type, mime) in files.items():
        data = path.read_bytes()
        upload = client.post(
            f"/admin/kbs/{kb_id}/documents",
            headers=admin_headers,
            files={"files": (path.name, data, mime)},
        )
        if upload.status_code != 201:
            print(f"  上传失败 {title}: {upload.status_code} {upload.text[:200]}")
            continue
        for item in upload.json()["items"]:
            task_ids.append(item["task"]["id"])
        print(f"  上传：{title}")

    deadline = time.time() + DOC_TIMEOUT_SECONDS
    pending = set(task_ids)
    while pending and time.time() < deadline:
        for task_id in list(pending):
            task = client.get(f"/admin/tasks/{task_id}", headers=admin_headers).json()
            if task["status"] in {"completed", "failed"}:
                pending.discard(task_id)
                if task["status"] == "failed":
                    print(f"  解析失败：{task_id} {str(task.get('error'))[:120]}")
        if pending:
            time.sleep(0.5)
    if pending:
        raise RuntimeError(f"{len(pending)} 个解析任务超时")
    print(f"知识库就绪：{kb_id}（{len(task_ids)} 个文档解析完成）")
    return kb_id


def create_users(client: httpx.Client) -> dict[str, str]:
    tokens: dict[str, str] = {}
    if TOKENS_PATH.exists():
        tokens = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    for i in range(1, USER_COUNT + 1):
        username = f"stress_user_{i:03d}"
        if username in tokens:
            continue
        resp = client.post(
            "/auth/register",
            json={"username": username, "password": USER_PASSWORD, "display_name": f"压测用户{i}"},
        )
        if resp.status_code == 201:
            token = resp.json()["access_token"]
        else:
            token = login(client, username, USER_PASSWORD)
        tokens[username] = token
        if i % 25 == 0:
            print(f"  已准备 {i}/{USER_COUNT} 个用户")
    TOKENS_PATH.write_text(json.dumps(tokens, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"用户令牌已写入 {TOKENS_PATH.name}（{len(tokens)} 个）")
    return tokens


def main() -> None:
    health = httpx.get(f"{BASE}/health", timeout=10)
    health.raise_for_status()
    with httpx.Client(base_url=API, timeout=60) as client:
        admin_token = login(client, "admin", "123456")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        seed_knowledge_base(client, admin_headers)
        create_users(client)
    print("压测环境准备完成。")


if __name__ == "__main__":
    main()
