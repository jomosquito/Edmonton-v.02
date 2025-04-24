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
import os
from operator import itemgetter

def utc_to_gmt5(dt):
    """Convert UTC datetime to GMT-5"""
    return dt - timedelta(hours=5)

from config import client_id, client_secret, SECRET_KEY
from form_utils import allowed_file, return_choice, generate_ferpa, generate_ssn_name
from sqlalchemy.orm import joinedload
import json
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

    @property
    def is_department_chair(self):
        return any(role.role.name == "department_chair" for role in self.user_roles)

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

class WorkflowConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    form_type = db.Column(db.String(50), unique=True, nullable=False)
    required_approvers = db.Column(db.Integer, default=2)
    required_roles = db.Column(db.Text, default='[]')  # JSON array of role names in order
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod 
    def get_required_approvers(form_type):
        config = WorkflowConfig.query.filter_by(form_type=form_type).first()
        return config.required_approvers if config else 2

    @staticmethod
    def get_required_roles(form_type):
        config = WorkflowConfig.query.filter_by(form_type=form_type).first()
        if config and config.required_roles:
            return json.loads(config.required_roles)
        return []

    def is_approval_valid(self, approver_roles):
        """Check if a set of approver roles satisfies the requirements"""
        required = set(json.loads(self.required_roles))
        provided = set(approver_roles)
        return len(required.intersection(provided)) == len(required)

class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    chairs = db.relationship('UserRole', back_populates='department')

class UserRole(db.Model):
    __tablename__ = 'user_roles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'))
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'))
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    role = db.relationship('Role', back_populates='user_roles')
    department = db.relationship('Department')
    user = db.relationship('Profile', back_populates='user_roles')

def _process_approval(request, user_id, form_type):
    """Process an approval for any form type using workflow configuration"""
    if not request.has_admin_viewed(user_id):
        return False, 'You must view the request PDF before approving'
    
    if request.has_admin_approved(user_id):
        return False, 'You have already approved this request'

    # Add admin to approvals list
    if not request.admin_approvals:
        admin_approvals = [str(user_id)]
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
                pdf_file = generate_ssn_name(data, forms_dir, os.path.join('static', 'uploads', 'signatures'))
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

    return render_template(
        'status.html',
        medical_requests=medical_requests,
        student_drop_requests=student_drop_requests,
        ferpa_requests=ferpa_requests,
        infochange_requests=infochange_requests,
        config=WorkflowConfig  # Pass WorkflowConfig class to template
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

    user = Profile.query.get(user_id)
    if not user:
        return "User not found", 404

    # 1) load workflow for FERPA
    workflow = WorkflowConfig.query.filter_by(form_type='ferpa').first()
    if not workflow:
        flash('No workflow configured for FERPA requests.', 'danger')
        return redirect(url_for('notifications'))

    # 2) role check
    user_roles = [ur.role.name for ur in user.user_roles]
    if not any(r in json.loads(workflow.required_roles) for r in user_roles):
        flash('You lack the role to approve FERPA requests.', 'danger')
        return redirect(url_for('notifications'))

    # 3) fetch and process approval
    req = FERPARequest.query.get_or_404(request_id)
    success, message = _process_approval(req, user_id, 'ferpa')
    flash(message, 'success' if success else 'danger')

    db.session.commit()
    return redirect(url_for('notifications'))

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

@app.route('/approve_infochange/<int:request_id>', methods=['POST'])
def approve_infochange(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user:
        return "User not found", 404

    # 1) load workflow for InfoChange
    workflow = WorkflowConfig.query.filter_by(form_type='info_change').first()
    if not workflow:
        flash('No workflow configured for Name/SSN change requests.', 'danger')
        return redirect(url_for('notifications'))

    # 2) role check
    user_roles = [ur.role.name for ur in user.user_roles]
    if not any(r in json.loads(workflow.required_roles) for r in user_roles):
        flash('You lack the role to approve Name/SSN change requests.', 'danger')
        return redirect(url_for('notifications'))

    # 3) fetch and process approval
    req = InfoChangeRequest.query.get_or_404(request_id)
    success, message = _process_approval(req, user_id, 'info_change')
    flash(message, 'success' if success else 'danger')

    db.session.commit()
    return redirect(url_for('notifications'))

    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        flash('You do not have permission to approve requests.', 'danger')
        return redirect(url_for('notifications'))

    req = InfoChangeRequest.query.get_or_404(request_id)
    success, message = _process_approval(req, user_id, 'info_change')
    flash(message, 'success' if success else 'danger')

    # Commit changes
    db.session.commit()
    return redirect(url_for('notifications'))

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

@app.route('/workflow_settings', methods=['GET', 'POST'])
def workflow_settings():
    """Admin page to configure workflow settings like number of required approvers and their roles"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    # Check if user is admin
    user = Profile.query.get(user_id)
    if not user or user.privilages_ != 'admin':
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Update workflow configs
        form_types = ['medical_withdrawal', 'student_drop', 'ferpa', 'info_change']
        for form_type in form_types:
            required_approvers = int(request.form.get(f"{form_type}_approvers", 2))
            required_roles = request.form.getlist(f"{form_type}_roles")
            
            config = WorkflowConfig.query.filter_by(form_type=form_type).first()
            if config:
                config.required_approvers = required_approvers
                config.required_roles = json.dumps(required_roles)
            else:
                config = WorkflowConfig(
                    form_type=form_type, 
                    required_approvers=required_approvers,
                    required_roles=json.dumps(required_roles)
                )
                db.session.add(config)
        
        db.session.commit()
        flash('Workflow settings updated successfully.', 'success')
        return redirect(url_for('workflow_settings'))

    # Get current configs
    configs = {}
    for config in WorkflowConfig.query.all():
        configs[config.form_type] = {
            'approvers': config.required_approvers,
            'roles': json.loads(config.required_roles) if config.required_roles else []
        }
    
    # Get all available roles for the form
    roles = Role.query.all()

    return render_template('workflow_settings.html', configs=configs, roles=roles)

# Update model methods to use configurable approver count
def _is_fully_approved(model, form_type):
    """Generic helper to check if a form has enough approvals"""
    if not model.admin_approvals:
        return False
    try:
        approved_by = json.loads(model.admin_approvals)
        required_approvers = WorkflowConfig.get_required_approvers(form_type)
        return len(approved_by) >= required_approvers
    except:
        return False

# Update the is_fully_approved methods for each model
def is_fully_approved(self):
    return _is_fully_approved(self, 'medical_withdrawal')

MedicalWithdrawalRequest.is_fully_approved = is_fully_approved

def is_fully_approved(self):
    return _is_fully_approved(self, 'student_drop')

StudentInitiatedDrop.is_fully_approved = is_fully_approved

def is_fully_approved(self):
    return _is_fully_approved(self, 'ferpa')

FERPARequest.is_fully_approved = is_fully_approved

def is_fully_approved(self):
    return _is_fully_approved(self, 'info_change')

InfoChangeRequest.is_fully_approved = is_fully_approved

##### V3 Integration of New Forms #####
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
    user = Profile.query.get(user_id)
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
    user = Profile.query.get(user_id)
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
        pending_infochange_requests=pending_infochange_requests,
        config=WorkflowConfig  # Pass WorkflowConfig class to template
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
                db.session.add(UserRole(
                    user_id=user.id,
                    role_id=role.id
                ))
        
        db.session.commit()
        return redirect(url_for('adminpage'))  # Fix: Change from '/' to 'adminpage    # For GET request - show current role
    current_role = None
    if user.user_roles:  # Check if user has any roles
        current_role = user.user_roles[0].role.name if user.user_roles else 'student'
    return render_template('update.html', 
                         profile=user,
                         current_role=current_role)

@app.route("/create", methods=["GET", "POST"])
def create_profile():
    if request.method ==     "POST":
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
        return redirect(url_for('login'))  # Redirect to login if the user is not logged in

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
            signature=signature,
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
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user:
        return "User not found", 404

    # 1) load config for this form
    workflow = WorkflowConfig.query.filter_by(form_type='medical_withdrawal').first()
    if not workflow:
        flash('No workflow configured for medical withdrawals.', 'danger')
        return redirect(url_for('notifications'))

    # 2) check user roles
    user_roles = [ur.role.name for ur in user.user_roles]
    required = json.loads(workflow.required_roles)
    if not any(r in required for r in user_roles):
        flash('You lack the role to approve medical withdrawals.', 'danger')
        return redirect(url_for('notifications'))

    # 3) fetch the request and hand off to the helper
    req = MedicalWithdrawalRequest.query.get_or_404(request_id)
    success, message = _process_approval(req, user_id, 'medical_withdrawal')
    flash(message, 'success' if success else 'danger')
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

    # Change status to rejected
    req_record.status = 'rejected'
    db.session.commit()

    # Generate PDF with the updated function
    from pdf_utils import generate_medical_withdrawal_pdf
    pdf_path = generate_medical_withdrawal_pdf(req_record)

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
        latest_pdf = max(matching_files, key=lambda x: os.path.getctime(x))
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
        # Just store the text as the signature
        signature = request.form.get('signature_text')

    # Save the drop request to the database
    drop_request = StudentInitiatedDrop(
        student_name=student_name,
        student_id=student_id,
        course_title=course_title,
        reason=reason,
        date=date,
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
        return "Unauthorized", 403

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

    # Process Student Drops
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
        pending_infochange_requests=pending_infochange_requests,
        config=WorkflowConfig  # Pass WorkflowConfig class to template
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
@app.route('/student_initiated_drop')
def student_initiated_drop():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    # Add today's date for the form
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('student_initiated_drop.html', user=user, today_date=today_date)
def _process_approval(request, user_id, form_type):
    """Process an approval for any form type using workflow configuration"""
    if not request.has_admin_viewed(user_id):
        return False, 'You must view the request PDF before approving'
    
    if request.has_admin_approved(user_id):
        return False, 'You have already approved this request'

    # Add admin to approvals list
    if not request.admin_approvals:
        admin_approvals = [str(user_id)]
    else:
        admin_approvals = json.loads(request.admin_approvals)
        if str(user_id) not in admin_approvals:
            admin_approvals.append(str(user_id))
    
    request.admin_approvals = json.dumps(admin_approvals)
    
    # Get workflow configuration
    workflow = WorkflowConfig.query.filter_by(form_type=form_type).first()
    if not workflow:
        return False, f'No workflow configuration found for {form_type}'
    
    # Get user's roles
    user = Profile.query.get(user_id)
    if not user:
        return False, 'User not found'
        
    user_roles = [role.role.name for role in user.user_roles]
    
    # Check if user has required role from workflow
    required_roles = json.loads(workflow.required_roles)
    if not any(role in required_roles for role in user_roles):
        return False, 'You do not have the required role to approve this request'
    
    # Update status based on workflow config
    if len(admin_approvals) >= workflow.required_approvers:
        request.status = 'approved'
        message = f'{form_type.replace("_", " ").title()} request has been fully approved.'
    else:
        request.status = 'pending_approval'
        message = f'{form_type.replace("_", " ").title()} request has been partially approved. Awaiting additional approvals.'

    # Mark as viewed if not already
    viewed = json.loads(request.admin_viewed or '[]')
    if str(user_id) not in viewed:
        viewed.append(str(user_id))
    request.admin_viewed = json.dumps(viewed)

    return True, message
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
        latest_pdf = max(matching_files, key=lambda x: os.path.getctime(x))
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
@app.route('/approve_student_drop/<int:request_id>', methods=['POST'])
def approve_student_drop(request_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if not user:
        return "User not found", 404
        
    # Get user's roles
    user_roles = [role.role.name for role in user.user_roles]
    
    # Get workflow configuration
    workflow = WorkflowConfig.query.filter_by(form_type='student_drop').first()
    if not workflow:
        flash('No workflow configuration found for student drops.', 'error')
        return redirect(url_for('notifications'))
        
    # Check if user has any of the required roles
    required_roles = json.loads(workflow.required_roles)
    if not any(role in required_roles for role in user_roles):
        flash('You do not have the required role to approve student drop requests.', 'error')
        return redirect(url_for('notifications'))

    req = StudentInitiatedDrop.query.get_or_404(request_id)
    
    # Check if admin has viewed the PDF
    if not req.has_admin_viewed(user_id):
        return "You must view the PDF before approving", 400
        
    # Check if this admin has already approved
    if req.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))

    success, message = _process_approval(req, user_id, 'student_drop')
    flash(message, 'success' if success else 'danger')
    
    db.session.commit()
    return redirect(url_for('notifications'))
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        return "Unauthorized", 403

    req = StudentInitiatedDrop.query.get_or_404(request_id)
    if not req.has_admin_viewed(user_id):
        return "You must view the PDF before approving", 400
    if req.has_admin_approved(user_id):
        flash('You have already approved this request.', 'warning')
        return redirect(url_for('notifications'))

    approvals = json.loads(req.admin_approvals or '[]')
    approvals.append(str(user_id))
    req.admin_approvals = json.dumps(approvals)

    required = WorkflowConfig.get_required_approvers('student_drop')
    if len(approvals) >= required:
        req.status = 'approved'
        flash(f'Student drop fully approved ({len(approvals)}/{required}).', 'success')
    else:
        req.status = 'pending_approval'
        flash(f'Student drop partially approved ({len(approvals)}/{required}); awaiting more.', 'success')

    viewed = json.loads(req.admin_viewed or '[]')
    if str(user_id) not in viewed:
        viewed.append(str(user_id))
    req.admin_viewed = json.dumps(viewed)

    db.session.commit()
    return redirect(url_for('notifications'))

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

@app.route('/drafts')
def drafts():
    """View draft medical withdrawal requests"""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    draft_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id, status='draft').all()
    return render_template('drafts.html', draft_requests=draft_requests)

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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        initialize_roles_and_departments()  # Add this line
    app.run(debug=True)