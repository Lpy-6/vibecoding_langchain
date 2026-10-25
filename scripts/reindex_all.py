"""
Re-embed every ready document, e.g. after switching from offline hashing
embeddings to DashScope text-embedding-v4.

Usage:
    backend/.venv/Scripts/python.exe scripts/reindex_all.py [--kb <kb_id>]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.models import Document, IngestTask  # noqa: E402
from app.db.session import init_db, sync_session_scope  # noqa: E402
from app.ingest.pipeline import process_document  # noqa: E402
from app.seed import seed_initial_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", help="only reindex documents in this KB id")
    args = parser.parse_args()

    asyncio.run(init_db())
    asyncio.run(seed_initial_data())

    with sync_session_scope() as session:
        stmt = select(Document).where(Document.deleted_at.is_(None), Document.status == "ready")
        if args.kb:
            stmt = stmt.where(Document.kb_id == args.kb)
        docs = session.execute(stmt).scalars().all()
        jobs = [(doc.id, doc.kb_id, doc.title) for doc in docs]

    print(f"当前向量提供方：{settings.embedding_model if settings.use_dashscope else 'offline-hashing-v1'}")
    print(f"待重索引文档：{len(jobs)}")
    for index, (document_id, kb_id, title) in enumerate(jobs, 1):
        with sync_session_scope() as session:
            doc = session.get(Document, document_id)
            if not doc:
                continue
            doc.status = "pending"
            task = IngestTask(
                document_id=document_id,
                kb_id=kb_id,
                task_type="reindex",
                max_attempts=settings.ingest_max_attempts,
            )
            session.add(task)
            session.flush()
            task_id = task.id
        print(f"[{index}/{len(jobs)}] {title} ...", end="", flush=True)
        try:
            process_document(document_id, task_id)
            print(" 完成")
        except Exception as exc:  # noqa: BLE001
            print(f" 失败：{exc}")
    print("\n全部完成。建议重启后端以重建内存索引。")


if __name__ == "__main__":
    main()
