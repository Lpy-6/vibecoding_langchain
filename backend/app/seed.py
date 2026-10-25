"""Idempotent bootstrap: admin account, demo user and a default knowledge base."""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import KnowledgeBase, User, utcnow
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def seed_initial_data() -> None:
    async with AsyncSessionLocal() as db:
        admin = await db.scalar(select(User).where(User.username == settings.admin_username))
        if not admin:
            admin = User(
                username=settings.admin_username,
                display_name="系统管理员",
                password_hash=hash_password(settings.admin_password),
                role="admin",
                is_active=True,
            )
            db.add(admin)
            logger.info("seeded admin account username=%s", settings.admin_username)
        else:
            admin.role = "admin"
            admin.is_active = True

        if settings.seed_demo_user:
            demo = await db.scalar(select(User).where(User.username == "demo"))
            if not demo:
                db.add(
                    User(
                        username="demo",
                        display_name="演示用户",
                        password_hash=hash_password("demo123"),
                        role="user",
                        is_active=True,
                    )
                )
                logger.info("seeded demo user username=demo password=demo123")

        kb = await db.scalar(select(KnowledgeBase).limit(1))
        if not kb:
            from app.rag.embeddings import get_embedding_provider

            provider = get_embedding_provider()
            db.add(
                KnowledgeBase(
                    name="商品知识库",
                    description="电商商品资料、参数与售后政策示例知识库",
                    is_public=True,
                    embedding_model=provider.name,
                    embedding_dim=settings.embedding_dim,
                    created_by=admin.id,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        await db.commit()
