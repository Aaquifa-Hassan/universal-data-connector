from sqlalchemy import Column, Integer, String
from app.database import Base

class StudentCourse(Base):
    __tablename__ = "student_courses"
    
    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(String, index=True)
    student_batch = Column(String, nullable=True, index=True)
    course_code = Column(String, index=True)
    course_name = Column(String)
    marks = Column(Integer)
    grade = Column(String)
    result = Column(String)
    term_code = Column(String, index=True)
    order = Column(Integer)
    
    def to_dict(self):
        return {
            "id": self.id,
            "account_id": self.account_id,
            "student_batch": self.student_batch,
            "course_code": self.course_code,
            "course_name": self.course_name,
            "marks": self.marks,
            "grade": self.grade,
            "result": self.result,
            "term_code": self.term_code,
            "order": self.order
        }
