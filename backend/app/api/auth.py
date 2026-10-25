"""Authentication: register/login/refresh rotation/logout/me/change-password."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    refresh_expiry,
    verify_password,
)
from app.db.models import RefreshToken, User, utcnow
from app.db.session import get_db
from app.schemas import ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserOut
from app.services.audit import add_audit

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "rag_refresh_token"
COOKIE_PATH = f"{settings.api_prefix}/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        samesite="lax",
        secure=False,  # local HTTP deployment; set True behind HTTPS
        path=COOKIE_PATH,
    )


async def _issue_tokens(
    db: AsyncSession, user: User, request: Request, response: Response, family_id: str | None = None
) -> tuple[TokenOut, RefreshToken]:
    access, expires_in = create_access_token(user.id, user.username, user.role, user.token_version)
    refresh_token = new_refresh_token()
    row = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        family_id=family_id or uuid.uuid4().hex,
        expires_at=refresh_expiry(),
        user_agent=(request.headers.get("user-agent") or "")[:250],
        ip=request.client.host if request.client else None,
    )
    db.add(row)
    await db.flush()
    _set_refresh_cookie(response, refresh_token)
    token = TokenOut(access_token=access, expires_in=expires_in, user=UserOut.model_validate(user))
    return token, row


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await limiter.hit(f"register:{request.client.host if request.client else 'na'}", settings.rate_limit_register_per_min)
    existing = await db.scalar(select(User).where(User.username == payload.username))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")
    user = User(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        password_hash=hash_password(payload.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    add_audit(db, user, "auth.register", "user", user.id, request)
    token, _ = await _issue_tokens(db, user, request, response)
    await db.commit()
    return token


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = request.client.host if request.client else "na"
    await limiter.hit(f"login:{ip}", settings.rate_limit_login_per_min)
    user = await db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        add_audit(db, None, "auth.login_failed", "user", None, request, {"username": payload.username})
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")
    user.last_login_at = utcnow()
    add_audit(db, user, "auth.login", "user", user.id, request)
    token, _ = await _issue_tokens(db, user, request, response)
    await db.commit()
    return token


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少刷新令牌")
    row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效")
    if row.revoked_at is not None:
        # Reuse detection: revoke the whole family.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌已被使用，请重新登录")
    if row.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
        row.revoked_at = utcnow()
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌已过期，请重新登录")

    user = await db.get(User, row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    row.revoked_at = utcnow()
    token, new_row = await _issue_tokens(db, user, request, response, family_id=row.family_id)
    row.replaced_by = new_row.id
    await db.commit()
    return token


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        row = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
        if row:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    await db.commit()
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user


@router.post("/password")
async def change_password(
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")
    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    add_audit(db, user, "auth.change_password", "user", user.id, request)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    await db.commit()
    return {"ok": True, "message": "密码已修改，请重新登录"}
