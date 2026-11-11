import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import retrieval, runtime, workflow
from app.agent.checks import find_exact_duplicates
from app.agent.llm import AIUnavailable, get_ai
from app.audit import audit
from app.auth.deps import current_user, load_campaign_for_editor, optional_user
from app.config import get_settings
from app.db.base import get_db, new_id
from app.db.models import (
    Campaign,
    ClaimEvidence,
    Evidence,
    EvidenceCheck,
    ExpenseClaim,
    ImpactClaim,
    ReportingRequest,
    User,
)
from app.reporting.router import ThreadOut, build_thread
from contracts.reporting_schemas import (
    CheckStatus,
    CheckType,
    ClaimStatus,
    EvidenceKind,
    EvidenceReviewStatus,
    EvidenceVisibility,
)

router = APIRouter(prefix="/api/evidence", tags=["evidence"])

# Magic-byte sniffing: the declared content type is not trusted.
SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF-",),
}
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}


def sniff_type(data: bytes) -> str | None:
    for mime, sigs in SIGNATURES.items():
        if any(data.startswith(s) for s in sigs):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def review_evidence(db: Session, req: ReportingRequest, ev: Evidence) -> None:
    """Index the receipt summary and look for the same receipt number elsewhere in this NGO."""
    db.flush()
    hits, backend = retrieval.find_reused_receipts(db, ev)
    already = db.scalar(select(EvidenceCheck).where(EvidenceCheck.evidence_id == ev.id, EvidenceCheck.check_type == CheckType.REUSED_RECEIPT))
    if hits and already is None:
        db.add(EvidenceCheck(evidence_id=ev.id, check_type=CheckType.REUSED_RECEIPT, status=CheckStatus.FLAG, findings_json={"backend": backend, "matches": [h.as_dict() for h in hits], "note": "Same receipt number already submitted. A lead for review, not proof of wrongdoing."}))
        workflow.say(db, req, f"\"{ev.original_filename}\" has the same receipt number as a document submitted earlier ({hits[0].source_id[:8]}), so I won't count it again. If it's a different receipt, please check the number.", step="evaluate_evidence", evidence_id=ev.id)
    retrieval.index(db, retrieval.doc_for_evidence(db, ev))


class ConfirmValuesIn(BaseModel):
    total: float = Field(ge=0, le=1_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    receipt_number: str | None = Field(default=None, max_length=100)
    merchant: str | None = Field(default=None, max_length=200)


class VisibilityIn(BaseModel):
    visibility: EvidenceVisibility


@router.post("/upload", response_model=ThreadOut)
async def upload(
    reporting_request_id: str = Form(...),
    kind: EvidenceKind = Form(...),
    claim_type: str | None = Form(None),
    claim_id: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    req = db.get(ReportingRequest, reporting_request_id)
    if req is None:
        raise HTTPException(404, "Reporting request not found")
    campaign = load_campaign_for_editor(db, user, req.campaign_id)

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"Files must be under {settings.max_upload_bytes // (1024 * 1024)} MB")
    mime = sniff_type(data)
    if mime is None:
        raise HTTPException(415, "Upload a JPEG, PNG, WebP or PDF file")

    claim = None
    if claim_id:
        model = {"expense": ExpenseClaim, "impact": ImpactClaim}.get(claim_type or "")
        claim = db.get(model, claim_id) if model else None
        if claim is None or claim.campaign_id != campaign.id:
            raise HTTPException(404, "Claim not found")

    evidence_id = new_id()
    rel = Path(campaign.id) / f"{evidence_id}{EXTENSIONS[mime]}"
    dest = settings.upload_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)

    ev = Evidence(
        id=evidence_id,
        campaign_id=campaign.id,
        reporting_request_id=req.id,
        uploaded_by_user_id=user.id,
        kind=kind,
        storage_key=str(rel),
        original_filename=(file.filename or "upload")[:255],
        file_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    db.add(ev)
    db.flush()
    if claim is not None:
        db.add(ClaimEvidence(claim_type=claim_type, claim_id=claim.id, evidence_id=ev.id))
        if claim.evidence_status == EvidenceReviewStatus.REPORTED:
            claim.evidence_status = EvidenceReviewStatus.SUBMITTED

    ngo_campaign_ids = list(db.scalars(select(Campaign.id).where(Campaign.ngo_id == campaign.ngo_id)))
    dups = find_exact_duplicates(db, ev, ngo_campaign_ids)
    if dups:
        db.add(EvidenceCheck(evidence_id=ev.id, check_type=CheckType.EXACT_DUPLICATE, status=CheckStatus.FLAG, findings_json={"matching_evidence_ids": [d.id for d in dups], "note": "Identical file uploaded before. A lead for review, not proof of wrongdoing."}))
        workflow.say(db, req, "This file is identical to one uploaded earlier, so I won't count it twice. If that was a mistake, upload the intended document.", step="evaluate_evidence", evidence_id=ev.id)

    if kind in (EvidenceKind.RECEIPT, EvidenceKind.PAYMENT_CONFIRMATION):
        ai = get_ai()
        extraction = None
        if ai is not None:
            try:
                extraction = ai.extract_receipt(data, mime)
            except AIUnavailable:
                extraction = None
        if extraction is not None:
            ev.extracted_json = extraction.model_dump(mode="json")
            db.add(EvidenceCheck(evidence_id=ev.id, check_type=CheckType.EXTRACTION, status=CheckStatus.PASS if extraction.total is not None else CheckStatus.INCONCLUSIVE, findings_json={"source": "ai", **ev.extracted_json}))
        else:
            workflow.say(db, req, f"I couldn't read \"{ev.original_filename}\" automatically. Please type the total shown on it.", step="request_more_information", evidence_id=ev.id)

    review_evidence(db, req, ev)
    audit(db, actor_type="user", actor_id=user.id, action="evidence.upload", entity_type="evidence", entity_id=ev.id, new={"sha256": ev.sha256, "kind": kind, "claim_id": claim_id})
    db.flush()
    runtime.dispatch(db, req, {"type": "evidence", "evidence_id": ev.id})
    db.commit()
    return build_thread(db, req, campaign)


@router.post("/{evidence_id}/confirm-values", response_model=ThreadOut)
def confirm_values(evidence_id: str, body: ConfirmValuesIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """NGO types or corrects the receipt values. Both AI-read and NGO-confirmed values stay on record."""
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    campaign = load_campaign_for_editor(db, user, ev.campaign_id)
    previous = ev.confirmed_json
    ev.confirmed_json = body.model_dump(mode="json") | {"currency": body.currency.upper()}
    ai_total = (ev.extracted_json or {}).get("total")
    if ai_total is not None and round(float(ai_total) * 100) != round(body.total * 100):
        db.add(EvidenceCheck(evidence_id=ev.id, check_type=CheckType.EXTRACTION, status=CheckStatus.FLAG, findings_json={"note": "NGO-entered total differs from the total the AI read", "ai_total": ai_total, "ngo_total": body.total}))
    audit(db, actor_type="user", actor_id=user.id, action="evidence.confirm_values", entity_type="evidence", entity_id=ev.id, previous=previous, new=ev.confirmed_json)
    req = db.get(ReportingRequest, ev.reporting_request_id)
    review_evidence(db, req, ev)
    runtime.dispatch(db, req, {"type": "evidence", "evidence_id": ev.id})
    db.commit()
    return build_thread(db, req, campaign)


@router.post("/{evidence_id}/visibility")
def set_visibility(evidence_id: str, body: VisibilityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    load_campaign_for_editor(db, user, ev.campaign_id)
    previous = ev.visibility
    ev.visibility = body.visibility
    audit(db, actor_type="user", actor_id=user.id, action="evidence.visibility", entity_type="evidence", entity_id=ev.id, previous={"visibility": previous}, new={"visibility": ev.visibility})
    db.commit()
    return {"id": ev.id, "visibility": ev.visibility}


@router.get("/{evidence_id}/file")
def get_file(evidence_id: str, user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    ev = db.get(Evidence, evidence_id)
    if ev is None:
        raise HTTPException(404, "Evidence not found")
    if ev.visibility != EvidenceVisibility.PUBLIC:
        if user is None:
            raise HTTPException(404, "Evidence not found")
        load_campaign_for_editor(db, user, ev.campaign_id)
    path = get_settings().upload_dir / ev.storage_key
    if not path.is_file():
        raise HTTPException(404, "This file is no longer stored on the server")
    return FileResponse(path, media_type=ev.file_type)
