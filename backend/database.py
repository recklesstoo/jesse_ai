import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# Configuración de SQLite
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Usa variable de entorno o por defecto jesse_ai.db en la raíz del proyecto
DB_NAME = os.getenv("DB_NAME", "jesse_ai.db")
DB_PATH = os.path.join(BASE_DIR, "..", DB_NAME)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# check_same_thread=False es necesario para SQLite en FastAPI
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Dependencia para FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()