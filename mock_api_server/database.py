"""
SQLAlchemy setup: engine, session factory, and ORM models for the mock API server.
DB file is stored at mock_api_server/data.db
"""

import os
from datetime import date
from sqlalchemy import (
    create_engine, Column, String, Float, Integer, Date, Text, DateTime
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

# ── Engine ─────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ── Models ─────────────────────────────────────────────────────────────────────

class Customer(Base):
    __tablename__ = "customers"

    id            = Column(String, primary_key=True)   # e.g. CUST-001
    name          = Column(String, nullable=False)
    email         = Column(String)
    segment       = Column(String)                     # Premium / Standard / Basic
    account_since = Column(String)


class Order(Base):
    __tablename__ = "orders"

    id              = Column(String, primary_key=True)  # e.g. ORD-1001
    customer_id     = Column(String, nullable=False)
    status          = Column(String)                    # Delivered / In Transit / Processing
    purchase_date   = Column(String)
    amount          = Column(Float)
    delivery_status = Column(String)


class Product(Base):
    __tablename__ = "products"

    order_id        = Column(String, primary_key=True)  # 1:1 with order
    name            = Column(String, nullable=False)
    category        = Column(String)                    # food / electronics / pharma / appliances
    expiry_date     = Column(String)                    # ISO date string
    warranty_months = Column(Integer, default=0)


class Ticket(Base):
    __tablename__ = "tickets"

    id          = Column(String, primary_key=True)      # e.g. TICK-1001
    customer_id = Column(String, nullable=False)
    subject     = Column(String)
    description = Column(Text)
    priority    = Column(Integer, default=3)            # 1=urgent 2=high 3=medium 4=low
    status      = Column(String, default="open")        # open / pending / resolved / closed
    created_at  = Column(DateTime, server_default=func.now())


class Case(Base):
    __tablename__ = "cases"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    order_id    = Column(String)
    customer_id = Column(String)
    type        = Column(String)                        # refund / exchange / billing / warranty
    reason      = Column(Text)
    created_at  = Column(DateTime, server_default=func.now())


# ── Helper: get a DB session ────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Create tables ───────────────────────────────────────────────────────────────

def init_db():
    Base.metadata.create_all(bind=engine)
