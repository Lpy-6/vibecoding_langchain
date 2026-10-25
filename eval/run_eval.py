"""
Lightweight RAG evaluation against a running backend.

Metrics (no extra dependencies):
  - retrieval_hit: expected keyword appears in retrieved snippets
  - answer_hit: expected keyword appears in the generated answer
  - citation_rate: answer carries at least one valid [n] and returns sources
  - latency: end-to-end first-token / total latency from the SSE done event

Usage:
    backend/.venv/Scripts/python.exe eval/run_eval.py --limit 20

For the paper's RAGAS numbers, see eval/run_ragas.py (optional dependencies).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden" / "qa.jsonl"
OUT = ROOT / "eval" / "results.csv"


def _norm(text: str) -> str:
    """Ignore whitespace, full-width commas and optional currency suffixes."""
    return re.sub(r"\s+", "", text or "").replace("，", ",").replace("元", "")


def _summary_from_rows(rows: list[dict]) -> dict:
    total = len(rows)
    retrieval_hits = sum(1 for r in rows if str(r.get("retrieval_hit")).lower() == "true")
    answer_hits = sum(1 for r in rows if str(r.get("answer_hit")).lower() == "true")
    citation_hits = sum(1 for r in rows if str(r.get("citation_ok")).lower() == "true")
    latencies = [int(float(r["latency_ms"])) for r in rows if str(r.get("latency_ms", "")).strip() not in {"", "None"}]
    first_tokens = [int(float(r["first_token_ms"])) for r in rows if str(r.get("first_token_ms", "")).strip() not in {"", "None"}]
    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)] if latencies else 0
    first_sorted = sorted(first_tokens)
    p95_first = first_sorted[max(0, int(len(first_sorted) * 0.95) - 1)] if first_tokens else 0
    return {
        "cases": total,
        "retrieval_hit_rate": round(retrieval_hits / total, 3) if total else 0,
        "answer_hit_rate": round(answer_hits / total, 3) if total else 0,
        "citation_rate": round(citation_hits / total, 3) if total else 0,
        "avg_first_token_ms": round(statistics.mean(first_tokens), 1) if first_tokens else 0,
        "p95_first_token_ms": p95_first,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
        "p95_latency_ms": p95,
    }


def rescore_existing() -> None:
    rows = list(csv.DictReader(OUT.open(encoding="utf-8-sig")))
    for row in rows:
        keywords = [k for k in (row.get("expected_keywords") or "").split("|") if k]
        row["answer_hit"] = str(any(_norm(k) in _norm(row.get("answer", "")) for k in keywords)).lower()
    fieldnames = list(rows[0].keys())
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(_summary_from_rows(rows), ensure_ascii=False, indent=2))
    print(f"已按归一化规则重算并写回 {OUT}")


def stream_chat(client: httpx.Client, headers: dict, question: str) -> dict:
    answer: list[str] = []
    sources: list[dict] = []
    done: dict = {}
    first_token_ms: int | None = None
    started = time.perf_counter()
    for attempt in range(4):
        with client.stream(
            "POST",
            "/chat/stream",
            headers=headers,
            json={"question": question, "kb_ids": [], "use_cache": False},
            timeout=120,
        ) as resp:
            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", "10"))
                print(f"     限流，等待 {wait}s 后重试 ...")
                time.sleep(wait + 1)
                continue
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
                        if first_token_ms is None:
                            first_token_ms = int((time.perf_counter() - started) * 1000)
                        answer.append(data.get("delta", ""))
                    elif event == "sources":
                        sources = data.get("sources", [])
                    elif event == "done":
                        done = data
            break
    return {
        "answer": "".join(answer),
        "sources": sources,
        "done": done,
        "first_token_ms": first_token_ms,
        "wall_ms": int((time.perf_counter() - started) * 1000),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="123456")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--keep-conversations", action="store_true")
    parser.add_argument("--rescore", action="store_true", help="recompute answer_hit from an existing results.csv")
    args = parser.parse_args()

    if args.rescore:
        rescore_existing()
        return

    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        cases = cases[: args.limit]

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        login = client.post("/auth/login", json={"username": args.username, "password": args.password})
        login.raise_for_status()
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        rows = []
        latencies = []
        first_tokens = []
        retrieval_hits = answer_hits = citation_hits = 0
        print(f"评估 {len(cases)} 条问题 ...\n")
        for index, case in enumerate(cases, 1):
            result = stream_chat(client, headers, case["question"])
            answer = result["answer"]
            snippets = " ".join(s.get("snippet", "") for s in result["sources"])
            keywords = case.get("expected_keywords", [])
            retrieval_hit = any(_norm(k) in _norm(snippets) for k in keywords)
            answer_hit = any(_norm(k) in _norm(answer) for k in keywords)
            used = result["done"].get("used_citations") or []
            citation_ok = bool(used) and bool(result["sources"])
            latency = result["done"].get("latency_ms") or result["wall_ms"]
            latencies.append(latency)
            if result["first_token_ms"] is not None:
                first_tokens.append(result["first_token_ms"])
            retrieval_hits += int(retrieval_hit)
            answer_hits += int(answer_hit)
            citation_hits += int(citation_ok)
            rows.append(
                {
                    "question": case["question"],
                    "expected_keywords": "|".join(keywords),
                    "answer": answer.replace("\n", " ")[:500],
                    "retrieval_hit": retrieval_hit,
                    "answer_hit": answer_hit,
                    "citation_ok": citation_ok,
                    "used_citations": "|".join(str(x) for x in used),
                    "sources": len(result["sources"]),
                    "first_token_ms": result["first_token_ms"],
                    "latency_ms": latency,
                    "cache_hit": result["done"].get("cache_hit", False),
                }
            )
            marks = "✔" if (retrieval_hit and answer_hit and citation_ok) else "✘"
            print(f"{index:2d}. {marks} {case['question']}  ({latency} ms)")
            if not answer_hit:
                print(f"     answer: {answer[:160]}")
            if not args.keep_conversations and result["done"].get("conversation_id"):
                client.delete(f"/conversations/{result['done']['conversation_id']}", headers=headers)

    total = len(rows)
    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)] if latencies else 0
    first_tokens_sorted = sorted(first_tokens)
    p95_first = first_tokens_sorted[max(0, int(len(first_tokens_sorted) * 0.95) - 1)] if first_tokens else 0
    summary = {
        "cases": total,
        "retrieval_hit_rate": round(retrieval_hits / total, 3),
        "answer_hit_rate": round(answer_hits / total, 3),
        "citation_rate": round(citation_hits / total, 3),
        "avg_first_token_ms": round(statistics.mean(first_tokens), 1) if first_tokens else 0,
        "p95_first_token_ms": p95_first,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0,
        "p95_latency_ms": p95,
    }
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n明细已写入 {OUT}")


if __name__ == "__main__":
    main()
