#!/usr/bin/env python3
"""Idempotent receipt backfill from retained verified payment records."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import app,db,sales_engine
from migrations import upgrade
if __name__=='__main__':
    with app.app_context():
        upgrade(db)
        print('Verified historical payment records imported:',sales_engine.backfill())
