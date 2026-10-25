"""Knowledge-base read endpoints for end users (visibility-filtered)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.schemas import KBOut
from app.services.kb_access import assert_kb_visible, visible_kbs

router = APIRouter(prefix="/kbs", tags=["knowledge-bases"])


@router.get("", response_model=list[KBOut])
async def list_kbs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await visible_kbs(db, user)


@router.get("/{kb_id}", response_model=KBOut)
async def get_kb(kb_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await assert_kb_visible(db, user, kb_id)
