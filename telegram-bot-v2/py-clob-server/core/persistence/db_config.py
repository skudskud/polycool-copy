"""
PostgreSQL Database Configuration
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

# Get database URL from environment (Railway provides this)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://localhost:5432/trading_bot')

# Create engine with Supabase-optimized settings
engine = create_engine(
    DATABASE_URL,
    pool_size=5,  # Reduced for Supabase pooler limits
    max_overflow=10,  # Reduced for Supabase pooler limits  
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=300,  # Recycle connections every 5 minutes (Supabase closes idle connections)
    connect_args={
        'connect_timeout': 10  # 10 second connection timeout
    },
    echo=False  # Set to True for SQL logging
)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create scoped session for thread safety
db_session = scoped_session(SessionLocal)

# Base class for models
Base = declarative_base()

def get_db_session():
    """Get database session"""
    return db_session()

def close_db_session():
    """Close database session"""
    db_session.remove()
