from sqlalchemy.orm import Session

from app.db.models import AuditLog


def audit(
    db: Session,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    entity_type: str,
    entity_id: str,
    previous: dict | None = None,
    new: dict | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            previous_json=previous,
            new_json=new,
            reason=reason,
        )
    )
