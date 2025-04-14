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
    first_name = db.Column(db.String(20), nullable=False)
    last_name = db.Column(db.String(20), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=True)
    pass_word = db.Column(db.String(200), nullable=False)  # Hashed passwords
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

    def has_admin_viewed(self, admin_id):
        if not self.admin_viewed:
            return False
        viewed_by = json.loads(self.admin_viewed)
        return str(admin_id) in viewed_by

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
    peoplesoft_id = StringField('PSID', validators=[DataRequired(), Length(min=6, max=6)])

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
            return render_template('ferpa_form.html', form=form, user=user)

        file = request.files['signature']
        if file.filename == '':
            flash('No file selected for signature.', 'danger')
            return render_template('ferpa_form.html', form=form, user=user)

        # Check if file type is allowed
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
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

            # Generate PDF
            pdf_file = generate_ferpa(data, forms_dir, signatures_dir)

            # Store options as comma-separate string
            official_choices_str = ",".join(form.official_choices.data)
            info_choices_str = ",".join(form.info_choices.data)
            release_choices_str = ",".join(form.release_choices.data)

            # Set status based on draft checkbox
            status = "draft" if form.is_draft.data else "pending"

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
                date=data['DATE']
            )

            # Commit FERPA request to database
            db.session.add(new_ferpa_request)
            db.session.commit()

            if form.is_draft.data:
                flash('FERPA request saved as draft.', 'success')
            else:
                flash('FERPA request submitted successfully.', 'success')

            return redirect(url_for('status'))

    # Set default date to today
    if request.method == 'GET':
        form.date.data = date.today()

    return render_template('ferpa_form.html', form=form, user=user)

@app.route('/name-ssn-change', methods=['GET', 'POST'])
def name_ssn_change():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = Profile.query.get(user_id)
    form = InfoChangeForm()

    if form.validate_on_submit():
        # Handle file upload for signature
        if 'signature' not in request.files:
            flash('Signature was not uploaded.', 'danger')
            return render_template('name_ssn_change.html', form=form, user=user)

        file = request.files['signature']
        if file.filename == '':
            flash('No file selected for signature.', 'danger')
            return render_template('name_ssn_change.html', form=form, user=user)

        # Check if file type is allowed
        if file and allowed_file(file.filename, {'png', 'jpg', 'jpeg', 'gif'}):
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
            choice = form.choice.data
            name_change_reason = form.name_change_reason.data if form.name_change_reason.data else []
            ssn_change_reason = form.ssn_change_reason.data if form.ssn_change_reason.data else []

            data = {
                "NAME": form.name.data,
                "PEOPLESOFT": form.peoplesoft_id.data,
                "EDIT_NAME": return_choice(choice, 'name'),
                "EDIT_SSN": return_choice(choice, 'ssn'),
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

            # Generate PDF and store path
            pdf_file = generate_ssn_name(data, forms_dir, signatures_dir)

            # Store options as comma-separated strings
            choice_str = ",".join(form.choice.data)
            name_change_reason_str = ",".join(name_change_reason)
            ssn_change_reason_str = ",".join(ssn_change_reason)

            # Set status based on draft checkbox
            status = "draft" if form.is_draft.data else "pending"

            # Create new request
            new_request = InfoChangeRequest(
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
                date=data['DATE']
            )

            # Commit request to database
            db.session.add(new_request)
            db.session.commit()

            if form.is_draft.data:
                flash('Name/SSN change request saved as draft.', 'success')
            else:
                flash('Name/SSN change request submitted successfully.', 'success')

            return redirect(url_for('status'))

    # Set default date to today
    if request.method == 'GET':
        form.date.data = date.today()
        # Pre-populate with user's name if available
        if user.first_name:
            form.name.data = f"{user.first_name} {user.last_name}"
            form.first_name_old.data = user.first_name
            form.last_name_old.data = user.last_name

    return render_template('name_ssn_change.html', form=form, user=user)

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
        infochange_requests=infochange_requests
    )

# Add routes for downloading FERPA and Info Change PDFs
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

    forms_dir = os.path.join('static', 'forms')
    pdf_path = os.path.join(forms_dir, ferpa_request.pdf_link)

    if not os.path.exists(pdf_path):
        flash('PDF file not found.', 'danger')
        return redirect(url_for('status'))

    return send_file(pdf_path, as_attachment=True)

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

    forms_dir = os.path.join('static', 'forms')
    pdf_path = os.path.join(forms_dir, infochange_request.pdf_link)

    if not os.path.exists(pdf_path):
        flash('PDF file not found.', 'danger')
        return redirect(url_for('status'))

    return send_file(pdf_path, as_attachment=True)

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
    ferpa_request.status = 'approved'
    db.session.commit()

    flash('FERPA request approved.', 'success')
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
    db.session.commit()

    flash('FERPA request rejected.', 'success')
    return redirect(url_for('notifications'))

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
    infochange_request.status = 'approved'
    db.session.commit()

    flash('Name/SSN change request approved.', 'success')
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
    db.session.commit()

    flash('Name/SSN change request rejected.', 'success')
    return redirect(url_for('notifications'))


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


@app.route('/notifications')
def notification():
    # Query pending medical withdrawal requests
    pending_medical_requests = MedicalWithdrawalRequest.query.filter_by(status='pending').all()

    # Query pending student drop requests
    pending_student_drops = StudentInitiatedDrop.query.filter_by(status='pending').all()

    # Query pending FERPA requests
    pending_ferpa_requests = FERPARequest.query.filter_by(status='pending').all()

    # Query pending Info Change requests
    pending_infochange_requests = InfoChangeRequest.query.filter_by(status='pending').all()

    return render_template(
        'notifications.html',
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops,
        pending_ferpa_requests=pending_ferpa_requests,
        pending_infochange_requests=pending_infochange_requests
    )
@app.route('/creat')
def index():
    return render_template('add_profile.html')

# Admin login page and route
@app.route('/admin')
def admin():
    # If already logged in as admin, redirect to dashboard
    if session.get('user_id') and session.get('admin'):
        return redirect(url_for('ap'))

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
    profiles = Profile.query.all()

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
def user_home():
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
    return redirect('/ap')

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
            now = datetime.utcnow()

            return render_template(
                'admin_dashboard.html',
                profiles=profiles,
                pending_medical_requests=pending_medical_requests,
                pending_student_drops=pending_student_drops,
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

    # Add current server time for the dashboard
    now = datetime.utcnow()

    return render_template(
        'admin_dashboard.html',
        profiles=profiles,
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops,
        now=now
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

# Microsoft OAuth Step Two Callback
@app.route('/steptwo')
def auth_step_two_callback():
    account = Account(credentials)

    my_saved_flow_str = my_db.get_flow()

    if not my_saved_flow_str:
        return "Flow state not found. Restart authentication.", 400

    my_saved_flow = deserialize(my_saved_flow_str)
    requested_url = request.url  # Get current URL with auth code
    result = account.con.request_token(requested_url, flow=my_saved_flow)
    email, idtoken=open1()


    if result:
        profile = Profile.query.order_by(Profile.id.desc()).first()
        if profile:
            profile.email_ = email  # Update the email field
            profile.usertokenid = idtoken
            db.session.commit()
        return redirect('/')


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
        return redirect('/ap')
    if data.privilages_ == "user":
        data.privilages_ = "admin"
    else:
        data.privilages_ = "user"
    db.session.commit()
    return redirect('/ap')

# Delete a profile
@app.route('/delete/<int:id>')
def erase(id):
    data = Profile.query.get(id)
    if data:
        db.session.delete(data)
        db.session.commit()
    return redirect('/ap')

@app.route('/update/<int:id>', methods=['GET', 'POST'])
def update_user(id):
    user = Profile.query.get(id)
    if not user:
        return "User not found", 404
    if request.method == 'POST':
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        phone_number = request.form.get("phoneN_")
        privileges = request.form.get("privileges")
        active = True if request.form.get("active") == "on" else False
        new_password = request.form.get("pass_word")
        user.first_name = first_name
        user.last_name = last_name
        user.email_ = email
        user.phoneN_ = phone_number
        user.privilages_ = privileges
        user.active = active
        if new_password:
            user.set_password(new_password)
        db.session.commit()
        return redirect('/ap')
    return render_template('update.html', profile=user)

@app.route("/create", methods=["GET", "POST"])
def create_profile():
    if request.method == "POST":
        password = request.form.get("pass_word")
        if not password:
            return "Password is required", 400
        new_profile = Profile(
            first_name=request.form.get("first_name"),
            last_name=request.form.get("last_name"),
            email_=request.form.get("email"),
            privilages_=request.form.get("privileges"),
            active=request.form.get("active") == "on",
            pass_word=generate_password_hash(password)
        )
        db.session.add(new_profile)
        db.session.commit()
        return redirect('/ap')
    return render_template("create.html")

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

    user = Profile.query.get(user_id)
    if user.privilages_ != 'admin':
        return "Unauthorized", 403

    req_record = MedicalWithdrawalRequest.query.get(request_id)
    if not req_record:
        return "Request not found", 404

    # Check if admin has viewed the PDF
    if not req_record.has_admin_viewed(user_id):
        return "You must view the request PDF before approving", 400

    # Get comments from form
    comments = request.form.get('comments', '')

    # Create history record
    history_entry = WithdrawalHistory(
        withdrawal_id=request_id,
        admin_id=user_id,
        action='approved',
        comments=comments
    )
    db.session.add(history_entry)

    # Change status to approved
    req_record.status = 'approved'
    db.session.commit()

    # Get admin signature if available
    admin_signature = None  # You'd need to implement signature storage for admins

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

    return redirect(url_for('notification'))

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

    return redirect(url_for('notification'))

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

    return redirect(url_for('notification'))

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

    # Combine both types of form submissions
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

        history_entries.append({
            'timestamp': req.updated_at or req.created_at,
            'form_type': 'Medical Withdrawal',
            'status': req.status,
            'reviewed_by': history.admin.first_name + ' ' + history.admin.last_name if history else 'System',
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
            'timestamp': req.updated_at or req.created_at,  # Use updated_at if available
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
            'timestamp': drop.created_at,  # Student drops might not have updated_at
            'form_type': 'Student Course Drop',
            'status': drop.status,
            'reviewed_by': 'System'  # Modify if you track approvers
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

    # Change status to approved
    req_record.status = 'approved'
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

    return redirect(url_for('notification'))


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

    return redirect(url_for('notification'))

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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)