from pydantic import BaseModel
from typing import Optional
from datetime import datetime

# ─── Entities ───
class EntityCreate(BaseModel):
    name: str
    country: Optional[str] = None

class EntityOut(BaseModel):
    id: int
    name: str
    country: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True  # Pydantic v2 : ORM mode


# ─── Sanctions ───
class SanctionCreate(BaseModel):
    name: str
    country: Optional[str] = None      # ex: RU, IR, US...
    source: Optional[str] = None       # ex: OFAC, EU, UN

class SanctionOut(BaseModel):
    id: int
    name: str
    country: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Matching result ───
class MatchOut(BaseModel):
    sanction_id: int
    name: str
    source: Optional[str] = None
    country: Optional[str] = None
    score: float

