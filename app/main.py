from fastapi.responses import StreamingResponse
from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from rapidfuzz import fuzz
import io, csv

from .database import Base, engine, get_db
from . import models
from .schemas import EntityCreate, EntityOut, SanctionCreate, SanctionOut, MatchOut

# Crée les tables si elles n'existent pas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="KesiLiance API")

# CORS (en prod: remplace "*" par ton domaine)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"message": "Bienvenue sur KesiLiance API (local + DB)"}

# ─────────── Entities ───────────

@app.post("/entities", response_model=EntityOut)
def create_entity(payload: EntityCreate, db: Session = Depends(get_db)):
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
):
    query = db.query(models.Entity)
    if q:
        query = query.filter(models.Entity.name.ilike(f"%{q}%"))
    items = query.order_by(models.Entity.id.desc()).offset(offset).limit(limit).all()
    return items

@app.post("/entities/import")
def import_entities(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Veuillez envoyer un fichier .csv")

    try:
        text_stream = io.TextIOWrapper(file.file, encoding="utf-8")
        reader = csv.DictReader(text_stream)
        if not reader.fieldnames or "name" not in [h.strip().lower() for h in reader.fieldnames]:
            raise HTTPException(
                status_code=400,
                detail="Le CSV doit contenir une colonne 'name' (et optionnellement 'country')."
            )

        inserted = 0
        for row in reader:
            keys = {k.lower(): k for k in row.keys()}
            name = (row.get(keys.get("name"), "") or "").strip()
            if not name:
                continue
            country = (row.get(keys.get("country"), "") or "").strip() or None
            e = models.Entity(name=name, country=country)
            db.add(e)
            inserted += 1

        db.commit()
        return {"inserted": inserted}
    finally:
        try:
            file.file.close()
        except Exception:
            pass

# ─────────── Sanctions ───────────

@app.post("/sanctions/import")
def import_sanctions(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Veuillez envoyer un fichier .csv")

    try:
        text_stream = io.TextIOWrapper(file.file, encoding="utf-8")
        reader = csv.DictReader(text_stream)
        # colonnes requises: name ; colonnes optionnelles: country, source
        lower_headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "name" not in lower_headers:
            raise HTTPException(status_code=400, detail="Le CSV doit contenir une colonne 'name'.")

        inserted = 0
        for row in reader:
            keys = {k.lower(): k for k in row.keys()}
            name = (row.get(keys.get("name"), "") or "").strip()
            if not name:
                continue
            country = (row.get(keys.get("country"), "") or "").strip() or None
            source = (row.get(keys.get("source"), "") or "").strip() or None

            s = models.Sanction(name=name, country=country, source=source)
            db.add(s)
            inserted += 1

        db.commit()
        return {"inserted": inserted}

    finally:
        try:
            file.file.close()
        except Exception:
            pass

@app.get("/sanctions", response_model=List[SanctionOut])
def list_sanctions(
    limit: int = 100,
    offset: int = 0,
    q: Optional[str] = None,
    source: Optional[str] = None,
    db: Session = Depends(get_db),
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
    threshold: int = 80,   # 0-100
    limit: int = 5,
    db: Session = Depends(get_db),
):
    # récupérer l'entité
    entity = db.get(models.Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # récupérer toutes les sanctions
    sanctions = db.query(models.Sanction).all()
    results: List[MatchOut] = []
    for s in sanctions:
        score = float(fuzz.WRatio(entity.name, s.name))
        if score >= threshold:
            results.append(MatchOut(
                sanction_id=s.id, name=s.name, source=s.source, country=s.country, score=score
            ))

    # trier par score desc et limiter
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]

@app.get("/match/{entity_id}/csv")
def match_entity_csv(
    entity_id: int,
    threshold: int = 80,
    limit: int = 5,
    db: Session = Depends(get_db),
):
    # 1) récupérer l'entité
    entity = db.get(models.Entity, entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # 2) recalculer les matches (même logique que /match/{entity_id})
    sanctions = db.query(models.Sanction).all()
    rows = []
    for s in sanctions:
        from rapidfuzz import fuzz
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

    # 3) construire un CSV en mémoire
    import io, csv
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "entity_id","entity_name","sanction_id","sanction_name","source","country","score"
        ],
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(r)

    buf.seek(0)
    filename = f"matches_entity_{entity_id}.csv"
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

