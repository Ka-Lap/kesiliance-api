from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from .database import Base

class Entity(Base):
    __tablename__ = "entities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    country = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Sanction(Base):
    __tablename__ = "sanctions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    country = Column(String, nullable=True)   # ex: RU, US, IR...
    source = Column(String, nullable=True)    # ex: OFAC, EU, UN
    created_at = Column(DateTime, default=datetime.utcnow)

