from app.connectors.base import BaseConnector
from typing import List, Dict, Any, Optional
from app.database import SessionLocal
from app.models.student import StudentCourse

class StudentConnector(BaseConnector):
    """Connector to fetch student course data from database"""
    
    def fetch(self, **kwargs) -> List[Dict[str, Any]]:
        """
        Fetch student course records with optional filters
        
        Args:
            account_id: Filter by student account ID
            course_code: Filter by course code
            course_name: Filter by course name
            batch: Filter by student batch
            term: Filter by term code
            min_marks: Minimum marks filter
            limit: Maximum number of records to return (default: 10)
        """
        db = SessionLocal()
        try:
            query = db.query(StudentCourse)
            
            # Apply filters
            if 'account_id' in kwargs and kwargs['account_id']:
                query = query.filter(StudentCourse.account_id == kwargs['account_id'])
            
            if 'course_code' in kwargs and kwargs['course_code']:
                query = query.filter(StudentCourse.course_code.ilike(kwargs['course_code']))

            if 'course_name' in kwargs and kwargs['course_name']:
                search_val = kwargs['course_name'].replace(' ', '%')
                query = query.filter(StudentCourse.course_name.ilike(f"%{search_val}%"))
            
            if 'batch' in kwargs and kwargs['batch']:
                batch_val = kwargs['batch'].replace(' ', '')
                query = query.filter(StudentCourse.student_batch.ilike(f"%{batch_val}%"))
            
            if 'term' in kwargs and kwargs['term']:
                query = query.filter(StudentCourse.term_code.ilike(kwargs['term']))
            
            if 'min_marks' in kwargs and kwargs['min_marks']:
                query = query.filter(StudentCourse.marks >= int(kwargs['min_marks']))
            
            # Apply limit
            limit = int(kwargs.get('limit', 10))
            query = query.limit(limit)
            
            # Execute query and convert to dict
            results = query.all()
            return [record.to_dict() for record in results]
            
        finally:
            db.close()
