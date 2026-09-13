import io
import json
import base64
from datetime import timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from reportlab.lib.pagesizes import letter
from sqlalchemy.orm import Session

import models
import schemas
from database import engine, get_db
from auth_utils import (
    hash_password, verify_password, create_access_token, get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from ocr_rules import (
    evaluate_label_rules, run_tesseract_ocr, extract_text_with_boxes,
    annotate_image, extract_text, run_rule_engine, score_and_verdict,
)
from report_generator import generate_compliance_pdf_report

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="PackSight API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "PackSight API"}


# ---------------------------------------------------------------- auth ----

@app.post("/auth/signup", response_model=schemas.TokenResponse)
def signup(payload: schemas.SignupRequest, db: Session = Depends(get_db)):
    normalized_id = payload.user_id.strip().lower()
    if not normalized_id or not payload.full_name.strip() or not payload.password:
        raise HTTPException(status_code=400, detail="All fields are required.")
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    existing = db.query(models.User).filter(models.User.user_id == normalized_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="That User ID is already taken.")

    user = models.User(
        user_id=normalized_id,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        {"sub": user.user_id}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return schemas.TokenResponse(
        access_token=token,
        token_type="bearer",
        full_name=user.full_name,
        user_id=user.user_id,
    )


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    normalized_id = payload.user_id.strip().lower()
    user = db.query(models.User).filter(models.User.user_id == normalized_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="No account found with that User ID.")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    token = create_access_token(
        {"sub": user.user_id}, expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return schemas.TokenResponse(
        access_token=token,
        token_type="bearer",
        full_name=user.full_name,
        user_id=user.user_id,
    )


# ---------------------------------------------------------------- scans ----

def _scan_to_response(scan: models.Scan) -> schemas.ScanResponse:
    raw = json.loads(scan.fields_json) if scan.fields_json else []
    fields_list = raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw
    return schemas.ScanResponse(
        id=scan.id,
        product_name=scan.product_name,
        created_at=scan.created_at,
        score=scan.score,
        has_violation=scan.has_violation,
        fail_count=scan.fail_count,
        raw_ocr_text=scan.raw_ocr_text or "",
        fields=[schemas.FieldResult(**f) for f in fields_list],
        annotated_image=getattr(scan, "annotated_image", None),
    )


@app.post("/scans", response_model=schemas.ScanResponse)
async def create_scan(
    image: UploadFile = File(...),
    product_name: str = Form("Untitled scan"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    image_bytes = await image.read()
    try:
        ocr_text, box_data = extract_text_with_boxes(image_bytes)
    except Exception as e:
        ocr_text = run_tesseract_ocr(image_bytes)
        box_data = {}

    eval_result = evaluate_label_rules(ocr_text)

    # Generate annotated image with bounding boxes around fail/review regions
    annotated_base64 = None
    try:
        annotated_bytes = annotate_image(image_bytes, box_data, eval_result["fields"])
        if annotated_bytes:
            annotated_base64 = base64.b64encode(annotated_bytes).decode("utf-8")
    except Exception as e:
        print(f"Annotation failed: {e}")

    scan = models.Scan(
        user_id=current_user.id,
        owner_id=current_user.id,
        product_name=product_name or "Untitled scan",
        score=eval_result["score"],
        has_violation=eval_result["has_violation"],
        fail_count=eval_result["fail_count"],
        raw_ocr_text=ocr_text,
        fields_json=json.dumps(eval_result["fields"]),
        annotated_image=annotated_base64,
    )
    db.add(scan)
    db.commit()
    db.refresh(scan)

    return _scan_to_response(scan)


@app.get("/scans", response_model=List[schemas.ScanResponse])
def list_scans(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scans = (
        db.query(models.Scan)
        .filter((models.Scan.user_id == current_user.id) | (models.Scan.owner_id == current_user.id))
        .order_by(models.Scan.created_at.desc())
        .all()
    )
    return [_scan_to_response(s) for s in scans]


@app.get("/stats", response_model=schemas.StatsResponse)
def get_stats(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scans = db.query(models.Scan).filter(
        (models.Scan.user_id == current_user.id) | (models.Scan.owner_id == current_user.id)
    ).all()
    total = len(scans)
    compliant = sum(1 for s in scans if not s.has_violation)
    violations = total - compliant
    avg_score = round(sum(s.score for s in scans) / total, 1) if total else None
    return schemas.StatsResponse(total=total, compliant=compliant, violations=violations, avg_score=avg_score)


@app.post("/scans/multi", response_model=schemas.ScanResponse)
async def create_multi_scan(
    product_name: str = Form("Untitled Product"),
    images: List[UploadFile] = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    combined_ocr_text = ""
    first_image_bytes = None
    first_box_data = {}

    for i, img in enumerate(images):
        contents = await img.read()
        if i == 0:
            first_image_bytes = contents
            try:
                panel_text, first_box_data = extract_text_with_boxes(contents)
            except Exception:
                panel_text = run_tesseract_ocr(contents)
        else:
            panel_text = run_tesseract_ocr(contents)
        combined_ocr_text += f"\n--- Panel ({img.filename}) ---\n" + panel_text

    eval_result = evaluate_label_rules(combined_ocr_text)

    annotated_base64 = None
    if first_image_bytes and first_box_data:
        try:
            annotated_bytes = annotate_image(first_image_bytes, first_box_data, eval_result["fields"])
            if annotated_bytes:
                annotated_base64 = base64.b64encode(annotated_bytes).decode("utf-8")
        except Exception as e:
            print(f"Multi annotation failed: {e}")

    db_scan = models.Scan(
        user_id=current_user.id,
        owner_id=current_user.id,
        product_name=product_name,
        score=eval_result["score"],
        has_violation=eval_result["has_violation"],
        fail_count=eval_result["fail_count"],
        raw_ocr_text=combined_ocr_text,
        fields_json=json.dumps(eval_result["fields"]),
        annotated_image=annotated_base64,
    )
    db.add(db_scan)
    db.commit()
    db.refresh(db_scan)

    return _scan_to_response(db_scan)


@app.get("/scans/{scan_id}/pdf")
async def download_scan_pdf(
    scan_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scan = db.query(models.Scan).filter(
        models.Scan.id == scan_id,
        (models.Scan.user_id == current_user.id) | (models.Scan.owner_id == current_user.id),
    ).first()

    if not scan:
        raise HTTPException(status_code=404, detail="Scan record not found.")

    raw = json.loads(scan.fields_json) if scan.fields_json else []
    fields = raw["fields"] if isinstance(raw, dict) and "fields" in raw else raw

    buffer = generate_compliance_pdf_report(
        scan_id=scan.id,
        product_name=scan.product_name or "Packaged Commodity",
        score=scan.score,
        has_violation=scan.has_violation,
        fields=fields,
        created_at=scan.created_at,
        user_name=current_user.full_name or current_user.user_id,
    )

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=packsight_report_{scan_id}.pdf"},
    )
