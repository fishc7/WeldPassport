from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class AuthenticatedActorResponse(BaseModel):
    account_id: UUID
    worker_id: int | None
    authenticated_at: datetime
    auth_method: str
    must_change_password: bool


class LoginResponse(AuthenticatedActorResponse):
    idle_expires_at: datetime
    absolute_expires_at: datetime


class LogoutAllResponse(BaseModel):
    revoked_sessions: int


class OperationResponse(BaseModel):
    status: str
