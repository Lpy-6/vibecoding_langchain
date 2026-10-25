from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_\-\u4e00-\u9fa5]+$")
    password: str = Field(min_length=6, max_length=64)
    display_name: str = Field(default="", max_length=32)


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class UserOut(ORMModel):
    id: str
    username: str
    email: str | None = None
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------- knowledge base ----------
class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    is_public: bool = True


class KBUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    is_public: bool | None = None


class KBOut(ORMModel):
    id: str
    name: str
    description: str
    is_public: bool
    version: int
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KBPermissionIn(BaseModel):
    user_ids: list[str] = Field(default_factory=list)


class UserBrief(ORMModel):
    id: str
    username: str
    display_name: str


# ---------- documents / tasks ----------
class DocumentOut(ORMModel):
    id: str
    kb_id: str
    title: str
    source_type: str
    original_filename: str | None
    mime_type: str | None
    size_bytes: int
    source_url: str | None
    status: str
    error_message: str | None
    page_count: int
    chunk_count: int
    ocr_pages: int
    created_at: datetime
    updated_at: datetime


class TaskOut(ORMModel):
    id: str
    document_id: str
    kb_id: str
    task_type: str
    status: str
    stage: str
    progress: int
    attempts: int
    max_attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class UrlImportIn(BaseModel):
    url: str = Field(max_length=1024)
    title: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("仅支持 http/https 链接")
        return v


class ChunkOut(ORMModel):
    id: int
    chunk_type: str
    ordinal: int
    content: str
    token_count: int
    page_no: int | None
    sheet_name: str | None
    row_start: int | None
    row_end: int | None
    heading_path: str | None
    parent_id: int | None


# ---------- conversation / chat ----------
class ConversationCreate(BaseModel):
    title: str = Field(default="新会话", max_length=60)
    kb_ids: list[str] = Field(default_factory=list)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=60)
    kb_ids: list[str] | None = None
    is_archived: bool | None = None


class ConversationOut(ORMModel):
    id: str
    title: str
    kb_ids: list[str]
    message_count: int
    last_message_at: datetime
    created_at: datetime


class CitationOut(ORMModel):
    id: int
    rank: int
    chunk_id: int | None
    document_id: str | None
    kb_id: str | None
    snippet: str
    doc_title: str
    locator: dict
    dense_score: float | None
    sparse_score: float | None
    rerank_score: float | None
    used: bool


class MessageOut(ORMModel):
    id: str
    role: str
    content: str
    status: str
    model: str | None
    latency_ms: int | None
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)
    feedback: int | None = None


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    kb_ids: list[str] = Field(default_factory=list)
    use_cache: bool = True


class FeedbackIn(BaseModel):
    rating: Literal[1, -1]
    reason_code: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=500)


# ---------- admin ----------
class UserAdminUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    role: Literal["admin", "user"] | None = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=64)


class Paginated(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
