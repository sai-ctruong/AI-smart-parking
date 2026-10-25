"""Password login, short-lived bearer tokens, and database-backed RBAC."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import MissingDatabaseConfiguration
from app.db import session_scope
from app.models import AuditLog, User

ISSUER = "smart-parking-api"
AUDIENCE = "smart-parking"
ALGORITHM = "HS256"
password_hasher = PasswordHash.recommended()
_DUMMY_HASH = password_hasher.hash("dummy-password-for-login-timing-only")
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/v1")


class ApiError(Exception):
    """Safe, stable error for versioned API routes."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _unauthed() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "Invalid credentials")


def hash_password(password: str) -> str:
    """Hash a new password with the maintained Argon2 default."""
    return password_hasher.hash(password)


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return password_hasher.verify(password, stored_hash)
    except (UnknownHashError, ValueError):
        return False


def _normalize_username(value: str) -> str:
    return value.strip().lower()


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=1024)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,99}$")
    password: str = Field(min_length=12, max_length=128)
    role: Literal["admin", "operator"]

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return _normalize_username(value) if isinstance(value, str) else value


class UserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["admin", "operator"] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UserPatch":
        if self.role is None and self.is_active is None:
            raise ValueError("Provide role or is_active")
        return self


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=12, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Literal["admin", "operator"]
    is_active: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


def get_auth_session(request: Request) -> Iterator[Session]:
    """Resolve the app's database without a global configuration override."""
    try:
        database_url = request.app.state.settings.require_database_url()
    except MissingDatabaseConfiguration as exc:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Authentication is unavailable"
        ) from exc
    with session_scope(database_url) as session:
        yield session


def _secret(request: Request) -> str:
    try:
        return request.app.state.settings.require_auth_secret()
    except ValueError as exc:
        raise ApiError(
            503, "SERVICE_UNAVAILABLE", "Authentication is unavailable"
        ) from exc


def create_access_token(user: User, request: Request) -> str:
    """Sign a minimal identity token; roles are never trusted from token claims."""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=request.app.state.settings.access_token_minutes)
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "iat": now,
            "exp": expires,
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        _secret(request),
        algorithm=ALGORITHM,
    )


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> User:
    """Reject invalid tokens and reload account state for every request."""
    if credentials is None:
        raise _unauthed()
    try:
        payload = jwt.decode(
            credentials.credentials,
            _secret(request),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["sub", "ver", "iat", "exp", "iss", "aud"]},
        )
        user_id = UUID(payload["sub"])
    except (InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise _unauthed() from exc
    user = session.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or user.role not in {"admin", "operator"}
        or isinstance(payload["ver"], bool)
        or not isinstance(payload["ver"], int)
        or payload["ver"] != user.token_version
    ):
        raise _unauthed()
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """Use on every Admin-only route, including future camera/spot writes."""
    if user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Insufficient permissions")
    return user


@router.post("/auth/login", response_model=TokenResponse)
def login(
    credentials: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_auth_session)],
) -> TokenResponse:
    user = session.scalar(
        select(User).where(User.username == _normalize_username(credentials.username))
    )
    if user is None or not user.is_active:
        _verify_password(credentials.password, _DUMMY_HASH)
        raise _unauthed()
    if not _verify_password(credentials.password, user.password_hash):
        raise _unauthed()
    token = create_access_token(user, request)
    session.add(
        AuditLog(
            actor_id=user.id,
            action="auth.login",
            target_type="user",
            target_id=user.id,
        )
    )
    session.commit()
    return TokenResponse(
        access_token=token,
        expires_in=request.app.state.settings.access_token_minutes * 60,
    )


@router.get("/auth/me", response_model=UserPublic)
def own_identity(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.post("/users", response_model=UserPublic, status_code=201)
def create_user(
    body: UserCreate,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> User:
    if (
        session.scalar(select(User.id).where(User.username == body.username))
        is not None
    ):
        raise ApiError(409, "CONFLICT", "Username already exists")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    session.add(user)
    session.flush()
    session.add(
        AuditLog(
            actor_id=admin.id,
            action="user.created",
            target_type="user",
            target_id=user.id,
        )
    )
    session.commit()
    return user


@router.get("/users")
def list_users(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> dict[str, list[UserPublic]]:
    users = session.scalars(select(User).order_by(User.username)).all()
    return {"items": [UserPublic.model_validate(user) for user in users]}


def _target_user(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "NOT_FOUND", "User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserPublic)
def update_user(
    user_id: UUID,
    body: UserPatch,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> User:
    user = _target_user(session, user_id)
    removing_active_admin = (
        user.role == "admin"
        and user.is_active
        and (body.role == "operator" or body.is_active is False)
    )
    if removing_active_admin:
        count = session.scalar(
            select(func.count(User.id)).where(User.role == "admin", User.is_active)
        )
        if count <= 1:
            raise ApiError(409, "CONFLICT", "Cannot disable the last active Admin")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    session.add(
        AuditLog(
            actor_id=admin.id,
            action="user.updated",
            target_type="user",
            target_id=user.id,
        )
    )
    session.commit()
    return user


@router.post("/users/{user_id}/password", response_model=UserPublic)
def reset_user_password(
    user_id: UUID,
    body: PasswordReset,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[Session, Depends(get_auth_session)],
) -> User:
    user = _target_user(session, user_id)
    session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            password_hash=hash_password(body.password),
            token_version=User.token_version + 1,
        )
    )
    session.refresh(user)
    session.add(
        AuditLog(
            actor_id=admin.id,
            action="user.password_reset",
            target_type="user",
            target_id=user.id,
        )
    )
    session.commit()
    return user
