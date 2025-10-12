from fastapi import Body
import requests
import os, io, csv
from typing import List, Optional

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security.api_key import APIKeyHeader
from sqlalchemy.orm import Session
from rapidfuzz import fuzz

from .database import Base, engine, get_db
from . import models
from .schemas import (
    EntityCreate, EntityOut,
    SanctionCreate, SanctionOut,
    MatchOut,
)

# ─────────── DB init ───────────
Base.metadata.create_all(bind=engine)

# ─────────── App ───────────
app = FastAPI(title="KesiLiance API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en prod: remplace par ton domaine
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────── API Key (x-api-key) ───────────
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

def require_api_key(api_key: str = Security(api_key_header)):
    """
    Vérifie le header x-api-key contre la variable d'env API_KEY.
    Si API_KEY n'est pas définie côté serveur, on laisse passer (utile en dev local).
    """
    expected = os.getenv("API_KEY")
    if not expected:
        return
    if api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")

# ─────────── Health & Root (non protégés) ───────────
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Bienvenue sur KesiLiance API"}

# ─────────── Entities ───────────
@app.post("/entities", response_model=EntityOut)
def create_entity(
    payload: EntityCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    e = models.Entity(name=payload.name.strip(), country=payload.country)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e

@app.get("/entities", response_model=List[EntityOut])
def list_entities(
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    query = db.query(models.Entity)
    if q:
        query = query.filter(models.Entity.name.ilike(f"%{q}%"))
    items = query.order_by(models.Entity.id.desc()).offset(offset).limit(limit).all()
    return items

@app.post("/entities/import")
def import_entities(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Veuillez envoyer un fichier .csv")
    try:
        text_stream = io.TextIOWrapper(file.file, encoding="utf-8")
        reader = csv.DictReader(text_stream)
        if not reader.fieldnames or "name" not in [h.strip().lower() for h in reader.fieldnames]:
            raise HTTPException(status_code=400, detail="Le CSV doit contenir 'name' (et optionnellement 'country').")
        inserted = 0
        for row in reader:
            keys = {k.lower(): k for k in row.keys()}
            name = (row.get(keys.get("name"), "") or "").strip()
            if not name:
                continue
            country = (row.get(keys.get("country"), "") or "").strip() or None
            db.add(models.Entity(name=name, country=country))
            inserted += 1
        db.commit()
        return {"inserted": inserted}
    finally:
        try: file.file.close()
        except Exception: pass

# ─────────── Sanctions ───────────
@app.post("/sanctions/import")
def import_sanctions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Veuillez envoyer un fichier .csv")
    try:
        text_stream = io.TextIOWrapper(file.file, encoding="utf-8")
        reader = csv.DictReader(text_stream)
        lower_headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "name" not in lower_headers:
            raise HTTPException(status_code=400, detail="Le CSV doit contenir 'name'.")
        inserted = 0
        for row in reader:
            keys = {k.lower(): k for k in row.keys()}
            name = (row.get(keys.get("name"), "") or "").strip()
            if not name:
                continue
            country = (row.get(keys.get("country"), "") or "").strip() or None
            source = (row.get(keys.get("source"), "") or "").strip() or None
            db.add(models.Sanction(name=name, country=country, source=source))
            inserted += 1
        db.commit()
        return {"inserted": inserted}
    finally:
        try: file.file.close()
        except Exception: pass

@app.get("/sanctions", response_model=List[SanctionOut])
def list_sanctions(
    limit: int = 100,
    offset: int = 0,
    q: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    query = db.query(models.Sanction)
    if q:
        query = query.filter(models.Sanction.name.ilike(f"%{q}%"))
    if source:
        query = query.filter(models.Sanction.source == source)
    items = query.order_by(models.Sanction.id.desc()).offset(offset).limit(limit).all()
    return items

# ─────────── Matching ───────────
@app.get("/match/{entity_id}", response_model=List[MatchOut])
def match_entity(
    entity_id: int,
    threshold: int = 80,
    limit: int = 5,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    entity = db.get(models.Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    sanctions = db.query(models.Sanction).all()
    results: List[MatchOut] = []
    for s in sanctions:
        score = float(fuzz.WRatio(entity.name, s.name))
        if score >= threshold:
            results.append(MatchOut(
                sanction_id=s.id, name=s.name, source=s.source, country=s.country, score=score
            ))
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]

@app.get("/match/{entity_id}/csv")
def match_entity_csv(
    entity_id: int,
    threshold: int = 80,
    limit: int = 5,
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    entity = db.get(models.Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    sanctions = db.query(models.Sanction).all()
    rows = []
    for s in sanctions:
        score = float(fuzz.WRatio(entity.name, s.name))
        if score >= threshold:
            rows.append({
                "entity_id": entity_id,
                "entity_name": entity.name,
                "sanction_id": s.id,
                "sanction_name": s.name,
                "source": s.source or "",
                "country": s.country or "",
                "score": f"{score:.1f}",
            })
    rows.sort(key=lambda r: float(r["score"]), reverse=True)
    rows = rows[:limit]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["entity_id","entity_name","sanction_id","sanction_name","source","country","score"])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="matches_entity_{entity_id}.csv"'},
    )

@app.post("/admin/refresh_sanctions")
def admin_refresh_sanctions(
    source_url: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    r = requests.get(source_url, timeout=30)
    if r.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Download failed: {r.status_code}")
    content = r.content.decode("utf-8", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    lower = [h.strip().lower() for h in (reader.fieldnames or [])]
    if "name" not in lower:
        raise HTTPException(status_code=400, detail="CSV must include \name\.")
    inserted = 0
    for row in reader:
        keys = {k.lower(): k for k in row.keys()}
        name = (row.get(keys.get("name"), "") or "").strip()
        if not name:
            continue
        country = (row.get(keys.get("country"), "") or "").strip() or None
        source = (row.get(keys.get("source"), "") or "").strip() or None
        db.add(models.Sanction(name=name, country=country, source=source)); inserted += 1
    db.commit()
    return {\"inserted\": inserted, \"source_url\": source_url}
