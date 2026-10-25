"""Background ingestion runner with bounded retries (thread pool, no Redis/Celery)."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.core.config import settings
from app.db.models import Document, IngestTask, utcnow
from app.db.session import sync_session_scope
from app.ingest.pipeline import process_document

logger = logging.getLogger(__name__)


class IngestTaskRunner:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.ingest_workers), thread_name_prefix="ingest"
        )

    def submit(self, task_id: str, document_id: str) -> None:
        self._executor.submit(self._run, task_id, document_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, task_id: str, document_id: str) -> None:
        max_attempts = settings.ingest_max_attempts
        with sync_session_scope() as session:
            task = session.get(IngestTask, task_id)
            if task:
                max_attempts = task.max_attempts or max_attempts

        for attempt in range(1, max_attempts + 1):
            with sync_session_scope() as session:
                task = session.get(IngestTask, task_id)
                doc = session.get(Document, document_id)
                if task:
                    task.status = "running"
                    task.attempts = attempt
                    task.started_at = task.started_at or utcnow()
                    task.error = None
                if doc:
                    doc.status = "parsing" if attempt == 1 else "retrying"
                    doc.error_message = None
            try:
                process_document(document_id, task_id)
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("ingest failed attempt=%s/%s doc=%s", attempt, max_attempts, document_id)
                final = attempt >= max_attempts
                with sync_session_scope() as session:
                    task = session.get(IngestTask, task_id)
                    doc = session.get(Document, document_id)
                    message = str(exc)[:2000]
                    if task:
                        task.status = "failed" if final else "retrying"
                        task.stage = "失败"
                        task.error = message
                        if final:
                            task.finished_at = utcnow()
                    if doc:
                        doc.status = "failed" if final else "retrying"
                        doc.error_message = message
                if final:
                    return
                time.sleep(min(10, 2 * attempt))


task_runner = IngestTaskRunner()
