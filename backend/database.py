"""
AURA — Database Layer
SQLite via SQLAlchemy for transaction history and fraud logs.
"""
import os
from datetime import datetime
from pathlib import Path
from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    Boolean, DateTime, Text, inspect,
)
from sqlalchemy.orm import declarative_base, sessionmaker

import os as _os

# Streamlit Cloud / Docker: only /tmp is writable.  Local dev: use data/ folder.
def _resolve_db_path() -> Path:
    local_data = Path(__file__).parent.parent / "data"
    try:
        local_data.mkdir(exist_ok=True)
        test = local_data / ".write_test"
        test.touch(); test.unlink()
        return local_data / "aura.db"
    except OSError:
        return Path("/tmp") / "aura.db"

DB_PATH = _resolve_db_path()
ENGINE = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ENGINE)
Base = declarative_base()


class Transaction(Base):
    __tablename__ = "transactions"

    id              = Column(Integer, primary_key=True, index=True)
    transaction_id  = Column(String, unique=True, index=True)
    amount          = Column(Float)
    hour            = Column(Integer)
    day_of_week     = Column(Integer)
    merchant_cat    = Column(Integer)
    location_risk   = Column(Float)
    device_trust    = Column(Float)
    past_fraud_ct   = Column(Integer)
    velocity_1h     = Column(Integer)
    dist_home_km    = Column(Float)
    card_age_days   = Column(Integer)
    is_online       = Column(Boolean)

    fraud_probability = Column(Float)
    risk_level        = Column(String)    # Low / Medium / High
    is_fraud          = Column(Boolean)
    anomaly_score     = Column(Float)
    top_features      = Column(Text)      # JSON string

    timestamp = Column(DateTime, default=datetime.utcnow)
    source    = Column(String, default="manual")  # manual | stream


class KYCSubmission(Base):
    __tablename__ = "kyc_submissions"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    id_type = Column(String)
    id_number = Column(String)
    file_path = Column(String)
    status = Column(String, default="pending")
    submitted_at = Column(DateTime, default=datetime.utcnow)



def init_db():
    Base.metadata.create_all(bind=ENGINE)


def save_transaction(data: dict, db=None):
    """Persist a prediction result to the DB."""
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        # Coerce timestamp: SQLite DateTime column requires a datetime object, not a string
        row_data = dict(data)
        ts = row_data.get("timestamp")
        if isinstance(ts, str):
            try:
                row_data["timestamp"] = datetime.fromisoformat(ts)
            except ValueError:
                row_data["timestamp"] = datetime.utcnow()
        elif ts is None:
            row_data["timestamp"] = datetime.utcnow()

        row = Transaction(**row_data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        if close:
            db.close()


def get_recent_transactions(limit: int = 100) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Transaction).order_by(Transaction.id.desc()).limit(limit).all()
        return [_row_to_dict(r) for r in rows]
    finally:
        db.close()


def get_stats() -> dict:
    db = SessionLocal()
    try:
        total = db.query(Transaction).count()
        fraud = db.query(Transaction).filter(Transaction.is_fraud == True).count()
        return {
            "total": total,
            "fraud": fraud,
            "legit": total - fraud,
            "fraud_rate": round(fraud / total * 100, 2) if total else 0.0,
        }
    finally:
        db.close()


def _row_to_dict(row: Transaction) -> dict:
    return {c.key: getattr(row, c.key)
            for c in inspect(row).mapper.column_attrs}


def save_kyc_submission(username: str, id_type: str, id_number: str, file_bytes: bytes, filename: str, db=None):
    """Save uploaded KYC document to disk and persist a DB record.

    Returns the DB row.
    """
    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        # Ensure directory
        kyc_dir = Path(__file__).parent.parent / 'data' / 'kyc'
        kyc_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
        fp = kyc_dir / safe_name
        with open(fp, 'wb') as f:
            f.write(file_bytes)

        row = KYCSubmission(username=username, id_type=id_type, id_number=id_number, file_path=str(fp), status='pending')
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        if close:
            db.close()


# Initialise on import
init_db()
