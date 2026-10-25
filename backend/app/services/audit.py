"""Audit log helper."""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, User


def add_audit(
    db: AsyncSession,
    actor: User | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id if actor else None,
            actor_name=actor.username if actor else None,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            ip=request.client.host if request and request.client else None,
            user_agent=(request.headers.get("user-agent") or "")[:250] if request else None,
            detail=detail or {},
        )
    )
