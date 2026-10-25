"""
Optional RAGAS evaluation (requires an API key and extra dependencies).

Install:
    uv pip install --python backend/.venv/Scripts/python.exe -r eval/requirements-ragas.txt

Run:
    set DASHSCOPE_API_KEY=sk-xxx
    backend/.venv/Scripts/python.exe eval/run_ragas.py

The judge model is qwen-max and the embedding model is text-embedding-v4 via
Bailian's OpenAI-compatible endpoint. RAGAS API has changed across releases;
this script supports both 0.2 class and legacy singleton metric styles.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from run_eval import GOLDEN, stream_chat  # noqa: E402

BASE = os.environ.get("RAG_BASE_URL", "http://127.0.0.1:8000/api/v1")
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
MODEL_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def collect() -> list[dict]:
    if not API_KEY:
        raise SystemExit("请先设置 DASHSCOPE_API_KEY")
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows: list[dict] = []
    with httpx.Client(base_url=BASE, timeout=120) as client:
        login = client.post("/auth/login", json={"username": "admin", "password": "123456"})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        for index, case in enumerate(cases, 1):
            result = stream_chat(client, headers, case["question"])
            rows.append(
                {
                    "user_input": case["question"],
                    "response": result["answer"],
                    "retrieved_contexts": [s.get("snippet", "") for s in result["sources"][:5]],
                    "reference": case.get("reference", ""),
                }
            )
            print(f"[{index}/{len(cases)}] {case['question']}")
            if result["done"].get("conversation_id"):
                client.delete(f"/conversations/{result['done']['conversation_id']}", headers=headers)
    return rows


def main() -> None:
    try:
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
    except ImportError as exc:
        raise SystemExit(
            "缺少依赖，请执行：uv pip install --python backend/.venv/Scripts/python.exe -r eval/requirements-ragas.txt"
        ) from exc

    try:
        from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness

        metrics = [Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()]
    except ImportError:
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

        metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    rows = collect()
    dataset = EvaluationDataset.from_list(rows)

    judge = ChatOpenAI(model="qwen-max", api_key=API_KEY, base_url=MODEL_BASE, temperature=0.0)
    embeddings = OpenAIEmbeddings(
        model="text-embedding-v4",
        api_key=API_KEY,
        base_url=MODEL_BASE,
        dimensions=1024,
        check_embedding_ctx_length=False,
    )
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=LangchainLLMWrapper(judge),
        embeddings=LangchainEmbeddingsWrapper(embeddings),
    )
    print(result)
    out = ROOT / "eval" / "ragas_result.json"
    try:
        out.write_text(json.dumps(result.to_pandas().to_dict(orient="records"), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"明细：{out}")
    except Exception:  # noqa: BLE001
        out.write_text(str(result), encoding="utf-8")


if __name__ == "__main__":
    main()
