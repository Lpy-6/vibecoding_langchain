"""Prometheus metrics for HTTP and RAG stages."""
from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "rag_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "rag_http_request_duration_seconds", "HTTP latency", ["method", "path"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
)
RAG_STAGE_LATENCY = Histogram(
    "rag_stage_duration_seconds", "RAG stage latency", ["stage"], buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20)
)
RAG_ANSWERS = Counter("rag_answers_total", "RAG answers", ["mode", "cache_hit", "status"])
CACHE_HITS = Counter("rag_cache_hits_total", "Semantic cache hits", ["kind"])
INGEST_JOBS = Counter("rag_ingest_jobs_total", "Ingestion jobs", ["status"])
FEEDBACK_COUNT = Counter("rag_feedback_total", "User feedback", ["rating"])
