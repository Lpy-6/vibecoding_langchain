"""
End-to-end smoke test against a running backend.

Usage:
    backend/.venv/Scripts/python.exe scripts/smoke_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
FAILURES: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        FAILURES.append(label)


def login(client: httpx.Client, username: str, password: str) -> dict:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def stream_chat(client: httpx.Client, headers: dict, question: str, kb_ids=None, use_cache=False) -> dict:
    answer: list[str] = []
    sources: list[dict] = []
    done: dict | None = None
    with client.stream(
        "POST",
        "/chat/stream",
        headers=headers,
        json={"question": question, "kb_ids": kb_ids or [], "use_cache": use_cache},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        event = None
        for line in resp.iter_lines():
            if not line:
                continue
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if event == "token":
                    answer.append(data.get("delta", ""))
                elif event == "sources":
                    sources = data.get("sources", [])
                elif event == "done":
                    done = data
    return {"answer": "".join(answer), "sources": sources, "done": done or {}}


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60) as client:
        print("\n[1] 认证与权限")
        admin = login(client, "admin", "123456")
        demo = login(client, "demo", "demo123")
        me = client.get("/auth/me", headers=admin).json()
        check(me["role"] == "admin", "管理员登录与 /auth/me")
        resp = client.get("/admin/kbs", headers=demo)
        check(resp.status_code == 403, "普通用户访问管理接口被拒绝", str(resp.status_code))

        print("\n[2] 知识库与私有权限")
        kbs = client.get("/kbs", headers=admin).json()
        check(len(kbs) >= 1, "知识库列表", str(kbs))
        kb_name = f"冒烟测试库-{int(time.time())}"
        created = client.post(
            "/admin/kbs",
            headers=admin,
            json={"name": kb_name, "description": "smoke test", "is_public": False},
        )
        check(created.status_code == 201, "创建私有知识库", created.text[:200])
        kb = created.json()
        demo_ids = [k["id"] for k in client.get("/kbs", headers=demo).json()]
        check(kb["id"] not in demo_ids, "私有库默认对普通用户不可见")
        client.put(f"/admin/kbs/{kb['id']}/permissions", headers=admin, json={"user_ids": []})
        users = client.get("/admin/users", headers=admin, params={"q": "demo"}).json()["items"]
        demo_id = users[0]["id"]
        client.put(f"/admin/kbs/{kb['id']}/permissions", headers=admin, json={"user_ids": [demo_id]})
        demo_ids = [k["id"] for k in client.get("/kbs", headers=demo).json()]
        check(kb["id"] in demo_ids, "授权后普通用户可见私有库")
        client.put(f"/admin/kbs/{kb['id']}/permissions", headers=admin, json={"user_ids": []})
        demo_ids = [k["id"] for k in client.get("/kbs", headers=demo).json()]
        check(kb["id"] not in demo_ids, "撤销授权后普通用户不可见")

        print("\n[3] 文档上传与异步解析")
        text = f"测试文档 {time.time()}：星辰 X5 售价 5999 元，整机保修 2 年。".encode("utf-8")
        upload = client.post(
            f"/admin/kbs/{kb['id']}/documents",
            headers=admin,
            files={"files": ("smoke_demo.txt", text, "text/plain")},
        )
        check(upload.status_code == 201, "上传文档", upload.text[:300])
        payload = upload.json()
        task_id = payload["items"][0]["task"]["id"]
        document_id = payload["items"][0]["document"]["id"]
        task = {}
        for _ in range(60):
            task = client.get(f"/admin/tasks/{task_id}", headers=admin).json()
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.5)
        check(task.get("status") == "completed", "解析任务完成", str(task))
        chunks = client.get(f"/admin/documents/{document_id}/chunks", headers=admin).json()
        check(chunks["total"] > 0, "生成父子分块", str(chunks["total"]))
        faq = stream_chat(client, admin, "星辰 X5 售价多少？", [kb["id"]])
        check("5999" in faq["answer"], "新文档可被检索并回答", faq["answer"][:120])
        check(len(faq["sources"]) > 0, "回答返回引用来源", str(len(faq["sources"])))
        deleted = client.delete(f"/admin/documents/{document_id}", headers=admin)
        check(deleted.status_code == 200, "删除文档与向量")

        print("\n[4] 问答、引用、缓存与反馈")
        conv = stream_chat(client, admin, "星辰 X1 Pro 的保修期是多久？", use_cache=False)
        check("保修" in conv["answer"], "保修问题命中售后资料", conv["answer"][:120])
        check(bool(conv["done"].get("used_citations")), "回答带有效引用编号", str(conv["done"]))
        conversation_id = conv["done"]["conversation_id"]
        cached = stream_chat(client, admin, "星辰 X1 Pro 的保修期是多久？", use_cache=True)
        check(cached["done"].get("cache_hit") is True, "重复问题命中语义缓存")
        messages = client.get(f"/conversations/{conversation_id}/messages", headers=admin).json()
        assistant = [m for m in messages["items"] if m["role"] == "assistant"][0]
        check(len(assistant["citations"]) > 0, "引用快照已持久化")
        feedback = client.post(f"/messages/{assistant['id']}/feedback", headers=admin, json={"rating": 1})
        check(feedback.status_code == 200, "提交点赞反馈")

        print("\n[5] 会话持久化与历史")
        convs = client.get("/conversations", headers=admin, params={"page_size": 50}).json()
        check(any(c["id"] == conversation_id for c in convs["items"]), "历史会话可找回")
        renamed = client.patch(f"/conversations/{conversation_id}", headers=admin, json={"title": "保修咨询"})
        check(renamed.status_code == 200 and renamed.json()["title"] == "保修咨询", "会话重命名")
        client.delete(f"/conversations/{conversation_id}", headers=admin)

        print("\n[6] 管理端统计与审计")
        stats = client.get("/admin/stats/overview", headers=admin)
        check(stats.status_code == 200, "统计概览", stats.text[:150])
        audit = client.get("/admin/audit-logs", headers=admin).json()
        check(audit["total"] > 0, "审计日志记录")
        system = client.get("/admin/system", headers=admin).json()
        check(system.get("embedding_provider"), "系统信息", str(system))
        client.delete(f"/admin/kbs/{kb['id']}", headers=admin)

        metrics = httpx.get("http://127.0.0.1:8000/metrics", timeout=10)
        check(metrics.status_code == 200 and "rag_http_requests_total" in metrics.text, "Prometheus 指标暴露")

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"失败 {len(FAILURES)} 项：{FAILURES}")
        sys.exit(1)
    print("全部冒烟测试通过 ✔")


if __name__ == "__main__":
    main()
