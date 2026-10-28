"""
Locust 压测脚本（SSE 流式问答 + 混合负载）。

通过环境变量控制行为：
    STRESS_MODE=S1|S2       S1 纯问答；S2 混合负载（默认 S1）
    STRESS_USER_COUNT=100   tokens.json 中使用的账号数

用法（仓库根目录）：
    backend/.venv/Scripts/python.exe -m locust -f stress/locustfile.py \
        --host http://127.0.0.1:8001 --headless -u 100 -r 10 --run-time 10m \
        --csv stress/results/s1
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

from locust import HttpUser, between, events, task

ROOT = Path(__file__).resolve().parents[1]
STRESS_MODE = os.environ.get("STRESS_MODE", "S1").upper()
USER_COUNT = int(os.environ.get("STRESS_USER_COUNT", "100"))
PASSWORD = "Stress@123456"

QUESTIONS: list[str] = []
TOKENS: list[str] = []


@events.init.add_listener
def on_init(environment, **_kwargs) -> None:
    global QUESTIONS, TOKENS
    qa_path = ROOT / "eval" / "golden" / "qa.jsonl"
    with qa_path.open(encoding="utf-8") as fh:
        QUESTIONS = [json.loads(line)["question"] for line in fh if line.strip()]
    tokens_path = Path(__file__).parent / "tokens.json"
    TOKENS = sorted(json.loads(tokens_path.read_text(encoding="utf-8")).values())
    print(f"压测模式 {STRESS_MODE}，问题 {len(QUESTIONS)} 条，账号 {len(TOKENS)} 个")


class ChatUser(HttpUser):
    wait_time = between(1.0, 3.0)

    def on_start(self) -> None:
        idx = random.randrange(min(USER_COUNT, len(TOKENS)))
        self.client.headers["Authorization"] = f"Bearer {TOKENS[idx]}"
        self.conversation_id: str | None = None
        self.last_message_id: str | None = None

    def stream_chat(self) -> None:
        question = random.choice(QUESTIONS)
        start = time.perf_counter()
        first_token: float | None = None
        got_done = False
        with self.client.post(
            "/api/v1/chat/stream",
            json={"question": question, "kb_ids": [], "use_cache": True},
            stream=True,
            catch_response=True,
            name="POST /chat/stream [SSE]",
        ) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
                return
            event = None
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event = line[6:].strip()
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    if event == "token" and first_token is None:
                        first_token = time.perf_counter() - start
                    elif event == "done":
                        got_done = True
                        self.conversation_id = data.get("conversation_id")
                        self.last_message_id = data.get("message_id")
                    elif event == "error":
                        resp.failure(str(data)[:200])
                        return
            except (json.JSONDecodeError, OSError) as exc:
                resp.failure(f"SSE 中断: {exc}")
                return
        total = time.perf_counter() - start
        if not got_done:
            return  # 已在上方标失败或流中断
        if first_token is not None:
            self.environment.events.request.fire(
                request_type="SSE",
                name="first-token",
                response_time=first_token * 1000,
                response_length=0,
                exception=None,
                context={},
            )
        self.environment.events.request.fire(
            request_type="SSE",
            name="full-answer",
            response_time=total * 1000,
            response_length=0,
            exception=None,
            context={},
        )

    @task(55)
    def chat(self) -> None:
        self.stream_chat()

    @task(20)
    def browse_history(self) -> None:
        if STRESS_MODE == "S1":
            self.stream_chat()
            return
        resp = self.client.get("/api/v1/conversations", params={"page_size": 20}, name="GET /conversations")
        if resp.status_code != 200 or not (items := resp.json().get("items", [])):
            return
        conv_id = self.conversation_id or random.choice(items)["id"]
        self.client.get(
            f"/api/v1/conversations/{conv_id}/messages",
            params={"page_size": 50},
            name="GET /conversations/{id}/messages",
        )

    @task(10)
    def create_conversation(self) -> None:
        if STRESS_MODE == "S1":
            self.stream_chat()
            return
        resp = self.client.post(
            "/api/v1/conversations",
            json={"title": f"压测会话 {random.randrange(1000)}"},
            name="POST /conversations",
        )
        if resp.status_code == 201:
            self.conversation_id = resp.json()["id"]

    @task(10)
    def view_citations(self) -> None:
        if STRESS_MODE == "S1" or not self.last_message_id:
            if STRESS_MODE == "S1":
                self.stream_chat()
            return
        self.client.get(
            f"/api/v1/messages/{self.last_message_id}/citations",
            name="GET /messages/{id}/citations",
        )

    @task(5)
    def send_feedback(self) -> None:
        if STRESS_MODE == "S1" or not self.last_message_id:
            if STRESS_MODE == "S1":
                self.stream_chat()
            return
        self.client.post(
            f"/api/v1/messages/{self.last_message_id}/feedback",
            json={"rating": random.choice([1, -1]), "comment": "压测反馈"},
            name="POST /messages/{id}/feedback",
        )
