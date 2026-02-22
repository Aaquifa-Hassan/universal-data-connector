#!/usr/bin/env python3
"""
Import student data from CSV into SQLite database
"""
import sys
import os
import pandas as pd

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import engine, Base
from app.models.student import StudentCourse
from sqlalchemy.orm import Session

def import_csv_data(csv_path: str):
    """Import student data from CSV file into database"""
    
    print(f"Reading CSV file: {csv_path}")
    df = pd.read_csv(csv_path)
    
    print(f"Found {len(df)} records")
    
    # Create tables
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Create session
    session = Session(engine)
    
    try:
        # Clear existing data
        print("Clearing existing data...")
        session.query(StudentCourse).delete()
        session.commit()
        
        # Import data
        print("Importing data...")
        records_imported = 0
        
        for _, row in df.iterrows():
            student_course = StudentCourse(
                account_id=str(row['AccountID']),
                student_batch=str(row['StudentBatch']) if pd.notna(row['StudentBatch']) else None,
                course_code=str(row['course_code']),
                course_name=str(row['name']),
                marks=int(row['marks']),
                grade=str(row['grade']),
                result=str(row['result']),
                term_code=str(row['term_code']),
                order=int(row['order'])
            )
            session.add(student_course)
            records_imported += 1
            
            # Commit in batches of 1000
            if records_imported % 1000 == 0:
                session.commit()
                print(f"  Imported {records_imported} records...")
        
        # Final commit
        session.commit()
        print(f"✅ Successfully imported {records_imported} records!")
        
        # Verify import
        total_count = session.query(StudentCourse).count()
        print(f"✅ Database now contains {total_count} records")
        
    except Exception as e:
        print(f"❌ Error importing data: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    csv_file = "data/project_data.csv"
    
    if not os.path.exists(csv_file):
        print(f"❌ CSV file not found: {csv_file}")
        sys.exit(1)
    
    import_csv_data(csv_file)
