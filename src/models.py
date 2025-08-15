# src/models.py

import enum
from datetime import datetime
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, String, DateTime, Text,
    ForeignKey, Enum, Float
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# --- Enum-типы для PostgreSQL --- 
# Для SQLite они будут создаваться как VARCHAR

class SummaryStatus(enum.Enum):
    OK = "OK"
    FAILED = "FAILED"
    PENDING = "PENDING"

class DLQEntityType(enum.Enum):
    ARTICLE = "article"
    SUMMARY = "summary"

# --- Модели SQLAlchemy ---

class Source(Base):
    __tablename__ = 'sources'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    base_url = Column(String(2048), nullable=False)
    priority = Column(Integer, default=100)
    created_at = Column(DateTime, default=datetime.utcnow)

    articles = relationship("Article", back_populates="source")

class Article(Base):
    __tablename__ = 'articles'
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey('sources.id'))
    link = Column(String(2048), nullable=False, unique=True)
    title = Column(String, nullable=False)
    published_at = Column(DateTime, nullable=False)
    parsed_at = Column(DateTime, default=datetime.utcnow)
    lang = Column(String(2), default='ru')
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source = relationship("Source", back_populates="articles")
    summaries = relationship("Summary", back_populates="article")

class Summary(Base):
    __tablename__ = 'summaries'
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    summary_text = Column(Text, nullable=False)
    model = Column(String(255))
    provider = Column(String(255))
    temperature = Column(Float)
    tokens_used = Column(Integer)
    status = Column(Enum(SummaryStatus), default=SummaryStatus.PENDING)
    version = Column(Integer, default=1)
    prompt_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    article = relationship("Article", back_populates="summaries")

class Digest(Base):
    __tablename__ = 'digests'
    id = Column(Integer, primary_key=True)
    digest_key = Column(String(255), nullable=False, unique=True) # e.g., "daily_2024-05-31"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class DLQ(Base):
    __tablename__ = 'dlq'
    id = Column(Integer, primary_key=True)
    entity_type = Column(Enum(DLQEntityType))
    entity_ref = Column(String(2048)) # e.g., article link
    error_code = Column(String(255))
    error_payload = Column(Text)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    attempts = Column(Integer, default=1)