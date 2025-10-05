from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite local (un fichier dev.db sera créé à la racine du projet)
DATABASE_URL = "sqlite:///./dev.db"

# Pour SQLite, check_same_thread doit être à False
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dépendance FastAPI pour obtenir une session par requête
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

