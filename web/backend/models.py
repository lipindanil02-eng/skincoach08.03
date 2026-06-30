"""
SQLAlchemy модели для веб-версии SkinCoach.
"""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True, nullable=True)
    username = Column(String, index=True, nullable=True)
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    trial_start = Column(DateTime, default=datetime.utcnow)
    subscription = Column(String, default="free")  # free | paid
    paid_until = Column(DateTime, nullable=True)
    bonus_days = Column(Integer, default=0)


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    photo_b64 = Column(Text, nullable=True)
    vision_data = Column(JSON, default=dict)
    reasoning_data = Column(JSON, default=dict)
    diagnosis = Column(String, nullable=True)
    risk = Column(JSON, default=dict)
    recommendations = Column(Text, nullable=True)
    questions = Column(JSON, default=list)
    answers = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProgramProgress(Base):
    __tablename__ = "program_progress"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    day = Column(Integer, default=0)
    week = Column(Integer, default=1)
    last_plan = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
