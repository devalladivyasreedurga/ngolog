from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import current_user, issue_token
from app.config import get_settings
from app.db.base import get_db
from app.db.models import User
from contracts.reporting_schemas import Role

router = APIRouter(prefix="/api/auth", tags=["auth"])


class DemoLoginIn(BaseModel):
    email: EmailStr
    role: Role = Role.DONOR
    display_name: str | None = None


class UserOut(BaseModel):
    id: str
    email: str
    role: Role
    display_name: str | None


class TokenOut(BaseModel):
    token: str
    user: UserOut


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=Role(u.role), display_name=u.display_name)


@router.post("/demo-login", response_model=TokenOut)
def demo_login(body: DemoLoginIn, db: Session = Depends(get_db)) -> TokenOut:
    settings = get_settings()
    if not settings.demo_auth_enabled:
        raise HTTPException(404, "Demo sign-in is disabled")
    email = body.email.lower()
    if body.role == Role.REVIEWER and email not in settings.reviewer_email_set:
        raise HTTPException(403, "Reviewer accounts are allowlisted")
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, role=body.role, display_name=body.display_name)
        db.add(user)
        db.commit()
    elif user.role != body.role:
        raise HTTPException(409, f"This email is registered as {user.role}")
    return TokenOut(token=issue_token(user.id), user=_out(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return _out(user)
