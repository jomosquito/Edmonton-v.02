from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json
from app import db

class MyDB:
    def __init__(self):
        self.storage = {}

    def store_flow(self, flow):
        self.storage['flow'] = flow

    def get_flow(self):
        return self.storage.get('flow')

# Profile Model
class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(20), nullable=False)
    last_name = db.Column(db.String(20), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=True)
    pass_word = db.Column(db.String(200), nullable=False)
    privilages_ = db.Column(db.String(20), default='user')
    email_ = db.Column(db.String(100), nullable=True)
    usertokenid = db.Column(db.String(100), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    phoneN_ = db.Column(db.String(200), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    enroll_status = db.Column(db.String(200), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)

# StudentInitiatedDrop Model
class StudentInitiatedDrop(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(20), nullable=False)
    course_title = db.Column(db.String(200), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    date = db.Column(db.Date, nullable=False)
    signature = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)

# MedicalWithdrawalRequest Model
class MedicalWithdrawalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    
    # Student Information
    last_name = db.Column(db.String(100), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    middle_name = db.Column(db.String(100), nullable=True)
    myuh_id = db.Column(db.String(20), nullable=False)
    college = db.Column(db.String(100), nullable=False)
    plan_degree = db.Column(db.String(100), nullable=False)
    
    # Address Information
    address = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(50), nullable=False)
    zip_code = db.Column(db.String(20), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    
    # Withdrawal Information
    term_year = db.Column(db.String(50), nullable=False)
    last_date = db.Column(db.Date, nullable=False)
    reason_type = db.Column(db.String(50), nullable=False)  # Medical or Administrative
    details = db.Column(db.Text, nullable=False)
    
    # Questions
    financial_assistance = db.Column(db.Boolean, default=False)
    health_insurance = db.Column(db.Boolean, default=False)
    campus_housing = db.Column(db.Boolean, default=False)
    visa_status = db.Column(db.Boolean, default=False)
    gi_bill = db.Column(db.Boolean, default=False)
    
    # Courses as JSON
    courses = db.Column(db.Text, nullable=False) 
    
    # Acknowledgment & Signature
    initial = db.Column(db.String(10), nullable=False)
    signature = db.Column(db.String(100), nullable=True)
    signature_date = db.Column(db.Date, nullable=False)
    
    # File paths for uploaded documentation
    documentation_files = db.Column(db.Text, nullable=True)  # JSON array of file paths
    
    # Add a new field to store paths to generated PDFs
    generated_pdfs = db.Column(db.Text, nullable=True)  # JSON array of PDF file paths
    
    # Status and timestamps
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to access the requesting user's profile
    user = db.relationship('Profile', backref='medical_withdrawals')
    
    admin_viewed = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have viewed

    # Helper method to check if an admin has viewed the request
    def has_admin_viewed(self, admin_id):
        if not self.admin_viewed:
            return False
        viewed_by = json.loads(self.admin_viewed)
        return str(admin_id) in viewed_by
    
    # Helper property for display in the admin portal
    @property
    def request_type(self):
        return f"{self.reason_type} Term Withdrawal"