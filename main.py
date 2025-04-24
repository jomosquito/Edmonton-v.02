# Imports
from flask import Flask, render_template, url_for, request, redirect, session, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from wtforms import StringField, SubmitField, SelectMultipleField, BooleanField, TextAreaField, DateField, FileField
from wtforms.validators import DataRequired, Length, Email, Optional
from O365 import Account
from datetime import datetime, timedelta, date
from config import client_id, client_secret, SECRET_KEY
from form_utils import allowed_file, return_choice, generate_ferpa, generate_ssn_name
from sqlalchemy.orm import joinedload, relationship
import json
import os
import re
import uuid
import jwt

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
db = SQLAlchemy(app)

# Create upload directories
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'documentation'), exist_ok=True)
os.makedirs(os.path.join('static', 'pdfs'), exist_ok=True)
os.makedirs(os.path.join('static', 'temp'), exist_ok=True)

# Custom filter for JSON parsing
@app.template_filter('from_json')
def from_json(value):
    return json.loads(value) if value else []

# Microsoft OAuth Credentials
credentials = (client_id, client_secret)
scopes = ['Mail.ReadWrite', 'Mail.Send', 'email']

# Simple in-memory database for OAuth flows
class MyDB:
    def __init__(self):
        self.storage = {}

    def store_flow(self, flow):
        self.storage['flow'] = flow

    def get_flow(self):
        return self.storage.get('flow')

my_db = MyDB()

def serialize(flow):
    return json.dumps(flow)

def deserialize(flow_str):
    return json.loads(flow_str)

# Updated Profile Model with new fields for optional token claims
class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(20), nullable=True)
    last_name = db.Column(db.String(20), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=True)
    pass_word = db.Column(db.String(200), nullable=False)  # Hashed passwords
    privilages_ = db.Column(db.String(20), default='user')
    user_roles = db.relationship('UserRole', back_populates='user')
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
    
    def has_role(self, role_name):
        return any(role.role.name == role_name for role in self.user_roles)

    @property
    def is_department_chair(self):
        return any(role.role.name == "department_chair" for role in self.user_roles)
    
    @property
    def is_admin(self):
        return self.has_role('admin') or self.privilages_ == 'admin'
    
    @property
    def can_approve_forms(self):
        return self.is_admin or self.is_department_chair

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

    # Add a field for generated PDFs
    generated_pdfs = db.Column(db.Text, nullable=True)  # JSON array of PDF file paths

    # Admin viewed field similar to MedicalWithdrawalRequest
    admin_viewed = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have viewed

    # Add a new column to store admin approvals
    admin_approvals = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have approved

    def has_admin_viewed(self, admin_id):
        if not self.admin_viewed:
            return False
        viewed_by = json.loads(self.admin_viewed)
        return str(admin_id) in viewed_by

    def has_admin_approved(self, admin_id):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return str(admin_id) in approved_by
        except:
            return False

    def is_fully_approved(self):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return len(approved_by) >= 2
        except:
            return False

    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)


class WithdrawalHistory(db.Model):
    __tablename__ = 'withdrawal_history'
    id = db.Column(db.Integer, primary_key=True)
    withdrawal_id = db.Column(db.Integer, db.ForeignKey('medical_withdrawal_request.id'))
    admin_id = db.Column(db.Integer, db.ForeignKey('profile.id'))
    action = db.Column(db.String(20))  # 'approved', 'rejected'
    comments = db.Column(db.Text)
    action_date = db.Column(db.DateTime, default=datetime.utcnow)
    

    # Relationships
    withdrawal = db.relationship('MedicalWithdrawalRequest', backref='history_entries')
    admin = db.relationship('Profile', backref='withdrawal_actions')


# Medical/Administrative Withdrawal Request Model
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

    # Add a new column to store admin approvals (JSON array of admin IDs)
    admin_approvals = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have approved

    # Helper method to check if an admin has viewed the request
    def has_admin_viewed(self, admin_id):
        if not self.admin_viewed:
            return False
        viewed_by = json.loads(self.admin_viewed)
        return str(admin_id) in viewed_by

    # Helper method to check if an admin has approved the request
    def has_admin_approved(self, admin_id):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return str(admin_id) in approved_by
        except:
            return False

    # Helper method to check if request is fully approved (by 2 admins)
    def is_fully_approved(self):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return len(approved_by) >= 2
        except:
            return False

    # Helper property for display in the admin portal
    @property
    def request_type(self):
        return f"{self.reason_type} Term Withdrawal"


##### V3 Integration of New Forms #####
class FERPARequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False)
    time = db.Column(db.DateTime, server_default=db.func.now())
    pdf_link = db.Column(db.String(100), nullable=False)
    sig_link = db.Column(db.String(100))

    # Name and campus
    name = db.Column(db.String(25))
    campus = db.Column(db.String(25))

    # Officials
    official_choices = db.Column(db.String(100))  # comma-separated string
    official_other = db.Column(db.String(100))

    # Information
    info_choices = db.Column(db.String(100))  # comma-separated string
    info_other = db.Column(db.String(100))

    # Release
    release_choices = db.Column(db.String(100))  # comma-separated string
    release_other = db.Column(db.String(100))

    # Release and purpose
    release_to = db.Column(db.String(50))
    purpose = db.Column(db.String(25))
    additional_names = db.Column(db.String(50))

    # Essential info
    password = db.Column(db.String(25), nullable=False)
    peoplesoft_id = db.Column(db.String(25), nullable=False)
    date = db.Column(db.Date(), nullable=False)

    # Relationship to User model
    user = db.relationship('Profile', backref='ferpa_requests')

    admin_viewed = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have viewed

    # Add a new column to store admin approvals
    admin_approvals = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have approved

    def has_admin_viewed(self, admin_id):
        """Check if an admin has viewed this request"""
        if not self.admin_viewed:
            return False
        try:
            viewed_by = json.loads(self.admin_viewed)
            return str(admin_id) in viewed_by
        except:
            return False

    def has_admin_approved(self, admin_id):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return str(admin_id) in approved_by
        except:
            return False

    def is_fully_approved(self):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return len(approved_by) >= 2
        except:
            return False

class InfoChangeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    # Meta data
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    status = db.Column(db.String(10), nullable=False)
    time = db.Column(db.DateTime, server_default=db.func.now())
    pdf_link = db.Column(db.String(100), nullable=False)
    sig_link = db.Column(db.String(100))

    # Name and ID
    name = db.Column(db.String(25), nullable=False)
    peoplesoft_id = db.Column(db.String(6), nullable=False)

    # Choice for Name/SSN
    choice = db.Column(db.String(25), nullable=False)

    # Section A: Name Change
    fname_old = db.Column(db.String(25))
    mname_old = db.Column(db.String(25))
    lname_old = db.Column(db.String(25))
    sfx_old = db.Column(db.String(25))

    fname_new = db.Column(db.String(25))
    mname_new = db.Column(db.String(25))
    lname_new = db.Column(db.String(25))
    sfx_new = db.Column(db.String(25))

    # Reason for name change
    nmchg_reason = db.Column(db.String(25))

    # Section B: SSN Change
    ssn_old = db.Column(db.String(11))
    ssn_new = db.Column(db.String(11))

    # Reason for SSN change
    ssnchg_reason = db.Column(db.String(25))

    # Signature/Date
    date = db.Column(db.Date(), nullable=False)

    # Relationship to User model
    user = db.relationship('Profile', backref='infochange_requests')

    admin_viewed = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have viewed

    # Add a new column to store admin approvals
    admin_approvals = db.Column(db.Text, nullable=True)  # JSON array of admin IDs who have approved

    def has_admin_viewed(self, admin_id):
        """Check if an admin has viewed this request"""
        if not self.admin_viewed:
            return False
        try:
            viewed_by = json.loads(self.admin_viewed)
            return str(admin_id) in viewed_by
        except:
            return False

    def has_admin_approved(self, admin_id):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return str(admin_id) in approved_by
        except:
            return False

    def is_fully_approved(self):
        if not self.admin_approvals:
            return False
        try:
            approved_by = json.loads(self.admin_approvals)
            return len(approved_by) >= 2
        except:
            return False


### V3 Integration of New Forms ###

##### V3 Form Classes #####

class FERPAForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(min=2, max=25)])
    campus = StringField('Campus', validators=[DataRequired(), Length(min=2, max=25)])

    official_choices = SelectMultipleField("Select Officials", choices=[
        ('registrar', 'Office of the University Registrar'),
        ('aid', 'Scholarships and Financial Aid'),
        ('financial', 'Student Financial Services'),
        ('undergrad', 'Undergraduate Scholars & US (formally USD)'),
        ('advancement', 'University Advancement'),
        ('dean', 'Dean of Students Office'),
        ('other', 'Other')
    ], validators=[DataRequired()])

    official_other = StringField('Other Officials', validators=[Optional()])

    info_choices = SelectMultipleField("Select Info", choices=[
        ('advising', 'Academic Advising Profile/Information'),
        ('all_records', 'All University Records'),
        ('academics', 'Academic Records'),
        ('billing', 'Billing/Financial Aid'),
        ('disciplinary', 'Disciplinary'),
        ('transcripts', 'Grades/Transcripts'),
        ('housing', 'Housing'),
        ('photos', 'Photos'),
        ('scholarship', 'Scholarship and/or Honors'),
        ('other', 'Other')
    ], validators=[DataRequired()])

    info_other = StringField('Other Info', validators=[Optional()])

    release_to = StringField('Release to', validators=[DataRequired(), Length(max=25)])
    purpose = StringField('Purpose', validators=[DataRequired(), Length(max=25)])

    additional_names = StringField('Additional Individuals', validators=[Optional(), Length(max=25)])

    release_choices = SelectMultipleField('Select People', choices=[
        ('family', 'Family'),
        ('institution', 'Educational Institution'),
        ('award', 'Honor or Award'),
        ('employer', 'Employer/Prospective Employer'),
        ('media', 'Public or Media of Scholarship'),
        ('other', 'Other')
    ], validators=[DataRequired()])

    release_other = StringField('Other Releases', validators=[Optional()])

    password = StringField('Password', validators=[DataRequired(), Length(min=5, max=16)])
    peoplesoft_id = StringField('PSID', validators=[DataRequired(), Length(min=7, max=7)])

    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])

    is_draft = BooleanField('Save as Draft?')

    submit = SubmitField('Submit FERPA')

class InfoChangeForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=25)])
    peoplesoft_id = StringField('UH ID', validators=[DataRequired(), Length(min=6, max=6)])

    choice = SelectMultipleField("Choose", choices=[
        ('name', 'Update Name (Complete Section A)'),
        ('ssn', 'Update SSN (Complete Section B)')
    ], validators=[DataRequired()])

    # Section A: Name Change
    first_name_old = StringField('Old Name', validators=[Optional(), Length(max=25)])
    middle_name_old = StringField('Old Mid. Name', validators=[Optional(), Length(max=25)])
    last_name_old = StringField('Old Last Name', validators=[Optional(), Length(max=25)])
    suffix_old = StringField('Old Suffix', validators=[Optional(), Length(max=10)])

    first_name_new = StringField('New Name', validators=[Optional(), Length(max=25)])
    middle_name_new = StringField('New Mid. Name', validators=[Optional(), Length(max=25)])
    last_name_new = StringField('New Last Name', validators=[Optional(), Length(max=25)])
    suffix_new = StringField('New Suffix', validators=[Optional(), Length(max=10)])

    # Reason for name change checkbox
    name_change_reason = SelectMultipleField("Reason for Name Change", choices=[
        ('marriage', 'Marriage/Divorce'),
        ('court', 'Court Order'),
        ('error', 'Correction of Error')
    ], validators=[Optional()])

    # Section B: SSN Change
    ssn_old = StringField('Old SSN', validators=[Optional(), Length(max=11)])
    ssn_new = StringField('New SSN', validators=[Optional(), Length(max=11)])

    # Reason for SSN change checkbox
    ssn_change_reason = SelectMultipleField("Reason for SSN Change", choices=[
        ('error', 'Correction of Error'),
        ('addition', 'Addition of SSN to University Records')
    ], validators=[Optional()])

    # Signature and date
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])

    is_draft = BooleanField('Save as Draft?')

    submit = SubmitField('Submit Name/SSN Change')

##### V3 Form Classes #####

# Add after your existing models but before routes
class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True)  # student, department_chair, president
    level = db.Column(db.Integer)  # 1=student, 2=chair, 3=president
    user_roles = db.relationship('UserRole', back_populates='role')

class OrganizationalUnit(db.Model):
    __tablename__ = 'organizational_units'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('organizational_units.id'), nullable=True)
    level = db.Column(db.Integer, default=1)  # Hierarchy level (1=top level, 2=second level, etc.)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Self-referential relationship for hierarchy
    children = db.relationship('OrganizationalUnit', 
                               backref=db.backref('parent', remote_side=[id]),
                               cascade="all, delete-orphan")
    
    # Other relationships
    departments = db.relationship('Department', backref='organizational_unit', cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<OrganizationalUnit {self.name}>"
    
    @property
    def full_path(self):
        """Get the full hierarchical path to this unit"""
        if self.parent:
            return f"{self.parent.full_path} > {self.name}"
        return self.name

# Update Department model to include organizational unit relationship
class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    org_unit_id = db.Column(db.Integer, db.ForeignKey('organizational_units.id'), nullable=True)
    chairs = db.relationship('UserRole', back_populates='department')
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Add ApprovalWorkflow and Step models for dynamic approval workflows
class ApprovalWorkflow(db.Model):
    __tablename__ = 'approval_workflows'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    form_type = db.Column(db.String(50), nullable=False)  # Type of form this workflow applies to
    org_unit_id = db.Column(db.Integer, db.ForeignKey('organizational_units.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    steps = db.relationship('ApprovalStep', backref='workflow', cascade="all, delete-orphan", order_by="ApprovalStep.order")
    org_unit = db.relationship('OrganizationalUnit')
    department = db.relationship('Department')
    
    def __repr__(self):
        return f"<ApprovalWorkflow {self.name}>"

class ApprovalStep(db.Model):
    __tablename__ = 'approval_steps'
    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey('approval_workflows.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False)  # Order in the workflow
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    approver_role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    org_unit_id = db.Column(db.Integer, db.ForeignKey('organizational_units.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    min_approvers = db.Column(db.Integer, default=1)  # Minimum approvers needed
    active = db.Column(db.Boolean, default=True)
    
    # Relationships
    approver_role = db.relationship('Role')
    org_unit = db.relationship('OrganizationalUnit')
    department = db.relationship('Department')
    
    def __repr__(self):
        return f"<ApprovalStep {self.name} (Order: {self.order})>"

# Add model for delegations
class ApprovalDelegation(db.Model):
    __tablename__ = 'approval_delegations'
    id = db.Column(db.Integer, primary_key=True)
    delegator_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    delegate_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    org_unit_id = db.Column(db.Integer, db.ForeignKey('organizational_units.id'), nullable=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    delegator = db.relationship('Profile', foreign_keys=[delegator_id], backref='delegated_approvals')
    delegate = db.relationship('Profile', foreign_keys=[delegate_id], backref='received_delegations')
    role = db.relationship('Role')
    department = db.relationship('Department')
    org_unit = db.relationship('OrganizationalUnit')
    
    def __repr__(self):
        return f"<Delegation from {self.delegator_id} to {self.delegate_id}>"
    
    @property
    def is_active(self):
        """Check if the delegation is currently active"""
        now = datetime.utcnow()
        return (self.active and 
                self.start_date <= now and 
                self.end_date >= now)

# Enhanced tracking for form approvals
class FormApproval(db.Model):
    __tablename__ = 'form_approvals'
    id = db.Column(db.Integer, primary_key=True)
    form_type = db.Column(db.String(50), nullable=False)  # 'medical_withdrawal', 'ferpa', etc.
    form_id = db.Column(db.Integer, nullable=False)  # ID of the form record
    step_id = db.Column(db.Integer, db.ForeignKey('approval_steps.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    delegated_by_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=True)  # If approval was delegated
    status = db.Column(db.String(20), nullable=False)  # 'approved', 'rejected', 'pending'
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    step = db.relationship('ApprovalStep')
    approver = db.relationship('Profile', foreign_keys=[approver_id])
    delegated_by = db.relationship('Profile', foreign_keys=[delegated_by_id])
    
    def __repr__(self):
        return f"<FormApproval {self.form_type}:{self.form_id} by {self.approver_id}>"

class UserRole(db.Model):
    __tablename__ = 'user_roles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    role = db.relationship('Role', back_populates='user_roles')
    department = db.relationship('Department')
    user = db.relationship('Profile', back_populates='user_roles')


@app.before_request
def check_user_active():
    user_id = session.get('user_id')
    if user_id:
        user = Profile.query.get(user_id)
        if user and not user.active and user.privilages_ != 'admin':
            session.clear()  # Clear session to prevent further access
            return redirect(url_for('deactivated'))  # Redirect to a deactivated page


# -------------------------------
# V3 Routes
# -------------------------------

@app.route('/ferpa-form', methods=['GET', 'POST'])
def ferpa_form():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    form = FERPAForm()

    if form.validate_on_submit():
        # Handle file upload for signature
        if 'signature' not in request.files:
            flash('Signature was not uploaded.', 'danger')
            return redirect(url_for('status'))  # Make sure this is correct

        file = request.files['signature']
        if file.filename == '':
            flash('No file selected for signature.', 'danger')
            return render_template('ferpa_form.html', form=form, user=user)

        # Check if file type is allowed
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
            try:
                # Generate a unique name for the image
                unique_filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()

                # Create the signatures directory if it doesn't exist
                signatures_dir = os.path.join('static', 'uploads', 'signatures')
                os.makedirs(signatures_dir, exist_ok=True)

                # Save file with new name
                filepath = os.path.join(signatures_dir, unique_filename)
                file.save(filepath)

                # Use forward slashes for LaTeX compatibility
                latex_path = filepath.replace("\\", "/")

                # Build data dictionary for the PDF
                official_choices = form.official_choices.data
                info_choices = form.info_choices.data
                release_choices = form.release_choices.data

                data = {
                    "NAME": form.name.data,
                    "CAMPUS": form.campus.data,

                    "OPT_REGISTRAR": return_choice(official_choices, 'registrar'),
                    "OPT_AID": return_choice(official_choices, 'aid'),
                    "OPT_FINANCIAL": return_choice(official_choices, 'financial'),
                    "OPT_UNDERGRAD": return_choice(official_choices, 'undergrad'),
                    "OPT_ADVANCEMENT": return_choice(official_choices, 'advancement'),
                    "OPT_DEAN": return_choice(official_choices, 'dean'),
                    "OPT_OTHER_OFFICIALS": return_choice(official_choices, 'other'),
                    "OTHEROFFICIALS": form.official_other.data,

                    "OPT_ACADEMIC_INFO": return_choice(info_choices, 'advising'),
                    "OPT_UNIVERSITY_RECORDS": return_choice(info_choices, 'all_records'),
                    "OPT_ACADEMIC_RECORDS": return_choice(info_choices, 'academics'),
                    "OPT_BILLING": return_choice(info_choices, 'billing'),
                    "OPT_DISCIPLINARY": return_choice(info_choices, 'disciplinary'),
                    "OPT_TRANSCRIPTS": return_choice(info_choices, 'transcripts'),
                    "OPT_HOUSING": return_choice(info_choices, 'housing'),
                    "OPT_PHOTOS": return_choice(info_choices, 'photos'),
                    "OPT_SCHOLARSHIP": return_choice(info_choices, 'scholarship'),
                    "OPT_OTHER_INFO": return_choice(info_choices, 'other'),
                    "OTHERINFO": form.info_other.data,

                    "RELEASE": form.release_to.data,
                    "PURPOSE": form.purpose.data,
                    "ADDITIONALS": form.additional_names.data,

                    "OPT_FAMILY": return_choice(release_choices, 'family'),
                    "OPT_INSTITUTION": return_choice(release_choices, 'institution'),
                    "OPT_HONOR": return_choice(release_choices, 'award'),
                    "OPT_EMPLOYER": return_choice(release_choices, 'employer'),
                    "OPT_PUBLIC": return_choice(release_choices, 'media'),
                    "OPT_OTHER_RELEASE": return_choice(release_choices, 'other'),
                    "OTHERRELEASE": form.release_other.data,

                    "PASSWORD": form.password.data,
                    "PEOPLESOFT": form.peoplesoft_id.data,
                    "SIGNATURE": latex_path,
                    "DATE": str(form.date.data)
                }

                # Create form directories if they don't exist
                forms_dir = os.path.join('static', 'forms')
                os.makedirs(forms_dir, exist_ok=True)

                # Generate PDF with debug output
                print(f"Generating FERPA PDF with data: {data}")
                pdf_file = generate_ferpa(data, forms_dir, signatures_dir)
                print(f"Generated PDF file: {pdf_file}")

                if not pdf_file:
                    flash('Error generating PDF. Please try again.', 'danger')
                    return render_template('ferpa_form.html', form=form, user=user)

                # Store options as comma-separate string
                official_choices_str = ",".join(form.official_choices.data)
                info_choices_str = ",".join(form.info_choices.data)
                release_choices_str = ",".join(form.release_choices.data)

                # Set status based on draft checkbox
                status = "draft" if form.is_draft.data else "pending"

                # Convert string date to DateTime
                try:
                    date_obj = datetime.strptime(str(form.date.data), '%Y-%m-%d').date()
                except ValueError:
                    date_obj = date.today()

                # Create new FERPA request
                new_ferpa_request = FERPARequest(
                    user_id=user_id,
                    status=status,
                    pdf_link=pdf_file,
                    sig_link=unique_filename,
                    name=data['NAME'],
                    campus=data['CAMPUS'],
                    official_choices=official_choices_str,
                    official_other=data['OTHEROFFICIALS'],
                    info_choices=info_choices_str,
                    info_other=data['OTHERINFO'],
                    release_choices=release_choices_str,
                    release_other=data['OTHERRELEASE'],
                    release_to=data['RELEASE'],
                    purpose=data['PURPOSE'],
                    additional_names=data['ADDITIONALS'],
                    password=data['PASSWORD'],
                    peoplesoft_id=data['PEOPLESOFT'],
                    date=date_obj
                )

                # Commit FERPA request to database
                db.session.add(new_ferpa_request)
                db.session.commit()



                print(f"Created FERPA request with ID: {new_ferpa_request.id}")

                if form.is_draft.data:
                    flash('FERPA request saved as draft.', 'success')
                else:
                    flash('FERPA request submitted successfully.', 'success')

                return redirect(url_for('status'))
            except Exception as e:
                import traceback
                print(f"Error in FERPA form submission: {str(e)}")
                print(traceback.format_exc())
                flash(f'An error occurred while processing your request: {str(e)}', 'danger')
                return render_template('ferpa_form.html', form=form, user=user)
        else:
            flash('Invalid file type. Please upload a PNG, JPG, or GIF image.', 'danger')
            return render_template('ferpa_form.html', form=form, user=user)

    if request.method == 'POST':
        print("Form submitted")

    if not form.validate():
        print(f"Form validation errors: {form.errors}")
        flash(f"Form validation errors: {form.errors}", "danger")

        # Return the form with validation errors
        today_date = date.today().strftime('%Y-%m-%d')
        return render_template('ferpa_form.html', form=form, user=user, today_date=today_date)

@app.route('/name-ssn-change', methods=['GET', 'POST'])
def name_ssn_change():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    form = InfoChangeForm()

    # Process form submission...
    if form.validate_on_submit():
        # Handle file upload for signature
        if 'signature' not in request.files:
            flash('Signature was not uploaded.', 'danger')
            return redirect(url_for('status'))

        file = request.files['signature']
        if file.filename == '':
            flash('No file selected for signature.', 'danger')
            return render_template('name_ssn_change.html', form=form, user=user, today_date=date.today().strftime('%Y-%m-%d'))

        # Check if file type is allowed
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
            try:
                # Generate a unique name for the image
                unique_filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()

                # Create the signatures directory if it doesn't exist
                signatures_dir = os.path.join('static', 'uploads', 'signatures')
                os.makedirs(signatures_dir, exist_ok=True)

                # Save file with new name
                filepath = os.path.join(signatures_dir, unique_filename)
                file.save(filepath)

                # Use forward slashes for LaTeX compatibility
                latex_path = filepath.replace("\\", "/")

                # Build data dictionary for the PDF
                choice_options = form.choice.data if form.choice.data else []  # Add this check
                name_change_reason = form.name_change_reason.data if form.name_change_reason.data else []  # And this check
                ssn_change_reason = form.ssn_change_reason.data if form.ssn_change_reason.data else []  # And this check

                data = {
                    "NAME": form.name.data,
                    "PEOPLESOFT": form.peoplesoft_id.data,
                    "EDIT_NAME": return_choice(choice_options, 'name'),
                    "EDIT_SSN": return_choice(choice_options, 'ssn'),
                    "FN_OLD": form.first_name_old.data or "",
                    "MN_OLD": form.middle_name_old.data or "",
                    "LN_OLD": form.last_name_old.data or "",
                    "SUF_OLD": form.suffix_old.data or "",
                    "FN_NEW": form.first_name_new.data or "",
                    "MN_NEW": form.middle_name_new.data or "",
                    "LN_NEW": form.last_name_new.data or "",
                    "SUF_NEW": form.suffix_new.data or "",
                    "OPT_MARITAL": return_choice(name_change_reason, 'marriage'),
                    "OPT_COURT": return_choice(name_change_reason, 'court'),
                    "OPT_ERROR_NAME": return_choice(name_change_reason, 'error'),
                    "SSN_OLD": form.ssn_old.data or "",
                    "SSN_NEW": form.ssn_new.data or "",
                    "OPT_ERROR_SSN": return_choice(ssn_change_reason, 'error'),
                    "OPT_ADD_SSN": return_choice(ssn_change_reason, 'addition'),
                    "SIGNATURE": latex_path,
                    "DATE": str(form.date.data)
                }

                # Create form directories if they don't exist
                forms_dir = os.path.join('static', 'forms')
                os.makedirs(forms_dir, exist_ok=True)

                # Generate PDF with debug output
                print(f"Generating Name/SSN Change PDF with data: {data}")
                pdf_file = generate_ssn_name(data, forms_dir, signatures_dir)
                print(f"Generated PDF file: {pdf_file}")

                if not pdf_file:
                    flash('Error generating PDF. Please try again.', 'danger')
                    return render_template('name_ssn_change.html', form=form, user=user, today_date=date.today().strftime('%Y-%m-%d'))

                # Store options as comma-separate string
                choice_str = ",".join(form.choice.data) if form.choice.data else ""
                name_change_reason_str = ",".join(form.name_change_reason.data) if form.name_change_reason.data else ""
                ssn_change_reason_str = ",".join(form.ssn_change_reason.data) if form.ssn_change_reason.data else ""

                # Set status based on draft checkbox
                status = "draft" if form.is_draft.data else "pending"

                # Convert string date to DateTime
                try:
                    date_obj = datetime.strptime(str(form.date.data), '%Y-%m-%d').date()
                except ValueError:
                    date_obj = date.today()

                # Create new info change request
                new_infochange_request = InfoChangeRequest(
                    user_id=user_id,
                    status=status,
                    pdf_link=pdf_file,
                    sig_link=unique_filename,
                    name=data['NAME'],
                    peoplesoft_id=data['PEOPLESOFT'],
                    choice=choice_str,
                    fname_old=data['FN_OLD'],
                    mname_old=data['MN_OLD'],
                    lname_old=data['LN_OLD'],
                    sfx_old=data['SUF_OLD'],
                    fname_new=data['FN_NEW'],
                    mname_new=data['MN_NEW'],
                    lname_new=data['LN_NEW'],
                    sfx_new=data['SUF_NEW'],
                    nmchg_reason=name_change_reason_str,
                    ssn_old=data['SSN_OLD'],
                    ssn_new=data['SSN_NEW'],
                    ssnchg_reason=ssn_change_reason_str,
                    date=date_obj
                )

                # Commit info change request to database
                db.session.add(new_infochange_request)
                db.session.commit()

                print(f"Created Info Change request with ID: {new_infochange_request.id}")

                if form.is_draft.data:
                    flash('Name/SSN change request saved as draft.', 'success')
                else:
                    flash('Name/SSN change request submitted successfully.', 'success')

                return redirect(url_for('status'))
            except Exception as e:
                import traceback
                print(f"Error in Name/SSN change form submission: {str(e)}")
                print(traceback.format_exc())
                flash(f'An error occurred while processing your request: {str(e)}', 'danger')
                today_date = date.today().strftime('%Y-%m-%d')
                return render_template('name_ssn_change.html', form=form, user=user, today_date=today_date)
        else:
            flash('Invalid file type. Please upload a PNG, JPG, or GIF image.', 'danger')
            today_date = date.today().strftime('%Y-%m-%d')
            return render_template('name_ssn_change.html', form=form, user=user, today_date=today_date)

    if request.method == 'POST':
        print("Form submitted")

    if not form.validate():
        print(f"Form validation errors: {form.errors}")
        flash(f"Form validation errors: {form.errors}", "danger")

        # Return the form with validation errors
        today_date = date.today().strftime('%Y-%m-%d')
        return render_template('name_ssn_change.html', form=form, user=user, today_date=today_date)

    # Set default date to today
    if request.method == 'GET':
        form.date.data = date.today()
        # Pre-populate with user's name if available
        if user.first_name:
            form.name.data = f"{user.first_name} {user.last_name}"
            form.first_name_old.data = user.first_name
            form.last_name_old.data = user.last_name

    # Always pass today_date variable to the template
    today_date = date.today().strftime('%Y-%m-%d')
    return render_template('name_ssn_change.html', form=form, user=user, today_date=today_date)

# Update the status route to include the new request types
@app.route('/status')
def status():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Query all types of requests for the logged-in user
    medical_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id).all()
    student_drop_requests = StudentInitiatedDrop.query.filter_by(student_id=str(user_id)).all()
    ferpa_requests = FERPARequest.query.filter_by(user_id=user_id).all()
    infochange_requests = InfoChangeRequest.query.filter_by(user_id=user_id).all()

    # Debug: Print counts to console
    print(f"Status page for user {user_id}:")
    print(f"Medical requests: {len(medical_requests)}")
    print(f"Student drop requests: {len(student_drop_requests)}")
    print(f"FERPA requests: {len(ferpa_requests)}")
    print(f"Name/SSN change requests: {len(infochange_requests)}")

    return render_template(
        'status.html',
        medical_requests=medical_requests,
        student_drop_requests=student_drop_requests,
        ferpa_requests=ferpa_requests,
        infochange_requests=infochange_requests
    )

# Modified routes for FERPA and Name/SSN PDF downloads

@app.route('/download_ferpa_pdf/<int:request_id>')
def download_ferpa_pdf(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    ferpa_request = FERPARequest.query.get_or_404(request_id)

    # Check if user is owner of the request or an admin
    user = Profile.query.get(user_id)
    if ferpa_request.user_id != user_id and user.privilages_ != 'admin':
        flash('You do not have permission to access this file.', 'danger')
        return redirect(url_for('status'))

    # Get the absolute path to the forms directory
    current_dir = os.path.abspath(os.getcwd())
    forms_dir = os.path.join(current_dir, 'static', 'forms')
    pdf_path = os.path.join(forms_dir, ferpa_request.pdf_link)

    # Debug output
    print(f"Looking for FERPA PDF at: {pdf_path}")
    print(f"File exists: {os.path.exists(pdf_path)}")

    if not os.path.exists(pdf_path):
        # Try to regenerate the PDF if it doesn't exist
        try:
            # Get signature path
            sig_path = os.path.join(current_dir, 'static', 'uploads', 'signatures', ferpa_request.sig_link)

            # Extract data from the request object
            official_choices = ferpa_request.official_choices.split(',') if ferpa_request.official_choices else []
            info_choices = ferpa_request.info_choices.split(',') if ferpa_request.info_choices else []
            release_choices = ferpa_request.release_choices.split(',') if ferpa_request.release_choices else []

            # Rebuild data dictionary
            data = {
                "NAME": ferpa_request.name,
                "CAMPUS": ferpa_request.campus,
                "OPT_REGISTRAR": return_choice(official_choices, 'registrar'),
                "OPT_AID": return_choice(official_choices, 'aid'),
                "OPT_FINANCIAL": return_choice(official_choices, 'financial'),
                "OPT_UNDERGRAD": return_choice(official_choices, 'undergrad'),
                "OPT_ADVANCEMENT": return_choice(official_choices, 'advancement'),
                "OPT_DEAN": return_choice(official_choices, 'dean'),
                "OPT_OTHER_OFFICIALS": return_choice(official_choices, 'other'),
                "OTHEROFFICIALS": ferpa_request.official_other,
                "OPT_ACADEMIC_INFO": return_choice(info_choices, 'advising'),
                "OPT_UNIVERSITY_RECORDS": return_choice(info_choices, 'all_records'),
                "OPT_ACADEMIC_RECORDS": return_choice(info_choices, 'academics'),
                "OPT_BILLING": return_choice(info_choices, 'billing'),
                "OPT_DISCIPLINARY": return_choice(info_choices, 'disciplinary'),
                "OPT_TRANSCRIPTS": return_choice(info_choices, 'transcripts'),
                "OPT_HOUSING": return_choice(info_choices, 'housing'),
                "OPT_PHOTOS": return_choice(info_choices, 'photos'),
                "OPT_SCHOLARSHIP": return_choice(info_choices, 'scholarship'),
                "OPT_OTHER_INFO": return_choice(info_choices, 'other'),
                "OTHERINFO": ferpa_request.info_other,
                "RELEASE": ferpa_request.release_to,
                "PURPOSE": ferpa_request.purpose,
                "ADDITIONALS": ferpa_request.additional_names,
                "OPT_FAMILY": return_choice(release_choices, 'family'),
                "OPT_INSTITUTION": return_choice(release_choices, 'institution'),
                "OPT_HONOR": return_choice(release_choices, 'award'),
                "OPT_EMPLOYER": return_choice(release_choices, 'employer'),
                "OPT_PUBLIC": return_choice(release_choices, 'media'),
                "OPT_OTHER_RELEASE": return_choice(release_choices, 'other'),
                "OTHERRELEASE": ferpa_request.release_other,
                "PASSWORD": ferpa_request.password,
                "PEOPLESOFT": ferpa_request.peoplesoft_id,
                "SIGNATURE": sig_path,
                "DATE": str(ferpa_request.date)
            }

            # Regenerate PDF
            os.makedirs(forms_dir, exist_ok=True)
            new_pdf_file = generate_ferpa(data, forms_dir, os.path.join('static', 'uploads', 'signatures'))

            if new_pdf_file:
                # Update the database with the new PDF path
                ferpa_request.pdf_link = new_pdf_file
                db.session.commit()

                # Update the pdf_path to the new file
                pdf_path = os.path.join(forms_dir, new_pdf_file)
                print(f"Regenerated PDF at: {pdf_path}")

                if not os.path.exists(pdf_path):
                    flash('PDF file could not be regenerated.', 'danger')
                    return redirect(url_for('status'))
            else:
                flash('PDF file not found and could not be regenerated.', 'danger')
                return redirect(url_for('status'))

        except Exception as e:
            import traceback
            print(f"Error regenerating FERPA PDF: {str(e)}")
            print(traceback.format_exc())
            flash('PDF file not found and regeneration failed.', 'danger')
            return redirect(url_for('status'))

    try:
        return send_file(pdf_path, as_attachment=True)
    except Exception as e:
        print(f"Error sending file: {str(e)}")
        flash('Error accessing the PDF file.', 'danger')
        return redirect(url_for('status'))

@app.route('/download_infochange_pdf/<int:request_id>')
def download_infochange_pdf(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    infochange_request = InfoChangeRequest.query.get_or_404(request_id)

    # Check if user is owner of the request or an admin
    user = Profile.query.get(user_id)
    if infochange_request.user_id != user_id and user.privilages_ != 'admin':
        flash('You do not have permission to access this file.', 'danger')
        return redirect(url_for('status'))

    # Get the absolute path to the forms directory
    current_dir = os.path.abspath(os.getcwd())
    forms_dir = os.path.join(current_dir, 'static', 'forms')
    pdf_path = os.path.join(forms_dir, infochange_request.pdf_link)

    # Debug output
    print(f"Looking for Name/SSN PDF at: {pdf_path}")
    print(f"File exists: {os.path.exists(pdf_path)}")

    if not os.path.exists(pdf_path):
        # Try to regenerate the PDF if it doesn't exist
        try:
            # Get signature path
            sig_path = os.path.join(current_dir, 'static', 'uploads', 'signatures', infochange_request.sig_link)

            # Extract data from the request object
            choice = infochange_request.choice.split(',') if infochange_request.choice else []
            nmchg_reason = infochange_request.nmchg_reason.split(',') if infochange_request.nmchg_reason else []
            ssnchg_reason = infochange_request.ssnchg_reason.split(',') if infochange_request.ssnchg_reason else []

            # Rebuild data dictionary
            data = {
                "NAME": infochange_request.name,
                "PEOPLESOFT": infochange_request.peoplesoft_id,
                "EDIT_NAME": return_choice(choice, 'name'),
                "EDIT_SSN": return_choice(choice, 'ssn'),
                "FN_OLD": infochange_request.fname_old or "",
                "MN_OLD": infochange_request.mname_old or "",
                "LN_OLD": infochange_request.lname_old or "",
                "SUF_OLD": infochange_request.sfx_old or "",
                "FN_NEW": infochange_request.fname_new or "",
                "MN_NEW": infochange_request.mname_new or "",
                "LN_NEW": infochange_request.lname_new or "",
                "SUF_NEW": infochange_request.sfx_new or "",
                "OPT_MARITAL": return_choice(nmchg_reason, 'marriage'),
                "OPT_COURT": return_choice(nmchg_reason, 'court'),
                "OPT_ERROR_NAME": return_choice(nmchg_reason, 'error'),
                "SSN_OLD": infochange_request.ssn_old or "",
                "SSN_NEW": infochange_request.ssn_new or "",
                "OPT_ERROR_SSN": return_choice(ssnchg_reason, 'error'),
                "OPT_ADD_SSN": return_choice(ssnchg_reason, 'addition'),
                "SIGNATURE": sig_path,
                "DATE": str(infochange_request.date)
            }

            # Regenerate PDF
            os.makedirs(forms_dir, exist_ok=True)
            new_pdf_file = generate_ssn_name(data, forms_dir, os.path.join('static', 'uploads', 'signatures'))

            if new_pdf_file:
                # Update the database with the new PDF path
                infochange_request.pdf_link = new_pdf_file
                db.session.commit()

                # Update the pdf_path to the new file
                pdf_path = os.path.join(forms_dir, new_pdf_file)
                print(f"Regenerated PDF at: {pdf_path}")

                if not os.path.exists(pdf_path):
                    flash('PDF file could not be regenerated.', 'danger')
                    return redirect(url_for('status'))
            else:
                flash('PDF file not found and could not be regenerated.', 'danger')
                return redirect(url_for('status'))

        except Exception as e:
            import traceback
            print(f"Error regenerating Name/SSN PDF: {str(e)}")
            print(traceback.format_exc())
            flash('PDF file not found and regeneration failed.', 'danger')
            return redirect(url_for('status'))

    try:
        return send_file(pdf_path, as_attachment=True)
    except Exception as e:
        print(f"Error sending file: {str(e)}")
        flash('Error accessing the PDF file.', 'danger')
        return redirect(url_for('status'))


# Add admin routes for approving/rejecting FERPA and Info Change requests
@app.route('/approve_ferpa/<int:request_id>', methods=['POST'])
def approve_ferpa(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Check if user is admin
    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        flash('You do not have permission to approve requests.', 'danger')
        return redirect(url_for('notifications'))

    ferpa_request = FERPARequest.query.get_or_404(request_id)
    
    # Check if admin has viewed the PDF
    if not ferpa_request.has_admin_viewed(user_id):
        flash('You must view the request PDF before approving.', 'danger')
        return redirect(url_for('notifications'))
    
    # Check if this admin has already approved
    if ferpa_request.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))
    
    # Add admin to approvals list
    if not ferpa_request.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(ferpa_request.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    ferpa_request.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        ferpa_request.status = 'approved'
        flash('FERPA request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        ferpa_request.status = 'pending_approval'
        flash('FERPA request has been partially approved. Awaiting second approval.', 'success')
    
    # Update the admin_viewed field as well
    if hasattr(ferpa_request, 'admin_viewed'):
        if not ferpa_request.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(ferpa_request.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        ferpa_request.admin_viewed = json.dumps(admin_viewed)

    db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/simple_approve_ferpa/<int:request_id>', methods=['POST'])
def simple_approve_ferpa(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    ferpa_request = FERPARequest.query.get_or_404(request_id)
    
    # Add admin to approvals list
    if not ferpa_request.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(ferpa_request.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    ferpa_request.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        ferpa_request.status = 'approved'
        flash('FERPA request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        ferpa_request.status = 'pending_approval'
        flash('FERPA request has been partially approved. Awaiting second approval.', 'success')
    
    db.session.commit()
    return redirect(url_for('chair_student_drops'))

@app.route('/reject_ferpa/<int:request_id>', methods=['POST'])
def reject_ferpa(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Check if user is admin
    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        flash('You do not have permission to reject requests.', 'danger')
        return redirect(url_for('notifications'))

    ferpa_request = FERPARequest.query.get_or_404(request_id)
    ferpa_request.status = 'rejected'

    # If the model has an admin_viewed field, handle the admin viewing
    if hasattr(ferpa_request, 'admin_viewed'):
        if not ferpa_request.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(ferpa_request.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        ferpa_request.admin_viewed = json.dumps(admin_viewed)

    db.session.commit()

    flash('FERPA request rejected.', 'success')
    return redirect(url_for('notifications'))

@app.route('/simple_reject_ferpa/<int:request_id>', methods=['POST'])
def simple_reject_ferpa(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    ferpa_request = FERPARequest.query.get_or_404(request_id)
    ferpa_request.status = 'rejected'

    db.session.commit()

    flash('FERPA request rejected.', 'success')
    return redirect(url_for('chair_student_drops'))

@app.route('/approve_infochange/<int:request_id>', methods=['POST'])
def approve_infochange(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Check if user is admin
    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        flash('You do not have permission to approve requests.', 'danger')
        return redirect(url_for('notifications'))

    infochange_request = InfoChangeRequest.query.get_or_404(request_id)
    
    # Check if admin has viewed the PDF
    if not infochange_request.has_admin_viewed(user_id):
        flash('You must view the request PDF before approving.', 'danger')
        return redirect(url_for('notifications'))
    
    # Check if this admin has already approved
    if infochange_request.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))
    
    # Add admin to approvals list
    if not infochange_request.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(infochange_request.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    infochange_request.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        infochange_request.status = 'approved'
        flash('Name/SSN change request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        infochange_request.status = 'pending_approval'
        flash('Name/SSN change request has been partially approved. Awaiting second approval.', 'success')
    
    # Update the admin_viewed field as well
    if hasattr(infochange_request, 'admin_viewed'):
        if not infochange_request.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(infochange_request.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        infochange_request.admin_viewed = json.dumps(admin_viewed)

    db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/simple_approve_infochange/<int:request_id>', methods=['POST'])
def simple_approve_infochange(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    infochange_request = InfoChangeRequest.query.get_or_404(request_id)
    
    # Add user to approvals list
    if not infochange_request.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(infochange_request.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    infochange_request.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        infochange_request.status = 'approved'
        flash('Name/SSN change request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        infochange_request.status = 'pending_approval'
        flash('Name/SSN change request has been partially approved. Awaiting second approval.', 'success')

    db.session.commit()
    return redirect(url_for('chair_student_drops'))

@app.route('/reject_infochange/<int:request_id>', methods=['POST'])
def reject_infochange(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Check if user is admin
    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        flash('You do not have permission to reject requests.', 'danger')
        return redirect(url_for('notifications'))

    infochange_request = InfoChangeRequest.query.get_or_404(request_id)
    infochange_request.status = 'rejected'

    # If the model has an admin_viewed field, handle the admin viewing
    if hasattr(infochange_request, 'admin_viewed'):
        if not infochange_request.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(infochange_request.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        infochange_request.admin_viewed = json.dumps(admin_viewed)

    db.session.commit()

    flash('Name/SSN change request rejected.', 'success')
    return redirect(url_for('notifications'))

@app.route('/simple_reject_infochange/<int:request_id>', methods=['POST'])
def simple_reject_infochange(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    infochange_request = InfoChangeRequest.query.get_or_404(request_id)
    infochange_request.status = 'rejected'

    db.session.commit()

    flash('Name/SSN change request rejected.', 'success')
    return redirect(url_for('chair_student_drops'))

# Add routes for marking FERPA and Name/SSN forms as viewed by admin
@app.route('/mark_ferpa_viewed/<int:request_id>', methods=['POST'])
def mark_ferpa_viewed(request_id):
    """Mark a FERPA request as viewed by the current admin"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = FERPARequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Add admin to the viewed list if not already there
    if not req_record.admin_viewed:
        admin_viewed = [str(user_id)]
    else:
        admin_viewed = json.loads(req_record.admin_viewed)
        if str(user_id) not in admin_viewed:
            admin_viewed.append(str(user_id))

    req_record.admin_viewed = json.dumps(admin_viewed)
    db.session.commit()

    return {"success": True}

@app.route('/mark_infochange_viewed/<int:request_id>', methods=['POST'])
def mark_infochange_viewed(request_id):
    """Mark a Name/SSN change request as viewed by the current admin"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = InfoChangeRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Add admin to the viewed list if not already there
    if not req_record.admin_viewed:
        admin_viewed = [str(user_id)]
    else:
        admin_viewed = json.loads(req_record.admin_viewed)
        if str(user_id) not in admin_viewed:
            admin_viewed.append(str(user_id))

    req_record.admin_viewed = json.dumps(admin_viewed)
    db.session.commit()

    return {"success": True}

# -------------------------------
# V3 Routes
# -------------------------------


# Helper function to convert UTC to GMT-5
def utc_to_gmt5(utc_datetime):
    """Convert UTC datetime to GMT-5 timezone"""
    if utc_datetime is None:
        return None
    return utc_datetime - timedelta(hours=5)

# -------------------------------
# Routes
# -------------------------------

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/creat')
def index():
    return  redirect(url_for('auth_step_one'))

# Admin login page and route
@app.route('/admin')
def admin():
    # If already logged in as admin, redirect to dashboard
    if session.get('user_id') and session.get('admin'):
        return redirect(url_for('/'))

    # Otherwise show login page
    return render_template('adminlogin.html')

@app.route('/adminpage')
def adminpage():
    # Authentication check
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Special case for hardcoded admin users
    if user_id == -2 or user_id == -1:
        if session.get('admin'):
            # Hardcoded admin is authenticated
            profiles = Profile.query.all()
            return render_template('adminpage.html', profiles=profiles)

    # Regular database users
    user = db.session.get(Profile, user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))

    # Get all profiles for user management
    profiles = Profile.query.options(
        db.joinedload(Profile.user_roles)
        .joinedload(UserRole.role),
        db.joinedload(Profile.user_roles)
        .joinedload(UserRole.department)
    ).all()

    return render_template('adminpage.html', profiles=profiles)

@app.route('/a')
def ad():
    profiles = Profile.query.all()  # Retrieve all profiles from the database
    return render_template('adminpage.html', profiles=profiles)

@app.route('/profile')
def profileview():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    return render_template('profile.html', user=user)

# Update the admin login route
@app.route('/loginadmin', methods=['GET', 'POST'])
def loginadmin():
    if request.method == 'POST':
        first_name = request.form.get("first_name")
        pass_word = request.form.get("pass_word")

        # Hardcoded admin credentials for demo purposes
        if first_name == "admin" and pass_word == "admin123":
            session['admin'] = True
            session['user_id'] = -2  # Special ID for hardcoded admin
            return redirect(url_for('ap'))

        # Second hardcoded admin account
        elif first_name == "superadmin" and pass_word == "super123":
            session['admin'] = True
            session['user_id'] = -1  # Different special ID for the second hardcoded admin
            return redirect(url_for('ap'))

        # Database check
        user = Profile.query.filter_by(first_name=first_name).first()
        if user and user.check_password(pass_word) and user.privilages_ == "admin":
            session['admin'] = True
            session['user_id'] = user.id
            return redirect(url_for('ap'))
        else:
            return "Invalid username or password!"

    # GET request should redirect to admin login page
    return redirect(url_for('admin'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        if not email.endswith('@cougarnet.uh.edu'):
            flash('Only @cougarnet.uh.edu emails are allowed.', 'danger')
            return render_template('log.html')
        first_name = request.form.get("first_name")
        pass_word = request.form.get("pass_word")
        user = Profile.query.filter_by(first_name=first_name).first()
        if user and user.check_password(pass_word):
            if not user.active:
                return "Your profile is deactivated. Please contact the administrator."
            session['user_id'] = user.id
            return render_template('userhompage.html', user=user)
        else:
            return "Invalid username or password!"
    return render_template('log.html')

@app.route('/userhompage')
def userhompage():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    return render_template('userhompage.html', user=user)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    if request.method == 'POST':
        new_email = request.form.get("email")
        if new_email:
            user.email_ = new_email  # Update email field
            db.session.commit()
        return redirect(url_for('settings'))
    return render_template('settings.html', user=user)

@app.route('/reports')
def reports():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    return render_template('reports.html', user=user)

# Toggle the active status of a profile
@app.route('/active/<int:id>')
def activate(id):
    profile = Profile.query.get(id)
    if profile is None:
        return redirect('/ap')
    profile.active = not profile.active
    db.session.commit()
    return redirect(url_for('adminpage'))

@app.route('/ap')
def ap():
    # Authentication check
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Special case for hardcoded admin users
    if user_id == -2 or user_id == -1:
        if session.get('admin'):
            # Hardcoded admin is authenticated
            profiles = Profile.query.all()
            pending_medical_requests = MedicalWithdrawalRequest.query.filter_by(status='pending').all()
            pending_student_drops = StudentInitiatedDrop.query.filter_by(status='pending').all()
            pending_ferpa_requests = FERPARequest.query.filter_by(status='pending').all()
            pending_infochange_requests = InfoChangeRequest.query.filter_by(status='pending').all()
            now = datetime.utcnow()

            return render_template(
                'admin_dashboard.html',
                profiles=profiles,
                pending_medical_requests=pending_medical_requests,
                pending_student_drops=pending_student_drops,
                pending_ferpa_requests=pending_ferpa_requests,
                pending_infochange_requests=pending_infochange_requests,
                now=now
            )

    # Regular database users
    user = db.session.get(Profile, user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))

    # Get all profiles for the dashboard
    profiles = Profile.query.all()

    # Get pending requests for the dashboard
    pending_medical_requests = MedicalWithdrawalRequest.query.filter_by(status='pending').all()
    pending_student_drops = StudentInitiatedDrop.query.filter_by(status='pending').all()
    pending_ferpa_requests = FERPARequest.query.filter_by(status='pending').all()
    pending_infochange_requests = InfoChangeRequest.query.filter_by(status='pending').all()

    # Add current server time for the dashboard
    now = datetime.utcnow()

    return render_template(
        'admin_dashboard.html',
        profiles=profiles,
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops,
        pending_ferpa_requests=pending_ferpa_requests,
        pending_infochange_requests=pending_infochange_requests,
        now=now
    )

@app.route('/notifications')
def notifications():
    # Query pending and partially approved medical withdrawal requests
    pending_medical_requests = MedicalWithdrawalRequest.query.filter(
        MedicalWithdrawalRequest.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved student drop requests
    pending_student_drops = StudentInitiatedDrop.query.filter(
        StudentInitiatedDrop.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved FERPA requests
    pending_ferpa_requests = FERPARequest.query.filter(
        FERPARequest.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved Info Change requests
    pending_infochange_requests = InfoChangeRequest.query.filter(
        InfoChangeRequest.status.in_(['pending', 'pending_approval'])
    ).all()

    return render_template(
        'notifications.html',
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops,
        pending_ferpa_requests=pending_ferpa_requests,
        pending_infochange_requests=pending_infochange_requests
    )

# -------------------------------
# Microsoft OAuth Endpoints
# -------------------------------
def open1():
    with open('o365_token.txt', 'r') as token_file:
        token_data = json.load(token_file)
        account_data = token_data.get("Account")
        id_data = token_data.get("IdToken")
        for account in account_data.values():
            email = account.get("username")
            idtoken = account.get

        for account in id_data.values():
            idtoken = account.get("home_account_id")

        return email,idtoken

# Microsoft OAuth Step One
@app.route('/stepone')
def auth_step_one():
    # Create a callback URL for the next step, replacing '127.0.0.1' with 'localhost'
    callback = url_for('auth_step_two_callback', _external=True).replace("127.0.0.1", "localhost")
    account = Account(credentials)
    url, flow = account.con.get_authorization_url(requested_scopes=scopes, redirect_uri=callback)

    # Store flow for Step 2
    my_db.store_flow(serialize(flow))

    return redirect(url)

    account = Account(credentials)

    my_saved_flow_str = my_db.get_flow()

    if not my_saved_flow_str:
        return "Flow state not found. Restart authentication.", 400

    my_saved_flow = deserialize(my_saved_flow_str)
    requested_url = request.url  # Get current URL with auth code
    result = account.con.request_token(requested_url, flow=my_saved_flow)
    email, idtoken = open1()

    if result:
      
        return redirect('/')

    return "Authentication failed", 400
@app.route('/steptwo')
def auth_step_two_callback():
    account = Account(credentials)

    my_saved_flow_str = my_db.get_flow()

    if not my_saved_flow_str:
        return "Flow state not found. Restart authentication.", 400

    my_saved_flow = deserialize(my_saved_flow_str)
    requested_url = request.url  # Get current URL with auth code
    result = account.con.request_token(requested_url, flow=my_saved_flow)
    email, idtoken = open1()

    if result:
        # Check if the user already exists in the database
        user = Profile.query.filter_by(email_=email).first()

        if not user:
            # Ensure the email is a CougarNet account
            if not email.endswith('@cougarnet.uh.edu'):
                return "Account cannot be created. You need a CougarNet account.", 400

            # Check if this is the first account being created
            is_first_account = Profile.query.count() == 0

            # Create a new profile
            user = Profile(
                first_name=email,  # Use email as the username
                email_=email,
                pass_word=generate_password_hash(idtoken),  # Hash the idtoken for security
                privilages_="admin" if is_first_account else "user"  # Make the first account an admin
            )
            db.session.add(user)
            db.session.commit()

             # Role assignment logic
            if is_first_account:
                # Assign president role to first account
                president_role = Role.query.filter_by(name='president').first()
                if president_role:
                    db.session.add(UserRole(
                        user_id=user.id,
                        role_id=president_role.id
                    ))
            else:
                # Assign student role to subsequent accounts
                student_role = Role.query.filter_by(name='student').first()
                if student_role:
                    db.session.add(UserRole(
                        user_id=user.id,
                        role_id=student_role.id
                    ))
            db.session.commit()

        # Set session variables
        session['user_id'] = user.id
        session['admin'] = user.privilages_ == "admin"

        # Redirect based on privileges
        if user.privilages_ == "admin":
            return redirect(url_for('adminpage'))  # Admin page
        else:
            return redirect(url_for('userhompage'))  # User homepage
        

    return "Authentication failed", 400
# -------------------------------
# User and Admin Endpoints
# -------------------------------

# Add a new profile
@app.route('/add', methods=["POST"])
def add_profile():
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    phone_number = request.form.get("phoneN_")
    pass_word = request.form.get("pass_word")
    confirm_password = request.form.get("confirm_password")
    address = request.form.get("address")
    enroll_status = request.form.get("enroll_status")

    # Validation
    errors = []

    # Phone number validation
    import re
    phone_pattern = re.compile(r'^\d{3}-\d{3}-\d{4}$')
    if not phone_pattern.match(phone_number):
        errors.append("Invalid phone number format. Please use XXX-XXX-XXXX format.")

    # Address validation
    if not address or len(address.strip()) < 5:
        errors.append("Please provide a complete address (minimum 5 characters).")

    # Password confirmation
    if pass_word != confirm_password:
        errors.append("Passwords do not match.")

    if errors:
        # If there are validation errors, return to the form with error messages
        return render_template('add_profile.html', errors=errors)

    if first_name and pass_word:
        p = Profile(first_name=first_name, last_name=last_name, phoneN_=phone_number, address=address)
        p.set_password(pass_word)
        db.session.add(p)
        db.session.commit()
        return redirect('/stepone')
    else:
        return render_template('add_profile.html', errors=["First name and password are required"])

# Change privileges for a profile
@app.route('/priv/<int:id>')
def change_privileges(id):
    data = Profile.query.get(id)
    if data is None:
        return redirect('/login')
    if data.privilages_ == "user":
        data.privilages_ = "admin"
    else:
        data.privilages_ = "user"
    db.session.commit()
    return redirect(url_for('adminpage'))

# Delete a profile
@app.route('/delete/<int:id>')
def erase(id):
    data = Profile.query.get(id)
    if data:
        db.session.delete(data)
        db.session.commit()
    return redirect(url_for('adminpage'))

@app.route('/update/<int:id>', methods=['GET', 'POST'])
def update_user(id):
    user = Profile.query.get(id)
    if not user:
        return "User not found", 404

    if request.method == 'POST':
        # Update basic info
        user.first_name = request.form.get("first_name")
        user.last_name = request.form.get("last_name")
        user.email_ = request.form.get("email")
        user.phoneN_ = request.form.get("phoneN_")
        user.privilages_ = request.form.get("privileges")
        user.active = 'active' in request.form
        
        if request.form.get("pass_word"):
            user.set_password(request.form.get("pass_word"))

        # SIMPLIFIED ROLE UPDATE
        new_role = request.form.get("user_roles")  # Change from user_role to user_roles to match the form field
        
        # Clear existing roles
        UserRole.query.filter_by(user_id=id).delete()
        
        # Add new role if selected
        if new_role:
            role = Role.query.filter_by(name=new_role).first()
            if role:
                db.session.add(UserRole(user_id=user.id, role_id=role.id))
        
        db.session.commit()
        return redirect(url_for('adminpage'))  # Fix: Change from '/' to 'adminpage'

    # For GET request - show current role
    current_role = None
    if user.user_roles:  # Check if user has any roles
        current_role = user.user_roles[0].role.name if user.user_roles else 'student'
    return render_template('update.html', 
                         profile=user,
                         current_role=current_role)

@app.route("/create", methods=["GET", "POST"])
def create_profile():
    if request.method == "POST":
        password = request.form.get("pass_word")
        if not password:
            return "Password is required", 400
            
        # Create the new profile
        new_profile = Profile(
            first_name=request.form.get("first_name"),
            last_name=request.form.get("last_name"),
            email_=request.form.get("email"),
            privilages_=request.form.get("privileges"),
            active=request.form.get("active") == "on",
            pass_word=generate_password_hash(password)
        )
        
        # Add profile to the database to get an ID
        db.session.add(new_profile)
        db.session.flush()  # This assigns an ID to new_profile without committing
        
        # Assign role if specified in the form
        role_name = request.form.get("user_roles")
        if role_name:
            role = Role.query.filter_by(name=role_name).first()
            if role:
                user_role = UserRole(user_id=new_profile.id, role_id=role.id)
                db.session.add(user_role)
        
        # Commit all changes
        db.session.commit()
        return redirect('/ap')
        
    # For GET request - get all roles to display in the form
    roles = Role.query.all()
    return render_template("create.html", roles=roles)

# Optional: Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# -------------------------------
# Medical Withdrawal Form Routes
# -------------------------------

@app.route('/medical-withdrawal-form')
def medical_withdrawal_form():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    # Add today's date for the form
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('medical_withdrawal.html', user=user, today_date=today_date)

@app.route('/submit_medical_withdrawal', methods=['POST'])
def submit_medical_withdrawal():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    try:
        # Extract course data
        course_subjects = request.form.getlist('course_subject[]')
        course_numbers = request.form.getlist('course_number[]')
        course_sections = request.form.getlist('course_section[]')

        # Combine course data into JSON
        courses = []
        for i in range(len(course_subjects)):
            if i < len(course_numbers) and i < len(course_sections):
                courses.append({
                    'subject': course_subjects[i],
                    'number': course_numbers[i],
                    'section': course_sections[i]
                })

        # Handle file uploads
        documentation_files = []
        if 'documentation' in request.files:
            files = request.files.getlist('documentation')
            for file in files:
                if file and file.filename:
                    filename = secure_filename(f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'documentation')
                    os.makedirs(upload_dir, exist_ok=True)
                    file_path = os.path.join(upload_dir, filename)
                    file.save(file_path)
                    documentation_files.append(file_path)

        # Process signature based on chosen method
        signature_type = request.form.get('signature_type')
        signature = None

        if signature_type == 'draw':
            signature_data = request.form.get('signature_data')
            if signature_data:
                # Create signature directory
                signature_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'signatures')
                os.makedirs(signature_dir, exist_ok=True)

                # Generate filename
                signature_filename = f"sig_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.png"
                signature_path = os.path.join(signature_dir, signature_filename)

                # Save signature image by parsing data URL
                if signature_data.startswith('data:image'):
                    import base64
                    img_data = signature_data.split(',')[1]
                    with open(signature_path, "wb") as f:
                        f.write(base64.b64decode(img_data))
                    signature = signature_path

        elif signature_type == 'upload' and 'signature_upload' in request.files:
            sig_file = request.files['signature_upload']
            if sig_file and sig_file.filename:
                signature_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'signatures')
                os.makedirs(signature_dir, exist_ok=True)

                sig_filename = secure_filename(f"sig_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{sig_file.filename}")
                sig_path = os.path.join(signature_dir, sig_filename)
                sig_file.save(sig_path)
                signature = sig_path

        elif signature_type == 'text':
            # Just store the text as the signature
            signature = request.form.get('signature_text')

        # Create new medical withdrawal request
        new_request = MedicalWithdrawalRequest(
            user_id=user_id,
            last_name=request.form.get('last_name'),
            first_name=request.form.get('first_name'),
            middle_name=request.form.get('middle_name'),
            myuh_id=request.form.get('myuh_id'),
            college=request.form.get('college'),
            plan_degree=request.form.get('plan_degree'),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            zip_code=request.form.get('zip'),
            phone=request.form.get('phone'),
            term_year=request.form.get('term_year'),
            last_date=datetime.strptime(request.form.get('last_date'), '%Y-%m-%d'),
            reason_type=request.form.get('reason'),
            details=request.form.get('details'),
            financial_assistance=(request.form.get('financial_assistance') == 'yes'),
            health_insurance=(request.form.get('health_insurance') == 'yes'),
            campus_housing=(request.form.get('campus_housing') == 'yes'),
            visa_status=(request.form.get('visa') == 'yes'),
            gi_bill=(request.form.get('gi_bill') == 'yes'),
            courses=json.dumps(courses),
            initial=request.form.get('initial'),
            signature=signature,  # This can now be None or a path or text
            signature_date=datetime.strptime(request.form.get('signature_date'), '%Y-%m-%d'),
            documentation_files=json.dumps(documentation_files) if documentation_files else None,
            status='pending' if request.form.get('action') == 'submit' else 'draft'
        )

        db.session.add(new_request)
        db.session.commit()

        # Generate PDF if the form is being submitted (not saved as draft)
        if request.form.get('action') == 'submit':
            # Import the PDF generation function
            from pdf_utils import generate_medical_withdrawal_pdf

            # Generate the PDF
            pdf_path = generate_medical_withdrawal_pdf(new_request)

            # Store the PDF path in the database
            if pdf_path:
                new_request.generated_pdfs = json.dumps([pdf_path])
                db.session.commit()

            return redirect(url_for('status'))
        else:
            return redirect(url_for('drafts'))

    except Exception as e:
        print(f"Error processing medical withdrawal: {str(e)}")
        db.session.rollback()
        return "An error occurred while processing your request. Please try again.", 500

@app.route('/view-medical-request/<int:request_id>')
def view_medical_request(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    request_record = MedicalWithdrawalRequest.query.get(request_id)

    if not request_record:
        return "Request not found", 404

    # Check if user is admin or owner of the request
    is_admin = user.privilages_ == 'admin'
    if not is_admin and request_record.user_id != user_id:
        return "Unauthorized", 403

    return render_template('view_medical_request.html',
                          request=request_record,
                          is_admin=is_admin,
                          courses=json.loads(request_record.courses))

@app.route('/approve_medical_withdrawal/<int:request_id>', methods=['POST'])
def approve_medical_withdrawal(request_id):
    """Approve a medical withdrawal request and generate a PDF"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Get current user with roles loaded
    user = Profile.query.options(joinedload(Profile.user_roles)).get(user_id)
    
    # Check if user is either admin or department chair
    if not (user.is_admin or user.is_department_chair):  # Using the property we defined earlier
        return "Unauthorized", 403

    req_record = MedicalWithdrawalRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Check if user has viewed the PDF
    #if not req_record.has_admin_viewed(user_id):
        #return "You must view the request PDF before approving", 400
        
    # Check if this user has already approved
    if req_record.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))

    # Add user to approvals list
    if not req_record.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(req_record.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    req_record.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals
    if len(admin_approvals) >= 2:
        req_record.status = 'approved'
        
        # Get comments from form
        comments = request.form.get('comments', '')

        # Create history record
        history_entry = WithdrawalHistory(
            withdrawal_id=request_id,
            admin_id=user_id,
            action='approved',
            comments=comments,
            
        )
        db.session.add(history_entry)
        
        # Generate PDF with LaTeX
        from pdf_utils import generate_medical_withdrawal_pdf
        pdf_path = generate_medical_withdrawal_pdf(req_record)

        # Store the PDF path
        if pdf_path:
            if not req_record.generated_pdfs:
                req_record.generated_pdfs = json.dumps([pdf_path])
            else:
                pdfs = json.loads(req_record.generated_pdfs)
                pdfs.append(pdf_path)
                req_record.generated_pdfs = json.dumps(pdfs)
                
        flash('Medical withdrawal request has been fully approved.', 'success')
    else:
        req_record.status = 'pending_approval'
        role = 'Department Chair' if user.is_department_chair else 'Admin'
        flash(f'{role} approval recorded. Awaiting second approval.', 'success')
    
    db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/reject_medical_withdrawal/<int:request_id>', methods=['POST'])
def reject_medical_withdrawal(request_id):
    """Reject a medical withdrawal request and generate a PDF"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = MedicalWithdrawalRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Check if admin has viewed the PDF
    if not req_record.has_admin_viewed(user_id):
        return "You must view the request PDF before rejecting", 400

    # Get comments from form
    comments = request.form.get('comments', '')

    # Create history record
    history_entry = WithdrawalHistory(
        withdrawal_id=request_id,
        admin_id=user_id,
        action='rejected',
        comments=comments
    )
    db.session.add(history_entry)

    # Change status to rejected
    req_record.status = 'rejected'
    db.session.commit()

    # Generate PDF with LaTeX
    from pdf_utils import generate_medical_withdrawal_pdf
    pdf_path = generate_medical_withdrawal_pdf(req_record)

    # Store the PDF path
    if pdf_path:
        # If this is the first generated PDF
        if not req_record.generated_pdfs:
            req_record.generated_pdfs = json.dumps([pdf_path])
        else:
            # Otherwise append to existing list
            pdfs = json.loads(req_record.generated_pdfs)
            pdfs.append(pdf_path)
            req_record.generated_pdfs = json.dumps(pdfs)

        db.session.commit()

    return redirect(url_for('notifications'))

@app.route('/simple_approve_withdrawal/<int:request_id>', methods=['POST'])
def simple_approve_withdrawal(request_id):
    """Basic approval endpoint that just records the approval"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    req_record = MedicalWithdrawalRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404
    
    # Check if this request already has an approval
    if req_record.admin_approvals:
        existing_approvals = json.loads(req_record.admin_approvals)
        if existing_approvals:  # If there's at least one approval already
            flash('This request already has an approval and needs to be reviewed by someone else.', 'warning')
            return redirect(url_for('chair_student_drops'))

    # Check if this user has already approved
    if req_record.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('chair_student_drops'))

    # Add user to approvals list
    if not req_record.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(req_record.admin_approvals)
        admin_approvals.append(str(user_id))
    
    req_record.admin_approvals = json.dumps(admin_approvals)
    req_record.status = 'approved'  # Immediately approve with single approval

    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        req_record.status = 'approved'
        flash('Request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        req_record.status = 'pending_approval'
        flash('Request has been partially approved. Awaiting second approval.', 'success')
    
    # Create simple history record
    history_entry = WithdrawalHistory(
        withdrawal_id=request_id,
        admin_id=user_id,
        action='approved',
        comments='Approved via simple approval',
        
    )
    db.session.add(history_entry)
    
    db.session.commit()
    flash('Request approved successfully.', 'success')
    return redirect(url_for('chair_student_drops'))  # Or wherever you want to redirect

@app.route('/simple_reject_medical_withdrawal/<int:request_id>', methods=['POST'])
def simple_reject_medical_withdrawal(request_id):
    """Reject a medical withdrawal request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    req_record = MedicalWithdrawalRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Get comments from form
    comments = request.form.get('comments', '')

    # Create history record
    history_entry = WithdrawalHistory(
        withdrawal_id=request_id,
        admin_id=user_id,
        action='rejected',
        comments=comments
    )
    db.session.add(history_entry)

    # Change status to rejected
    req_record.status = 'rejected'
    db.session.commit()

    return redirect(url_for('chair_student_drops'))

@app.route('/download_pdf/<int:request_id>/<string:status>')
def download_pdf(request_id, status):
    """Download a generated PDF for a medical withdrawal request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    request_record = MedicalWithdrawalRequest.query.get(request_id)

    if not request_record:
        return "Request not found", 404

    # Check if user is admin or owner of the request
    is_admin = user.privilages_ == 'admin'
    if not is_admin and request_record.user_id != user_id:
        return "Unauthorized", 403

    # If admin is viewing, mark as viewed
    if is_admin:
        if not request_record.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(request_record.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        request_record.admin_viewed = json.dumps(admin_viewed)
        db.session.commit()

    # Rest of existing code remains the same
    # Find the most recent PDF with the given status
    pdf_dir = os.path.join('static', 'pdfs')
    search_pattern = f"medical_withdrawal_{request_id}_{status}_"

    matching_files = []
    if os.path.exists(pdf_dir):
        for filename in os.listdir(pdf_dir):
            if filename.startswith(search_pattern) and filename.endswith('.pdf'):
                matching_files.append(os.path.join(pdf_dir, filename))

    if matching_files:
        # Sort by creation time, newest first
        latest_pdf = max(matching_files, key=os.path.getctime)
        return send_file(latest_pdf, as_attachment=True)
    elif request_record.generated_pdfs:
        # Check if we have stored paths in the database
        pdfs = json.loads(request_record.generated_pdfs)
        # Find PDFs containing the status in their path
        status_pdfs = [pdf for pdf in pdfs if status in pdf]
        if status_pdfs:
            return send_file(status_pdfs[-1], as_attachment=True)

    # If no PDF found, generate one on the fly
    from pdf_utils import generate_medical_withdrawal_pdf
    pdf_path = generate_medical_withdrawal_pdf(request_record)
    if pdf_path and os.path.exists(pdf_path):
        return send_file(pdf_path, as_attachment=True)

    return "PDF file not found", 404

@app.route('/download_documentation/<int:request_id>/<int:file_index>')
def download_documentation(request_id, file_index):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    request_record = MedicalWithdrawalRequest.query.get(request_id)

    if not request_record:
        return "Request not found", 404

    # Check if user is admin or owner of the request
    is_admin = user.privilages_ == 'admin'
    if not is_admin and request_record.user_id != user_id:
        return "Unauthorized", 403

    # Get documentation files
    if not request_record.documentation_files:
        return "No documentation files found", 404

    files = json.loads(request_record.documentation_files)
    if file_index >= len(files):
        return "File not found", 404

    file_path = files[file_index]

    # Fix file path - ensure it has the correct path structure
    if not os.path.exists(file_path):
        # Try prefixing with static if the path starts with uploads
        if (file_path.startswith('uploads/')):
            fixed_path = os.path.join('static', file_path)
            if os.path.exists(fixed_path):
                file_path = fixed_path
        # Try other common path variations
        elif not file_path.startswith('static/'):
            fixed_path = os.path.join('static', 'uploads', os.path.basename(file_path))
            if os.path.exists(fixed_path):
                file_path = fixed_path

    # Final check if file exists
    if not os.path.exists(file_path):
        return "File not found at path: " + file_path, 404

    return send_file(file_path, as_attachment=True)

@app.route('/submit_student_drop', methods=['POST'])
def submit_student_drop():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))  # Redirect to login if the user is not logged in

    # Get form data
    student_name = request.form.get('studentName')
    student_id = str(user_id)  # Use the session user_id instead of form input
    course_title = request.form.get('course')
    reason = request.form.get('reason')
    date_str = request.form.get('date')  # Get the date as a string
    signature_type = request.form.get('signature_type')

    # Validate form data
    if not all([student_name, course_title, reason, date_str, signature_type]):
        return "All fields are required", 400

    # Convert the date string to a Python date object
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date format. Please use YYYY-MM-DD.", 400

    # Handle signature based on the selected type
    signature = ""
    if signature_type == 'draw':
        signature_data = request.form.get('signature_data')
        if not signature_data:
            return "Signature is required for the selected option", 400
        signature = signature_data
    elif signature_type == 'upload':
        signature_upload = request.files.get('signature_upload')
        if not signature_upload:
            return "Signature file is required for the selected option", 400
        # Save the uploaded file
        filename = secure_filename(f"sig_{user_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{signature_upload.filename}")
        signature_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'signatures')
        os.makedirs(signature_dir, exist_ok=True)
        filepath = os.path.join(signature_dir, filename)
        signature_upload.save(filepath)
        signature = filepath
    elif signature_type == 'text':
        signature_text = request.form.get('signature_text')
        if not signature_text:
            return "Typed signature is required for the selected option", 400
        signature = signature_text

    # Save the drop request to the database
    drop_request = StudentInitiatedDrop(
        student_name=student_name,
        student_id=student_id,
        course_title=course_title,
        reason=reason,
        date=date,  # Use the converted Python date object
        signature=signature,
        status='pending'
    )
    db.session.add(drop_request)
    db.session.commit()

    return redirect(url_for('status'))  # Redirect to the status page

# Now let's add a route for viewing form history for all users
@app.route('/form_history')
def form_history():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Get current user (admin viewing the history)
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))

    # Combine all types of form submissions
    history_entries = []

    # Process Medical Withdrawal Requests
    medical_requests = MedicalWithdrawalRequest.query.filter(
        MedicalWithdrawalRequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in medical_requests:
        # Get the most recent history entry for this request
        history = WithdrawalHistory.query.filter_by(
            withdrawal_id=req.id
        ).order_by(
            WithdrawalHistory.action_date.desc()
        ).first()

        # Safely construct the reviewer name to handle None values
        reviewer = 'System'
        if history and history.admin:
            first_name = history.admin.first_name or ''
            last_name = history.admin.last_name or ''
            if first_name or last_name:
                reviewer = f"{first_name} {last_name}".strip()

        history_entries.append({
            'timestamp': req.updated_at or req.created_at,
            'form_type': 'Medical Withdrawal',
            'status': req.status,
            'reviewed_by': reviewer,
            'original_request': req  # Keep reference if needed
        })

    # Process Student Drop Requests
    student_drops = StudentInitiatedDrop.query.filter(
        StudentInitiatedDrop.status.in_(['approved', 'rejected'])
    ).all()

    for drop in student_drops:
        history_entries.append({
            'timestamp': drop.created_at,  # Using created_at since we don't have updated_at
            'form_type': 'Student Course Drop',
            'status': drop.status,
            'reviewed_by': 'System',  # Modify if you track approvers for drops
            'original_request': drop  # Keep reference if needed
        })

    # Process FERPA Requests
    ferpa_requests = FERPARequest.query.filter(
        FERPARequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in ferpa_requests:
        history_entries.append({
            'timestamp': req.time,  # Using time field as timestamp
            'form_type': 'FERPA Release',
            'status': req.status,
            'reviewed_by': 'Admin',  # Could be enhanced if you track which admin made the approval/rejection
            'original_request': req
        })

    # Process Name/SSN Change Requests
    infochange_requests = InfoChangeRequest.query.filter(
        InfoChangeRequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in infochange_requests:
        request_type = "Name Change" if "name" in req.choice else "SSN Change"
        if "name" in req.choice and "ssn" in req.choice:
            request_type = "Name & SSN Change"

        history_entries.append({
            'timestamp': req.time,  # Using time field as timestamp
            'form_type': request_type,
            'status': req.status,
            'reviewed_by': 'Admin'  # Could be enhanced if you track which admin made the approval/rejection
        })

    # Sort all entries by timestamp (newest first)
    history_entries.sort(key=lambda x: x['timestamp'], reverse=True)

    # Get current time in GMT-5
    now = utc_to_gmt5(datetime.utcnow())

    return render_template(
        'history.html',
        user=user,
        history=history_entries,
        now=now
    )

# Add a route for viewing form history for a specific user
@app.route('/history/<int:user_id>')
def user_form_history(user_id):
    # Authentication and authorization checks
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_user = Profile.query.get(session['user_id'])
    if not current_user or current_user.privilages_ != 'admin':
        return "Unauthorized", 403

    # Get the user whose history we're viewing
    user = Profile.query.get_or_404(user_id)

    # Get form history data
    history_entries = []

    # Medical Withdrawals
    medical_requests = MedicalWithdrawalRequest.query.filter(
        MedicalWithdrawalRequest.user_id == user_id,
        MedicalWithdrawalRequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in medical_requests:
        history = WithdrawalHistory.query.filter_by(
            withdrawal_id=req.id
        ).order_by(
            WithdrawalHistory.action_date.desc()
        ).first()

        history_entries.append({
            'timestamp': req.updated_at or req.created_at,
            'form_type': 'Medical Withdrawal',
            'status': req.status,
            'reviewed_by': f"{history.admin.first_name} {history.admin.last_name}" if history else 'System'
        })

    # Student Drops (assuming student_id is string)
    student_drops = StudentInitiatedDrop.query.filter(
        StudentInitiatedDrop.student_id == str(user_id),
        StudentInitiatedDrop.status.in_(['approved', 'rejected'])
    ).all()

    for drop in student_drops:
        history_entries.append({
            'timestamp': drop.created_at,
            'form_type': 'Student Course Drop',
            'status': drop.status,
            'reviewed_by': 'System'
        })

    # FERPA Requests
    ferpa_requests = FERPARequest.query.filter(
        FERPARequest.user_id == user_id,
        FERPARequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in ferpa_requests:
        history_entries.append({
            'timestamp': req.time,
            'form_type': 'FERPA Release',
            'status': req.status,
            'reviewed_by': 'Admin'
        })

    # Name/SSN Change Requests
    infochange_requests = InfoChangeRequest.query.filter(
        InfoChangeRequest.user_id == user_id,
        InfoChangeRequest.status.in_(['approved', 'rejected'])
    ).all()

    for req in infochange_requests:
        request_type = "Name Change" if "name" in req.choice else "SSN Change"
        if "name" in req.choice and "ssn" in req.choice:
            request_type = "Name & SSN Change"

        history_entries.append({
            'timestamp': req.time,
            'form_type': request_type,
            'status': req.status,
            'reviewed_by': 'Admin'
        })

    # Sort by timestamp (newest first)
    history_entries.sort(key=lambda x: x['timestamp'], reverse=True)

    # Get current time in GMT-5
    now = utc_to_gmt5(datetime.utcnow())

    return render_template(
        'user_form_history.html',  # Use the new template for individual user history
        user=user,
        history=history_entries,
        now=now
    )


@app.route('/admin/student_drops')
def admin_student_drops():
    drop_requests = StudentInitiatedDrop.query.all()
    return render_template('admin_student_drops.html', drop_requests=drop_requests)

@app.route('/chair_student_drops')
def chair_student_drops():
    # Query pending and partially approved medical withdrawal requests
    pending_medical_requests = MedicalWithdrawalRequest.query.filter(
        MedicalWithdrawalRequest.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved student drop requests
    pending_student_drops = StudentInitiatedDrop.query.filter(
        StudentInitiatedDrop.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved FERPA requests
    pending_ferpa_requests = FERPARequest.query.filter(
        FERPARequest.status.in_(['pending', 'pending_approval'])
    ).all()

    # Query pending and partially approved Info Change requests
    pending_infochange_requests = InfoChangeRequest.query.filter(
        InfoChangeRequest.status.in_(['pending', 'pending_approval'])
    ).all()

    return render_template(
        'chair_student_drops.html',
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops,
        pending_ferpa_requests=pending_ferpa_requests,
        pending_infochange_requests=pending_infochange_requests
    )
@app.route('/mark_student_drop_viewed/<int:request_id>', methods=['POST'])
def mark_student_drop_viewed(request_id):
    """Mark a student drop request as viewed by the current admin"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = StudentInitiatedDrop.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Add admin to the viewed list if not already there
    if not req_record.admin_viewed:
        admin_viewed = [str(user_id)]
    else:
        admin_viewed = json.loads(req_record.admin_viewed)
        if str(user_id) not in admin_viewed:
            admin_viewed.append(str(user_id))

    req_record.admin_viewed = json.dumps(admin_viewed)
    db.session.commit()

    return {"success": True}

@app.route('/approve_student_drop/<int:request_id>', methods=['POST'])
def approve_student_drop(request_id):
    """Approve a student-initiated drop request and generate a PDF"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = StudentInitiatedDrop.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Check if admin has viewed the PDF
    if not req_record.has_admin_viewed(user_id):
        return "You must view the request PDF before approving", 400
    
    # Check if this admin has already approved
    if req_record.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))
    
    # Add admin to approvals list
    if not req_record.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(req_record.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    req_record.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        req_record.status = 'approved'
        
        # Generate PDF with the updated function
        from pdf_utils import generate_student_drop_pdf
        pdf_path = generate_student_drop_pdf(req_record)

        # Store the PDF path in the request record
        if pdf_path:
            # If this is the first generated PDF
            if not req_record.generated_pdfs:
                req_record.generated_pdfs = json.dumps([pdf_path])
            else:
                # Otherwise append to existing list
                pdfs = json.loads(req_record.generated_pdfs)
                pdfs.append(pdf_path)
                req_record.generated_pdfs = json.dumps(pdfs)
                
        flash('Student drop request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        req_record.status = 'pending_approval'
        flash('Student drop request has been partially approved. Awaiting second approval.', 'success')

    db.session.commit()
    return redirect(url_for('notifications'))

@app.route('/simple_approve_student_drop/<int:request_id>', methods=['POST'])
def simple_approve_student_drop(request_id):
    """Approve a student-initiated drop request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    req_record = StudentInitiatedDrop.query.get_or_404(request_id)
    
    # Add user to approvals list
    if not req_record.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(req_record.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    req_record.admin_approvals = json.dumps(admin_approvals)
    
    # Check if we now have 2 approvals, if so mark as fully approved
    if len(admin_approvals) >= 2:
        req_record.status = 'approved'
        flash('Student drop request has been fully approved.', 'success')
    else:
        # Mark as partially approved
        req_record.status = 'pending_approval'
        flash('Student drop request has been partially approved. Awaiting second approval.', 'success')

    db.session.commit()
    return redirect(url_for('chair_student_drops'))

@app.route('/reject_student_drop/<int:request_id>', methods=['POST'])
def reject_student_drop(request_id):
    """Reject a student-initiated drop request and generate a PDF"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = StudentInitiatedDrop.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Check if admin has viewed the PDF
    if not req_record.has_admin_viewed(user_id):
        return "You must view the request PDF before rejecting", 400

    # Change status to rejected
    req_record.status = 'rejected'
    db.session.commit()

    # Generate PDF with the updated function
    from pdf_utils import generate_student_drop_pdf
    pdf_path = generate_student_drop_pdf(req_record)

    # Store the PDF path in the request record
    if pdf_path:
        # If this is the first generated PDF
        if not req_record.generated_pdfs:
            req_record.generated_pdfs = json.dumps([pdf_path])
        else:
            # Otherwise append to existing list
            pdfs = json.loads(req_record.generated_pdfs)
            pdfs.append(pdf_path)
            req_record.generated_pdfs = json.dumps(pdfs)

        db.session.commit()

    return redirect(url_for('notifications'))

@app.route('/simple_reject_student_drop/<int:request_id>', methods=['POST'])
def simple_reject_student_drop(request_id):
    """Reject a student-initiated drop request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    req_record = StudentInitiatedDrop.query.get_or_404(request_id)

    # Change status to rejected
    req_record.status = 'rejected'
    db.session.commit()

    return redirect(url_for('chair_student_drops'))

@app.route('/view-student-drop/<int:request_id>')
def view_student_drop(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    request_record = StudentInitiatedDrop.query.get(request_id)

    if not request_record:
        return "Request not found", 404

    # Check if user is admin or owner of the request
    is_admin = user.privilages_ == 'admin'
    if not is_admin and request_record.student_id != str(user_id):
        return "Unauthorized", 403

    return render_template('view_student_drop.html',
                          request=request_record,
                          is_admin=is_admin)


@app.route('/download_student_drop_pdf/<int:request_id>/<string:status>')
def download_student_drop_pdf(request_id, status):
    """Download a generated PDF for a student drop request"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    request_record = StudentInitiatedDrop.query.get(request_id)

    if not request_record:
        return "Request not found", 404

    # Check if user is admin or owner of the request
    is_admin = user.privilages_ == 'admin'
    if not is_admin and request_record.student_id != str(user_id):
        return "Unauthorized", 403

    # If admin is viewing, mark as viewed
    if is_admin:
        if not request_record.admin_viewed:
            admin_viewed = [str(user_id)]
        else:
            admin_viewed = json.loads(request_record.admin_viewed)
            if str(user_id) not in admin_viewed:
                admin_viewed.append(str(user_id))
        request_record.admin_viewed = json.dumps(admin_viewed)
        db.session.commit()

    # Find the most recent PDF with the given status
    pdf_dir = os.path.join('static', 'pdfs')
    search_pattern = f"student_drop_{request_id}_{status}_"

    matching_files = []
    if os.path.exists(pdf_dir):
        for filename in os.listdir(pdf_dir):
            if filename.startswith(search_pattern) and filename.endswith('.pdf'):
                matching_files.append(os.path.join(pdf_dir, filename))

    if matching_files:
        # Sort by creation time, newest first
        latest_pdf = max(matching_files, key(os.path.getctime))
        return send_file(latest_pdf, as_attachment=True)
    elif request_record.generated_pdfs:
        # Check if we have stored paths in the database
        pdfs = json.loads(request_record.generated_pdfs)
        # Find PDFs containing the status in their path
        status_pdfs = [pdf for pdf in pdfs if status in pdf]
        if status_pdfs:
            return send_file(status_pdfs[-1], as_attachment=True)

    # If no PDF found, generate one on the fly
    from pdf_utils import generate_student_drop_pdf
    pdf_path = generate_student_drop_pdf(request_record)
    if pdf_path and os.path.exists(pdf_path):
        return send_file(pdf_path, as_attachment=True)

    return "PDF file not found", 404

@app.route('/student_initiated_drop')
def student_initiated_drop():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    # Add today's date for the form
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('student_initiated_drop.html', user=user, today_date=today_date)


@app.route('/drafts')
def drafts():
    """View draft medical withdrawal requests"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    draft_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id, status='draft').all()
    return render_template('drafts.html', draft_requests=draft_requests)

# Helper functions for multi-level approval workflows
def get_workflow_for_form(form_type, org_unit_id=None, department_id=None):
    """
    Find the appropriate workflow for a form based on org unit and department
    Prioritizes more specific workflows (department-level over org-level over global)
    """
    # Try to find a department-specific workflow first
    if department_id:
        workflow = ApprovalWorkflow.query.filter_by(
            form_type=form_type,
            department_id=department_id,
            active=True
        ).first()
        if workflow:
            return workflow
    
    # Then try org unit specific workflow
    if org_unit_id:
        workflow = ApprovalWorkflow.query.filter_by(
            form_type=form_type,
            org_unit_id=org_unit_id,
            active=True
        ).first()
        if workflow:
            return workflow
    
    # Finally, try a global workflow (no org_unit or department specified)
    workflow = ApprovalWorkflow.query.filter_by(
        form_type=form_type,
        org_unit_id=None,
        department_id=None,
        active=True
    ).first()
    
    return workflow

def get_current_approval_step(form_type, form_id):
    """Get the current approval step for a form"""
    # Get all approvals for this form, ordered by step order
    approvals = FormApproval.query.join(ApprovalStep).filter(
        FormApproval.form_type == form_type,
        FormApproval.form_id == form_id
    ).order_by(ApprovalStep.order.desc()).all()
    
    if not approvals:
        return None
    
    # Check if the last step was completed (all required approvals)
    last_step = approvals[0].step
    step_approvals = [a for a in approvals if a.step_id == last_step.id]
    
    if len(step_approvals) >= last_step.min_approvers:
        # Last step was completed, get the next step in the workflow
        next_step = ApprovalStep.query.filter(
            ApprovalStep.workflow_id == last_step.workflow_id,
            ApprovalStep.order > last_step.order,
            ApprovalStep.active == True
        ).order_by(ApprovalStep.order).first()
        return next_step
    else:
        # Still waiting for approvals on the current step
        return last_step

def get_eligible_approvers(step):
    """Get all users eligible to approve a step"""
    if not step:
        return []
    
    query = Profile.query.join(UserRole)
    
    # Filter by role if specified
    if step.approver_role_id:
        query = query.filter(UserRole.role_id == step.approver_role_id)
    
    # Filter by department if specified
    if step.department_id:
        query = query.filter(UserRole.department_id == step.department_id)
    
    # Filter by active users
    query = query.filter(Profile.active == True)
    
    # Get all eligible approvers
    eligible_approvers = query.all()
    
    # Also include users with active delegations from eligible approvers
    now = datetime.utcnow()
    for approver in list(eligible_approvers):
        delegations = ApprovalDelegation.query.filter(
            ApprovalDelegation.delegator_id == approver.id,
            ApprovalDelegation.active == True,
            ApprovalDelegation.start_date <= now,
            ApprovalDelegation.end_date >= now
        ).all()
        
        for delegation in delegations:
            if delegation.delegate not in eligible_approvers:
                eligible_approvers.append(delegation.delegate)
    
    return eligible_approvers

def can_user_approve(user_id, step_id, form_type, form_id):
    """Check if a user can approve a specific step"""
    step = ApprovalStep.query.get(step_id)
    if not step:
        return False
    
    # Get eligible approvers for this step
    eligible_approvers = get_eligible_approvers(step)
    user = Profile.query.get(user_id)
    
    if user not in eligible_approvers:
        return False
    
    # Check if this user has already approved this step
    existing_approval = FormApproval.query.filter_by(
        form_type=form_type,
        form_id=form_id,
        step_id=step_id,
        approver_id=user_id
    ).first()
    
    return existing_approval is None

def get_delegated_by(delegate_id, step):
    """Check if approval is being made as a delegate, return delegator if so"""
    if not step:
        return None
    
    # Find active delegations to this user
    now = datetime.utcnow()
    delegations = ApprovalDelegation.query.filter(
        ApprovalDelegation.delegate_id == delegate_id,
        ApprovalDelegation.active == True,
        ApprovalDelegation.start_date <= now,
        ApprovalDelegation.end_date >= now
    ).all()
    
    for delegation in delegations:
        # Check if the delegator is eligible to approve this step
        delegator = Profile.query.get(delegation.delegator_id)
        eligible_approvers = get_eligible_approvers(step)
        
        if delegator in eligible_approvers:
            return delegator.id
    
    return None

def get_form_status(form_type, form_id):
    """Get detailed status information about a form's approval progress"""
    # Get the workflow for this form
    workflow = None
    form = None
    
    # Determine which form table to query
    if form_type == 'medical_withdrawal':
        form = MedicalWithdrawalRequest.query.get(form_id)
        if form:
            dept = Department.query.filter_by(name=form.college).first()
            dept_id = dept.id if dept else None
            workflow = get_workflow_for_form(form_type, department_id=dept_id)
    elif form_type == 'student_drop':
        form = StudentInitiatedDrop.query.get(form_id)
        workflow = get_workflow_for_form(form_type)
    elif form_type == 'ferpa':
        form = FERPARequest.query.get(form_id)
        workflow = get_workflow_for_form(form_type)
    elif form_type == 'infochange':
        form = InfoChangeRequest.query.get(form_id)
        workflow = get_workflow_for_form(form_type)
    
    if not form or not workflow:
        return None
    
    # Get all approvals for this form
    approvals = FormApproval.query.filter_by(
        form_type=form_type,
        form_id=form_id
    ).all()
    
    # Get all steps in the workflow
    steps = ApprovalStep.query.filter_by(
        workflow_id=workflow.id
    ).order_by(ApprovalStep.order).all()
    
    # Build status for each step
    step_statuses = []
    all_steps_approved = True
    current_step = None
    
    for step in steps:
        step_approvals = [a for a in approvals if a.step_id == step.id]
        is_complete = len(step_approvals) >= step.min_approvers
        
        if not is_complete and all_steps_approved:
            all_steps_approved = False
            current_step = step
        
        approvers = []
        for approval in step_approvals:
            approver = Profile.query.get(approval.approver_id)
            delegated_by = None
            if approval.delegated_by_id:
                delegated_by = Profile.query.get(approval.delegated_by_id)
            
            approvers.append({
                'name': f"{approver.first_name} {approver.last_name}",
                'id': approver.id,
                'date': approval.created_at,
                'delegated_by': delegated_by.first_name + ' ' + delegated_by.last_name if delegated_by else None
            })
        
        step_statuses.append({
            'id': step.id,
            'name': step.name,
            'order': step.order,
            'min_approvers': step.min_approvers,
            'current_approvers': len(step_approvals),
            'is_complete': is_complete,
            'approvers': approvers
        })
    
    return {
        'workflow': workflow,
        'steps': step_statuses,
        'current_step': current_step,
        'is_fully_approved': all_steps_approved,
        'form': form
    }

def start_approval_workflow(form_type, form_id):
    """Initialize the approval workflow for a form"""
    # Determine form details to get appropriate workflow
    form = None
    dept_id = None
    
    if form_type == 'medical_withdrawal':
        form = MedicalWithdrawalRequest.query.get(form_id)
        if form:
            dept = Department.query.filter_by(name=form.college).first()
            dept_id = dept.id if dept else None
    elif form_type == 'student_drop':
        form = StudentInitiatedDrop.query.get(form_id)
    elif form_type == 'ferpa':
        form = FERPARequest.query.get(form_id)
    elif form_type == 'infochange':
        form = InfoChangeRequest.query.get(form_id)
    
    if not form:
        return False
    
    # Get the appropriate workflow
    workflow = get_workflow_for_form(form_type, department_id=dept_id)
    if not workflow:
        # No workflow defined - use legacy behavior
        return False
    
    # Get the first step in the workflow
    first_step = ApprovalStep.query.filter_by(
        workflow_id=workflow.id,
        active=True
    ).order_by(ApprovalStep.order).first()
    
    if not first_step:
        return False
    
    # Mark the form as being in the workflow
    if form_type == 'medical_withdrawal':
        form.status = 'in_workflow'
    elif form_type == 'student_drop':
        form.status = 'in_workflow'
    elif form_type == 'ferpa':
        form.status = 'in_workflow'
    elif form_type == 'infochange':
        form.status = 'in_workflow'
    
    db.session.commit()
    
    return True

def process_approval(user_id, form_type, form_id, step_id, action, comments=None):
    """Process an approval or rejection action"""
    step = ApprovalStep.query.get(step_id)
    if not step:
        return False, "Invalid step"
    
    # Check if user can approve this step
    if not can_user_approve(user_id, step_id, form_type, form_id):
        return False, "Not authorized to approve this step"
    
    # Check if this is a delegated approval
    delegated_by_id = get_delegated_by(user_id, step)
    
    # Create the approval record
    approval = FormApproval(
        form_type=form_type,
        form_id=form_id,
        step_id=step_id,
        approver_id=user_id,
        delegated_by_id=delegated_by_id,
        status=action,
        comments=comments,
        created_at=datetime.utcnow()
    )
    
    db.session.add(approval)
    
    # Get the form status after this approval
    form_status = get_form_status(form_type, form_id)
    
    # Update the form status if needed
    if action == 'rejected':
        if form_type == 'medical_withdrawal':
            form = MedicalWithdrawalRequest.query.get(form_id)
            form.status = 'rejected'
        elif form_type == 'student_drop':
            form = StudentInitiatedDrop.query.get(form_id)
            form.status = 'rejected'
        elif form_type == 'ferpa':
            form = FERPARequest.query.get(form_id)
            form.status = 'rejected'
        elif form_type == 'infochange':
            form = InfoChangeRequest.query.get(form_id)
            form.status = 'rejected'
    elif form_status and form_status['is_fully_approved']:
        if form_type == 'medical_withdrawal':
            form = MedicalWithdrawalRequest.query.get(form_id)
            form.status = 'approved'
        elif form_type == 'student_drop':
            form = StudentInitiatedDrop.query.get(form_id)
            form.status = 'approved'
        elif form_type == 'ferpa':
            form = FERPARequest.query.get(form_id)
            form.status = 'approved'
        elif form_type == 'infochange':
            form = InfoChangeRequest.query.get(form_id)
            form.status = 'approved'
    
    db.session.commit()
    
    return True, "Approval processed successfully"

def initialize_roles_and_departments():
    """Safe initialization that won't duplicate existing data"""
    with app.app_context():
        # Create default roles if they don't exist
        default_roles = [
            {'name': 'student', 'level': 1},
            {'name': 'department_chair', 'level': 2},
            {'name': 'president', 'level': 3}
        ]
        
        for role_data in default_roles:
            if not Role.query.filter_by(name=role_data['name']).first():
                db.session.add(Role(**role_data))
        
        # Create sample departments
        sample_departments = ['Computer Science', 'Mathematics', 'Biology']
        for dept_name in sample_departments:
            if not Department.query.filter_by(name=dept_name).first():
                db.session.add(Department(
                    name=dept_name,
                    code=dept_name[:3].upper()
                ))
        
        db.session.commit()

# Organization and Workflow Management Routes

@app.route('/admin/org_units')
def admin_org_units():
    """View and manage organizational units"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    # Get all organizational units with their hierarchy
    org_units = OrganizationalUnit.query.filter_by(parent_id=None).all()
    
    return render_template(
        'admin/org_units.html',
        org_units=org_units
    )

@app.route('/admin/org_units/add', methods=['GET', 'POST'])
def add_org_unit():
    """Add a new organizational unit"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        description = request.form.get('description')
        parent_id = request.form.get('parent_id')
        
        if parent_id:
            parent = OrganizationalUnit.query.get(parent_id)
            level = parent.level + 1 if parent else 1
        else:
            level = 1
        
        new_unit = OrganizationalUnit(
            name=name,
            code=code,
            description=description,
            parent_id=parent_id if parent_id else None,
            level=level
        )
        
        db.session.add(new_unit)
        db.session.commit()
        
        flash('Organizational unit added successfully.', 'success')
        return redirect(url_for('admin_org_units'))
    
    # Get all existing org units for the parent dropdown
    org_units = OrganizationalUnit.query.all()
    return render_template(
        'admin/add_org_unit.html',
        org_units=org_units
    )

@app.route('/admin/org_units/edit/<int:unit_id>', methods=['GET', 'POST'])
def edit_org_unit(unit_id):
    """Edit an organizational unit"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    unit = OrganizationalUnit.query.get_or_404(unit_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        description = request.form.get('description')
        parent_id = request.form.get('parent_id')
        active = 'active' in request.form
        
        if parent_id and int(parent_id) != unit_id:  # Don't allow self as parent
            parent = OrganizationalUnit.query.get(parent_id)
            level = parent.level + 1 if parent else 1
            
            # Check if this would create a circular reference
            current_parent = parent
            while current_parent:
                if current_parent.id == unit_id:
                    flash('Cannot set a unit as parent that would create a circular reference.', 'danger')
                    return redirect(url_for('edit_org_unit', unit_id=unit_id))
                current_parent = current_parent.parent
                
            unit.parent_id = parent_id
            unit.level = level
        elif not parent_id:
            unit.parent_id = None
            unit.level = 1
        
        unit.name = name
        unit.code = code
        unit.description = description
        unit.active = active
        
        db.session.commit()
        
        flash('Organizational unit updated successfully.', 'success')
        return redirect(url_for('admin_org_units'))
    
    # Get all existing org units for the parent dropdown, excluding this unit and its children
    org_units = OrganizationalUnit.query.filter(OrganizationalUnit.id != unit_id).all()
    
    # Filter out any children of this unit to prevent circular references
    def get_child_ids(parent_unit):
        child_ids = [child.id for child in parent_unit.children]
        for child in parent_unit.children:
            child_ids.extend(get_child_ids(child))
        return child_ids
    
    child_ids = get_child_ids(unit)
    valid_parents = [u for u in org_units if u.id not in child_ids]
    
    return render_template(
        'admin/edit_org_unit.html',
        unit=unit,
        org_units=valid_parents
    )

@app.route('/admin/departments')
def admin_departments():
    """View and manage departments"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    # Get all departments with their organizational units
    departments = Department.query.options(db.joinedload(Department.organizational_unit)).all()
    
    return render_template(
        'admin/departments.html',
        departments=departments
    )

@app.route('/admin/departments/add', methods=['GET', 'POST'])
def add_department():
    """Add a new department"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        org_unit_id = request.form.get('org_unit_id')
        
        new_dept = Department(
            name=name,
            code=code,
            org_unit_id=org_unit_id if org_unit_id else None
        )
        
        db.session.add(new_dept)
        db.session.commit()
        
        flash('Department added successfully.', 'success')
        return redirect(url_for('admin_departments'))
    
    # Get all org units for dropdown
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    return render_template(
        'admin/add_department.html',
        org_units=org_units
    )

@app.route('/admin/departments/edit/<int:dept_id>', methods=['GET', 'POST'])
def edit_department(dept_id):
    """Edit a department"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    dept = Department.query.get_or_404(dept_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code')
        org_unit_id = request.form.get('org_unit_id')
        active = 'active' in request.form
        
        dept.name = name
        dept.code = code
        dept.org_unit_id = org_unit_id if org_unit_id else None
        dept.active = active
        
        db.session.commit()
        
        flash('Department updated successfully.', 'success')
        return redirect(url_for('admin_departments'))
    
    # Get all org units for dropdown
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    return render_template(
        'admin/edit_department.html',
        dept=dept,
        org_units=org_units
    )

@app.route('/admin/workflows')
def admin_workflows():
    """View and manage approval workflows"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    # Get all workflows with their related entities
    workflows = ApprovalWorkflow.query.options(
        db.joinedload(ApprovalWorkflow.org_unit),
        db.joinedload(ApprovalWorkflow.department),
        db.joinedload(ApprovalWorkflow.steps).joinedload(ApprovalStep.approver_role)
    ).all()
    
    return render_template(
        'admin/workflows.html',
        workflows=workflows
    )

@app.route('/admin/workflows/add', methods=['GET', 'POST'])
def add_workflow():
    """Add a new approval workflow"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        form_type = request.form.get('form_type')
        org_unit_id = request.form.get('org_unit_id')
        department_id = request.form.get('department_id')
        
        new_workflow = ApprovalWorkflow(
            name=name,
            description=description,
            form_type=form_type,
            org_unit_id=org_unit_id if org_unit_id else None,
            department_id=department_id if department_id else None
        )
        
        db.session.add(new_workflow)
        db.session.commit()
        
        flash('Workflow added successfully. Now add steps to this workflow.', 'success')
        return redirect(url_for('edit_workflow', workflow_id=new_workflow.id))
    
    # Get all org units and departments for dropdowns
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    departments = Department.query.filter_by(active=True).all()
    form_types = [
        ('medical_withdrawal', 'Medical Withdrawal'),
        ('student_drop', 'Student Drop'),
        ('ferpa', 'FERPA Release'),
        ('infochange', 'Name/SSN Change')
    ]
    
    return render_template(
        'admin/add_workflow.html',
        org_units=org_units,
        departments=departments,
        form_types=form_types
    )

@app.route('/admin/workflows/edit/<int:workflow_id>', methods=['GET', 'POST'])
def edit_workflow(workflow_id):
    """Edit an approval workflow and its steps"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    workflow = ApprovalWorkflow.query.options(
        db.joinedload(ApprovalWorkflow.steps).joinedload(ApprovalStep.approver_role)
    ).get_or_404(workflow_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        form_type = request.form.get('form_type')
        org_unit_id = request.form.get('org_unit_id')
        department_id = request.form.get('department_id')
        active = 'active' in request.form
        
        workflow.name = name
        workflow.description = description
        workflow.form_type = form_type
        workflow.org_unit_id = org_unit_id if org_unit_id else None
        workflow.department_id = department_id if department_id else None
        workflow.active = active
        
        db.session.commit()
        
        flash('Workflow updated successfully.', 'success')
        return redirect(url_for('admin_workflows'))
    
    # Get all org units and departments for dropdowns
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    departments = Department.query.filter_by(active=True).all()
    form_types = [
        ('medical_withdrawal', 'Medical Withdrawal'),
        ('student_drop', 'Student Drop'),
        ('ferpa', 'FERPA Release'),
        ('infochange', 'Name/SSN Change')
    ]
    
    return render_template(
        'admin/edit_workflow.html',
        workflow=workflow,
        org_units=org_units,
        departments=departments,
        form_types=form_types
    )

@app.route('/admin/workflows/<int:workflow_id>/add_step', methods=['GET', 'POST'])
def add_workflow_step(workflow_id):
    """Add a step to an approval workflow"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    workflow = ApprovalWorkflow.query.get_or_404(workflow_id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        order = request.form.get('order', type=int)
        approver_role_id = request.form.get('approver_role_id')
        org_unit_id = request.form.get('org_unit_id')
        department_id = request.form.get('department_id')
        min_approvers = request.form.get('min_approvers', type=int, default=1)
        
        # Check if the order is already in use
        existing_step = ApprovalStep.query.filter_by(
            workflow_id=workflow_id,
            order=order
        ).first()
        
        if existing_step:
            # Shift steps with the same or higher order
            steps_to_shift = ApprovalStep.query.filter(
                ApprovalStep.workflow_id == workflow_id,
                ApprovalStep.order >= order
            ).all()
            
            for step in steps_to_shift:
                step.order += 1
        
        new_step = ApprovalStep(
            workflow_id=workflow_id,
            name=name,
            description=description,
            order=order,
            approver_role_id=approver_role_id if approver_role_id else None,
            org_unit_id=org_unit_id if org_unit_id else None,
            department_id=department_id if department_id else None,
            min_approvers=min_approvers
        )
        
        db.session.add(new_step)
        db.session.commit()
        
        flash('Workflow step added successfully.', 'success')
        return redirect(url_for('edit_workflow', workflow_id=workflow_id))
    
    # Get all roles, org units, and departments for dropdowns
    roles = Role.query.all()
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    departments = Department.query.filter_by(active=True).all()
    
    # Determine the next available order number
    next_order = 1
    highest_step = ApprovalStep.query.filter_by(workflow_id=workflow_id).order_by(ApprovalStep.order.desc()).first()
    if highest_step:
        next_order = highest_step.order + 1
    
    return render_template(
        'admin/add_workflow_step.html',
        workflow=workflow,
        roles=roles,
        org_units=org_units,
        departments=departments,
        next_order=next_order
    )

@app.route('/admin/workflows/steps/<int:step_id>/edit', methods=['GET', 'POST'])
def edit_workflow_step(step_id):
    """Edit a workflow step"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    step = ApprovalStep.query.get_or_404(step_id)
    workflow = step.workflow
    
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        new_order = request.form.get('order', type=int)
        approver_role_id = request.form.get('approver_role_id')
        org_unit_id = request.form.get('org_unit_id')
        department_id = request.form.get('department_id')
        min_approvers = request.form.get('min_approvers', type=int, default=1)
        active = 'active' in request.form
        
        # If order changed, handle reordering
        if new_order != step.order:
            if new_order < step.order:
                # Moving up: bump steps in the way down
                steps_to_shift = ApprovalStep.query.filter(
                    ApprovalStep.workflow_id == workflow.id,
                    ApprovalStep.order >= new_order,
                    ApprovalStep.order < step.order
                ).all()
                
                for s in steps_to_shift:
                    s.order += 1
            else:
                # Moving down: bump steps in the way up
                steps_to_shift = ApprovalStep.query.filter(
                    ApprovalStep.workflow_id == workflow.id,
                    ApprovalStep.order <= new_order,
                    ApprovalStep.order > step.order
                ).all()
                
                for s in steps_to_shift:
                    s.order -= 1
            
            step.order = new_order
        
        step.name = name
        step.description = description
        step.approver_role_id = approver_role_id if approver_role_id else None
        step.org_unit_id = org_unit_id if org_unit_id else None
        step.department_id = department_id if department_id else None
        step.min_approvers = min_approvers
        step.active = active
        
        db.session.commit()
        
        flash('Workflow step updated successfully.', 'success')
        return redirect(url_for('edit_workflow', workflow_id=workflow.id))
    
    # Get all roles, org units, and departments for dropdowns
    roles = Role.query.all()
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    departments = Department.query.filter_by(active=True).all()
    
    return render_template(
        'admin/edit_workflow_step.html',
        step=step,
        workflow=workflow,
        roles=roles,
        org_units=org_units,
        departments=departments
    )

@app.route('/admin/workflows/steps/<int:step_id>/delete', methods=['POST'])
def delete_workflow_step(step_id):
    """Delete a workflow step"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    step = ApprovalStep.query.get_or_404(step_id)
    workflow_id = step.workflow_id
    
    # Get steps that need to be re-ordered
    steps_to_shift = ApprovalStep.query.filter(
        ApprovalStep.workflow_id == workflow_id,
        ApprovalStep.order > step.order
    ).all()
    
    # Delete the step
    db.session.delete(step)
    
    # Re-order the remaining steps
    for s in steps_to_shift:
        s.order -= 1
    
    db.session.commit()
    
    flash('Workflow step deleted successfully.', 'success')
    return redirect(url_for('edit_workflow', workflow_id=workflow_id))

# Delegation Routes

@app.route('/admin/delegations')
def admin_delegations():
    """View all approval delegations"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user:
        return redirect(url_for('login'))
    
    is_admin = user.privilages_ == 'admin'
    
    # If admin, show all delegations
    if is_admin:
        delegations = ApprovalDelegation.query.options(
            db.joinedload(ApprovalDelegation.delegator),
            db.joinedload(ApprovalDelegation.delegate),
            db.joinedload(ApprovalDelegation.role),
            db.joinedload(ApprovalDelegation.department),
            db.joinedload(ApprovalDelegation.org_unit)
        ).order_by(ApprovalDelegation.created_at.desc()).all()
    else:
        # Show only delegations where the user is the delegator or delegate
        delegations = ApprovalDelegation.query.options(
            db.joinedload(ApprovalDelegation.delegator),
            db.joinedload(ApprovalDelegation.delegate),
            db.joinedload(ApprovalDelegation.role),
            db.joinedload(ApprovalDelegation.department),
            db.joinedload(ApprovalDelegation.org_unit)
        ).filter(
            db.or_(
                ApprovalDelegation.delegator_id == user_id,
                ApprovalDelegation.delegate_id == user_id
            )
        ).order_by(ApprovalDelegation.created_at.desc()).all()
    
    now = datetime.utcnow()
    
    return render_template(
        'admin/delegations.html',
        delegations=delegations,
        now=now,
        is_admin=is_admin
    )

@app.route('/admin/delegations/add', methods=['GET', 'POST'])
def add_delegation():
    """Add a new approval delegation"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    is_admin = user and user.privilages_ == 'admin'
    
    if request.method == 'POST':
        delegator_id = request.form.get('delegator_id')
        delegate_id = request.form.get('delegate_id')
        role_id = request.form.get('role_id')
        department_id = request.form.get('department_id')
        org_unit_id = request.form.get('org_unit_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        reason = request.form.get('reason')
        
        # Security check - only admins can delegate for others
        if not is_admin and int(delegator_id) != user_id:
            flash('You can only create delegations for yourself.', 'danger')
            return redirect(url_for('admin_delegations'))
        
        # Parse dates
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Set time to end of day for end_date
            end_date = end_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
            return redirect(url_for('add_delegation'))
        
        if start_date > end_date:
            flash('Start date must be before end date.', 'danger')
            return redirect(url_for('add_delegation'))
        
        # Ensure we're not delegating to the same person
        if int(delegator_id) == int(delegate_id):
            flash('You cannot delegate to yourself.', 'danger')
            return redirect(url_for('add_delegation'))
        
        # Create the delegation
        delegation = ApprovalDelegation(
            delegator_id=delegator_id,
            delegate_id=delegate_id,
            role_id=role_id if role_id else None,
            department_id=department_id if department_id else None,
            org_unit_id=org_unit_id if org_unit_id else None,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            active=True,
            created_at=datetime.utcnow()
        )
        
        db.session.add(delegation)
        db.session.commit()
        
        flash('Delegation created successfully.', 'success')
        return redirect(url_for('admin_delegations'))
    
    # Get data for dropdowns
    profiles = Profile.query.filter_by(active=True).all()
    roles = Role.query.all()
    departments = Department.query.filter_by(active=True).all()
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    
    # Default to current user as delegator if not admin
    default_delegator_id = user_id if not is_admin else None
    
    return render_template(
        'admin/add_delegation.html',
        profiles=profiles,
        roles=roles,
        departments=departments,
        org_units=org_units,
        default_delegator_id=default_delegator_id,
        is_admin=is_admin,
        today=datetime.now().strftime('%Y-%m-%d')
    )

@app.route('/admin/delegations/edit/<int:delegation_id>', methods=['GET', 'POST'])
def edit_delegation(delegation_id):
    """Edit an approval delegation"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    is_admin = user and user.privilages_ == 'admin'
    
    delegation = ApprovalDelegation.query.get_or_404(delegation_id)
    
    # Security check - only admin or the delegator can edit
    if not is_admin and delegation.delegator_id != user_id:
        flash('You can only edit your own delegations.', 'danger')
        return redirect(url_for('admin_delegations'))
    
    if request.method == 'POST':
        delegate_id = request.form.get('delegate_id')
        role_id = request.form.get('role_id')
        department_id = request.form.get('department_id')
        org_unit_id = request.form.get('org_unit_id')
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')
        reason = request.form.get('reason')
        active = 'active' in request.form
        
        # Parse dates
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Set time to end of day for end_date
            end_date = end_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
            return redirect(url_for('edit_delegation', delegation_id=delegation_id))
        
        if start_date > end_date:
            flash('Start date must be before end date.', 'danger')
            return redirect(url_for('edit_delegation', delegation_id=delegation_id))
        
        # Ensure we're not delegating to the same person
        if delegation.delegator_id == int(delegate_id):
            flash('You cannot delegate to yourself.', 'danger')
            return redirect(url_for('edit_delegation', delegation_id=delegation_id))
        
        # Update the delegation
        delegation.delegate_id = delegate_id
        delegation.role_id = role_id if role_id else None
        delegation.department_id = department_id if department_id else None
        delegation.org_unit_id = org_unit_id if org_unit_id else None
        delegation.start_date = start_date
        delegation.end_date = end_date
        delegation.reason = reason
        delegation.active = active
        
        db.session.commit()
        
        flash('Delegation updated successfully.', 'success')
        return redirect(url_for('admin_delegations'))
    
    # Get data for dropdowns
    profiles = Profile.query.filter_by(active=True).all()  # Fixed: active(True) → active=True
    roles = Role.query.all()
    departments = Department.query.filter_by(active=True).all()  # Fixed: active(True) → active=True
    org_units = OrganizationalUnit.query.filter_by(active=True).all()  # Fixed: active(True) → active=True
    
    # Format dates for the form
    start_date = delegation.start_date.strftime('%Y-%m-%d')
    end_date = delegation.end_date.strftime('%Y-%m-%d')
    
    return render_template(
        'admin/edit_delegation.html',
        delegation=delegation,
        profiles=profiles,
        roles=roles,
        departments=departments,
        org_units=org_units,
        start_date=start_date,
        end_date=end_date,
        is_admin=is_admin
    )

@app.route('/admin/delegations/toggle/<int:delegation_id>', methods=['POST'])
def toggle_delegation(delegation_id):
    """Enable or disable a delegation"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    is_admin = user and user.privilages_ == 'admin'
    
    delegation = ApprovalDelegation.query.get_or_404(delegation_id)
    
    # Security check - only admin or the delegator can toggle
    if not is_admin and delegation.delegator_id != user_id:
        flash('You can only modify your own delegations.', 'danger')
        return redirect(url_for('admin_delegations'))
    
    delegation.active = not delegation.active
    db.session.commit()
    
    status = 'enabled' if delegation.active else 'disabled'
    flash(f'Delegation {status} successfully.', 'success')
    
    return redirect(url_for('admin_delegations'))

# Enhanced workflow-based approval routes

@app.route('/approve_form/<string:form_type>/<int:form_id>', methods=['GET', 'POST'])
def approve_form(form_type, form_id):
    """Universal route for approving forms in the new workflow system"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    
    # Get form status information
    form_status = get_form_status(form_type, form_id)
    if not form_status:
        flash('Unable to find workflow information for this form.', 'danger')
        return redirect(url_for('notifications'))
    
    current_step = form_status['current_step']
    if not current_step:
        flash('This form has already completed all approval steps.', 'info')
        return redirect(url_for('notifications'))
    
    # Check if user can approve this step
    if not can_user_approve(user_id, current_step.id, form_type, form_id):
        flash('You are not authorized to approve this form at the current step.', 'danger')
        return redirect(url_for('notifications'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        comments = request.form.get('comments')
        
        if action not in ['approved', 'rejected']:
            flash('Invalid action specified.', 'danger')
            return redirect(url_for('approve_form', form_type=form_type, form_id=form_id))
        
        success, message = process_approval(user_id, form_type, form_id, current_step.id, action, comments)
        
        if success:
            flash(f'Form {action} successfully.', 'success')
        else:
            flash(f'Error processing approval: {message}', 'danger')
        
        return redirect(url_for('notifications'))
    
    # Determine what form record to get based on type
    form = None
    if form_type == 'medical_withdrawal':
        form = MedicalWithdrawalRequest.query.get(form_id)
    elif form_type == 'student_drop':
        form = StudentInitiatedDrop.query.get(form_id)
    elif form_type == 'ferpa':
        form = FERPARequest.query.get(form_id)
    elif form_type == 'infochange':
        form = InfoChangeRequest.query.get(form_id)
    
    if not form:
        flash('Form not found.', 'danger')
        return redirect(url_for('notifications'))
    
    # Check if this is a delegated approval
    delegated_by_id = get_delegated_by(user_id, current_step)
    delegated_by = None
    if delegated_by_id:
        delegated_by = Profile.query.get(delegated_by_id)
    
    # Get delegation history for this user and this form type
    delegations = []
    if delegated_by:
        delegations.append({
            'delegator': delegated_by,
            'delegate': user,
            'active': True
        })
    
    return render_template(
        'admin/approve_form.html',
        form=form,
        form_type=form_type,
        form_id=form_id,
        workflow=form_status['workflow'],
        current_step=current_step,
        steps=form_status['steps'],
        delegated_by=delegated_by,
        delegations=delegations,
        user=user
    )

@app.route('/form_status/<string:form_type>/<int:form_id>')
def view_form_status(form_type, form_id):
    """View detailed approval status for a form"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    is_admin = user and user.privilages_ == 'admin'
    
    # Determine what form record to get based on type
    form = None
    can_view = False
    
    if form_type == 'medical_withdrawal':
        form = MedicalWithdrawalRequest.query.get(form_id)
        can_view = is_admin or (form and form.user_id == user_id)
    elif form_type == 'student_drop':
        form = StudentInitiatedDrop.query.get(form_id)
        can_view = is_admin or (form and form.student_id == str(user_id))
    elif form_type == 'ferpa':
        form = FERPARequest.query.get(form_id)
        can_view = is_admin or (form and form.user_id == user_id)
    elif form_type == 'infochange':
        form = InfoChangeRequest.query.get(form_id)
        can_view = is_admin or (form and form.user_id == user_id)
    
    if not form:
        flash('Form not found.', 'danger')
        return redirect(url_for('status'))
    
    if not can_view:
        flash('You do not have permission to view this form.', 'danger')
        return redirect(url_for('status'))
    
    # Get workflow status information
    form_status = get_form_status(form_type, form_id)
    
    # If no workflow is defined, show basic status
    if not form_status:
        return render_template(
            'form_status_basic.html',
            form=form,
            form_type=form_type,
            is_admin=is_admin
        )
    
    return render_template(
        'form_status.html',
        form=form,
        form_type=form_type,
        form_id=form_id,
        workflow=form_status['workflow'],
        current_step=form_status['current_step'],
        steps=form_status['steps'],
        is_admin=is_admin
    )

# Initialize new tables
def initialize_organization_structure():
    """Create initial organizational structure if not exists"""
    with app.app_context():
        # Check if we already have organizational units
        if OrganizationalUnit.query.count() > 0:
            return
        
        # Create top-level university unit
        university = OrganizationalUnit(
            name="University of Houston",
            code="UH",
            description="Main university campus",
            level=1
        )
        db.session.add(university)
        db.session.flush()  # Get ID without committing
        
        # Create colleges as second-level units
        colleges = [
            {"name": "College of Natural Sciences and Mathematics", "code": "NSM"},
            {"name": "College of Engineering", "code": "ENG"},
            {"name": "College of Liberal Arts and Social Sciences", "code": "CLASS"},
            {"name": "C. T. Bauer College of Business", "code": "BAUER"}
        ]
        
        for college_data in colleges:
            college = OrganizationalUnit(
                name=college_data["name"],
                code=college_data["code"],
                description=f"{college_data['name']} at University of Houston",
                parent_id=university.id,
                level=2
            )
            db.session.add(college)
        
        db.session.commit()
        
        # Link existing departments to organizational units
        # Example: Computer Science to NSM
        nsm = OrganizationalUnit.query.filter_by(code="NSM").first()
        if nsm:
            cs_dept = Department.query.filter_by(name="Computer Science").first()
            if cs_dept:
                cs_dept.org_unit_id = nsm.id
            
            math_dept = Department.query.filter_by(name="Mathematics").first()
            if math_dept:
                math_dept.org_unit_id = nsm.id
        
        # Example: Biology to NSM
        biology_dept = Department.query.filter_by(name="Biology").first()
        if biology_dept and nsm:
            biology_dept.org_unit_id = nsm.id
        
        db.session.commit()
        
        # Create default workflows
        # 1. Global medical withdrawal workflow (applies to all departments)
        med_withdrawal_workflow = ApprovalWorkflow(
            name="Medical Withdrawal Approval",
            description="Standard approval process for medical withdrawals",
            form_type="medical_withdrawal",
            active=True
        )
        db.session.add(med_withdrawal_workflow)
        db.session.flush()
        
        # Add steps to medical withdrawal workflow
        steps = [
            {
                "order": 1,
                "name": "Department Chair Review",
                "description": "Initial review by the department chair",
                "approver_role_id": Role.query.filter_by(name="department_chair").first().id,
                "min_approvers": 1
            },
            {
                "order": 2,
                "name": "President Review",
                "description": "Final approval by university president",
                "approver_role_id": Role.query.filter_by(name="president").first().id,
                "min_approvers": 1
            }
        ]
        
        for step_data in steps:
            step = ApprovalStep(
                workflow_id=med_withdrawal_workflow.id,
                order=step_data["order"],
                name=step_data["name"],
                description=step_data["description"],
                approver_role_id=step_data["approver_role_id"],
                min_approvers=step_data["min_approvers"],
                active=True
            )
            db.session.add(step)
        
        db.session.commit()

@app.route('/admin/org_chart')
def admin_org_chart():
    """Display a visual organizational chart"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    # Get all organizational units with their hierarchy
    root_units = OrganizationalUnit.query.filter_by(parent_id=None).all()
    
    return render_template(
        'admin/org_chart.html',
        root_units=root_units
    )

@app.route('/admin/approval_analytics')
def approval_analytics():
    """Display approval analytics dashboard"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    
    # Get date range from request, default to last 30 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=30)
    
    date_range = request.args.get('range', '30d')
    if date_range == '90d':
        start_date = end_date - timedelta(days=90)
    elif date_range == '180d':
        start_date = end_date - timedelta(days(180))
    elif date_range == '1y':
        start_date = end_date - timedelta(days(365))
    
    # Get department and org unit filters
    department_id = request.args.get('department_id')
    org_unit_id = request.args.get('org_unit_id')
    
    # Base query for approvals
    approval_query = FormApproval.query.filter(FormApproval.created_at.between(start_date, end_date))
    
    # Apply filters if provided
    if department_id:
        # This would need joining with forms and their departments - simplified here
        pass
    if org_unit_id:
        # This would need joining with forms and their org units - simplified here
        pass
    
    # Get all approvals in the period
    approvals = approval_query.all()
    
    # Calculate statistics
    total_approvals = len(approvals)
    approved_count = sum(1 for a in approvals if a.status == 'approved')
    rejected_count = sum(1 for a in approvals if a.status == 'rejected')
    
    approval_rate = (approved_count / total_approvals * 100) if total_approvals > 0 else 0
    
    # Get approval times (time between form submission and approval)
    # This would require additional queries to get form submission times
    avg_approval_time = "2.3 days"  # Placeholder for actual calculation
    
    # Get most active approvers
    approver_counts = {}
    for approval in approvals:
        approver_id = approval.approver_id
        approver_counts[approver_id] = approver_counts.get(approver_id, 0) + 1
    
    top_approvers = []
    for approver_id, count in sorted(approver_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        approver = Profile.query.get(approver_id)
        if approver:
            top_approvers.append({
                'name': f"{approver.first_name} {approver.last_name}",
                'count': count
            })
    
    # Get approval counts by form type
    form_type_counts = {}
    for approval in approvals:
        form_type = approval.form_type
        form_type_counts[form_type] = form_type_counts.get(form_type, 0) + 1
    
    # Get delegation statistics
    delegated_approvals = [a for a in approvals if a.delegated_by_id is not None]
    delegation_percent = (len(delegated_approvals) / total_approvals * 100) if total_approvals > 0 else 0
    
    # Get departments and org units for filter dropdowns
    departments = Department.query.filter_by(active=True).all()
    org_units = OrganizationalUnit.query.filter_by(active=True).all()
    
    return render_template(
        'admin/approval_analytics.html',
        total_approvals=total_approvals,
        approved_count=approved_count,
        rejected_count=rejected_count,
        approval_rate=approval_rate,
        avg_approval_time=avg_approval_time,
        top_approvers=top_approvers,
        form_type_counts=form_type_counts,
        delegation_percent=delegation_percent,
        date_range=date_range,
        departments=departments,
        org_units=org_units,
        selected_department_id=department_id,
        selected_org_unit_id=org_unit_id
    )

@app.route('/admin/delegations/history')
def delegation_history():
    """View history of approval delegations"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    # Update from Query.get() to db.session.get()
    user = db.session.get(Profile, user_id)
    if not user:
        return redirect(url_for('login'))
    
    is_admin = user.privilages_ == 'admin'
    
    # Query delegations with joined data
    query = ApprovalDelegation.query.options(
        db.joinedload(ApprovalDelegation.delegator),
        db.joinedload(ApprovalDelegation.delegate),
        db.joinedload(ApprovalDelegation.role),
        db.joinedload(ApprovalDelegation.department),
        db.joinedload(ApprovalDelegation.org_unit)
    )
    
    # Filter by user if not admin
    if not is_admin:
        query = query.filter(
            db.or_(
                ApprovalDelegation.delegator_id == user_id,
                ApprovalDelegation.delegate_id == user_id
            )
        )
    
    delegations = query.order_by(ApprovalDelegation.created_at.desc()).all()
    
    now = datetime.utcnow()
    
    return render_template(
        'admin/delegation_history.html',
        delegations=delegations,
        now=now,
        is_admin=is_admin
    )

@app.route('/admin/org_hierarchy_report')
def admin_org_hierarchy_report():
    """Display a report of the organizational hierarchy"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))
    org_units = OrganizationalUnit.query.all()
    return render_template('admin/org_hierarchy_report.html', org_units=org_units)

# Update the initialization in the main block
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        initialize_roles_and_departments()
        initialize_organization_structure()  # Add the new initialization
    app.run(debug=True)



