#!/usr/bin/env python3
"""
Check users table schema for duplicate columns
"""
import os
import sys

# Must set DATABASE_URL before importing anything else
if 'DATABASE_URL' not in os.environ:
    db_url = os.getenv('DATABASE_PUBLIC_URL')
    if db_url:
        os.environ['DATABASE_URL'] = db_url

from sqlalchemy import create_engine, text, inspect

def check_users_table():
    """Check users table schema"""
    
    # Get database URL
    db_url = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set!")
        sys.exit(1)
    
    print(f"📊 Inspecting users table schema...")
    engine = create_engine(db_url)
    
    inspector = inspect(engine)
    
    # Get all columns
    columns = inspector.get_columns('users')
    
    print(f"\n" + "="*80)
    print(f"📋 USERS TABLE COLUMNS ({len(columns)} total)")
    print("="*80)
    
    # Look for Solana-related columns
    solana_columns = []
    polygon_columns = []
    
    for col in columns:
        col_name = col['name']
        col_type = str(col['type'])
        nullable = "NULL" if col['nullable'] else "NOT NULL"
        
        if 'solana' in col_name.lower():
            solana_columns.append(col_name)
            print(f"🔶 {col_name:45s} | {col_type:20s} | {nullable}")
        elif 'polygon' in col_name.lower():
            polygon_columns.append(col_name)
            print(f"🔷 {col_name:45s} | {col_type:20s} | {nullable}")
        else:
            print(f"   {col_name:45s} | {col_type:20s} | {nullable}")
    
    print("\n" + "="*80)
    print(f"🔶 SOLANA COLUMNS: {len(solana_columns)}")
    print("="*80)
    for col in solana_columns:
        print(f"   • {col}")
    
    print("\n" + "="*80)
    print(f"🔷 POLYGON COLUMNS: {len(polygon_columns)}")
    print("="*80)
    for col in polygon_columns:
        print(f"   • {col}")
    
    # Check for duplicates
    column_names = [col['name'] for col in columns]
    duplicates = [name for name in column_names if column_names.count(name) > 1]
    
    if duplicates:
        print("\n" + "="*80)
        print(f"⚠️  DUPLICATE COLUMNS FOUND!")
        print("="*80)
        for dup in set(duplicates):
            print(f"   ❌ {dup} (appears {column_names.count(dup)} times)")
    else:
        print("\n✅ No duplicate columns found")

if __name__ == "__main__":
    check_users_table()

