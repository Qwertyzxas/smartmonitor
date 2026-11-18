from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from loguru import logger

from app.api.deps import DB, AdminUser, CurrentUser
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.repositories import users as users_repo
from app.schemas import Credentials, TokenOut, UserOut, UserRoleUpdate

router = APIRouter(prefix="/api", tags=["auth"])


def _token(user: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(str(user.id), user.role),
                    user=UserOut.model_validate(user))


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(body: Credentials, db: DB) -> TokenOut:
    if users_repo.get_by_username(db, body.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = users_repo.create(db, body.username, hash_password(body.password), UserRole.viewer.value)
    db.commit()
    logger.info("Registered viewer '{}'", user.username)
    return _token(user)


@router.post("/auth/login", response_model=TokenOut)
def login(body: Credentials, db: DB) -> TokenOut:
    user = users_repo.get_by_username(db, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return _token(user)


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut])
def list_users(db: DB, _: AdminUser) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in users_repo.list_all(db)]


@router.patch("/users/{user_id}", response_model=UserOut)
def update_role(user_id: int, body: UserRoleUpdate, db: DB, admin: AdminUser) -> UserOut:
    user = users_repo.get(db, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and body.role != "admin":
        raise HTTPException(400, "Нельзя снять роль admin с самого себя")
    user.role = body.role
    db.commit()
    logger.info("Admin '{}' set role of '{}' to {}", admin.username, user.username, body.role)
    return UserOut.model_validate(user)
