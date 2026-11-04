"""Demo authentication: signed bearer tokens issued by passwordless email sign-in.

Good enough for a hackathon demo with seeded accounts; swap for Supabase Auth or
similar before any real use. Authorization (who may touch what) lives in the
require_* helpers below and is what the tests exercise.
"""

import hashlib
import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import get_db
from app.db.models import Campaign, Ngo, User
from contracts.reporting_schemas import Role

_bearer = HTTPBearer(auto_error=False)


def _sign(user_id: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, user_id.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: str) -> str:
    return f"{user_id}.{_sign(user_id)}"


def _user_from_token(token: str, db: Session) -> User | None:
    user_id, _, sig = token.partition(".")
    if not user_id or not hmac.compare_digest(sig, _sign(user_id)):
        return None
    return db.get(User, user_id)


def optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User | None:
    return _user_from_token(creds.credentials, db) if creds else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    return user


def require_role(user: User, *roles: Role) -> None:
    if user.role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for this role")


def ngo_for_user(db: Session, user: User) -> Ngo:
    ngo = db.scalar(select(Ngo).where(Ngo.owner_user_id == user.id))
    if ngo is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Create an NGO profile first")
    return ngo


def load_campaign_for_editor(db: Session, user: User, campaign_id: str) -> Campaign:
    """Campaign the user may manage: its NGO owner, or a platform reviewer.

    Returns 404 (not 403) for other NGOs' campaigns so ids cannot be enumerated.
    """
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    if user.role == Role.REVIEWER:
        return campaign
    if user.role == Role.NGO_ADMIN:
        ngo = db.scalar(select(Ngo).where(Ngo.owner_user_id == user.id))
        if ngo and ngo.id == campaign.ngo_id:
            return campaign
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
