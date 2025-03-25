# Imports
from flask import Flask, render_template, url_for, request, redirect, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from O365 import Account
import json
import os
from config import client_id, client_secret, SECRET_KEY
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
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
    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)

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

# -------------------------------
# Routes
# -------------------------------

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/status')
def status():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))  # Redirect to login if the user is not logged in

    # Query medical withdrawal requests for the logged-in user
    medical_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id).all()

    # Query student-initiated drop requests for the logged-in user
    student_drop_requests = StudentInitiatedDrop.query.filter_by(student_id=user_id).all()

    return render_template(
        'status.html',
        medical_requests=medical_requests,
        student_drop_requests=student_drop_requests
    )
@app.route('/notifications')
def notification():
    # Query pending medical withdrawal requests
    pending_medical_requests = MedicalWithdrawalRequest.query.filter_by(status='pending').all()
    
    # Query pending student drop requests
    pending_student_drops = StudentInitiatedDrop.query.filter_by(status='pending').all()
    
    return render_template(
        'notifications.html',
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops
    )
@app.route('/creat')
def index():
    return render_template('add_profile.html')

# Admin login page and route
@app.route('/admin')
def admin():
    profiles = Profile.query.all()  # Retrieve all profiles from the database
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

@app.route('/loginadmin', methods=['GET', 'POST'])
def loginadmin():
    if request.method == 'POST':
        first_name = request.form.get("first_name")
        pass_word = request.form.get("pass_word")
        profiles = Profile.query.all()
        user = Profile.query.filter_by(first_name=first_name).first()
        if user and user.check_password(pass_word) and user.privilages_ == "admin":
            return render_template('adminpage.html', profiles=profiles)
        else:
            return "Invalid username or password!"
    return render_template('adminlogin.html')

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

# Updated /ap route to return all profiles
@app.route('/ap')
def ap():
    profiles = Profile.query.all()
    return render_template('adminpage.html', profiles=profiles)

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
    return redirect(url_for('login'))

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
    
    # Change status to approved
    req_record.status = 'approved'
    db.session.commit()
    
    # Get admin signature if available
    admin_signature = None  # You'd need to implement signature storage for admins
    
    # Generate PDF with LaTeX
    from pdf_utils import generate_medical_withdrawal_pdf
    pdf_path = generate_medical_withdrawal_pdf(req_record, admin_signature)
    
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
    student_id = request.form.get('studentID')
    course_title = request.form.get('course')
    reason = request.form.get('reason')
    date_str = request.form.get('date')  # Get the date as a string
    signature_type = request.form.get('signature_type')

    # Validate form data
    if not all([student_name, student_id, course_title, reason, date_str, signature_type]):
        return "All fields are required", 400

    # Convert the date string to a Python date object
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date format. Please use YYYY-MM-DD.", 400

    # Handle signature based on the selected type
    if signature_type == 'draw':
        signature_data = request.form.get('signature_data')
        if not signature_data:
            return "Signature is required for the selected option", 400
    elif signature_type == 'upload':
        signature_upload = request.files.get('signature_upload')
        if not signature_upload:
            return "Signature file is required for the selected option", 400
        # Save the uploaded file (optional)
        signature_upload.save(f"uploads/{signature_upload.filename}")
    elif signature_type == 'text':
        signature_text = request.form.get('signature_text')
        if not signature_text:
            return "Typed signature is required for the selected option", 400

    # Save the drop request to the database
    drop_request = StudentInitiatedDrop(
        student_name=student_name,
        student_id=student_id,
        course_title=course_title,
        reason=reason,
        date=date,  # Use the converted Python date object
        signature=signature_type  # Save the signature type (optional)
    )
    db.session.add(drop_request)
    db.session.commit()

    return redirect(url_for('settings'))  # Redirect back to the settings page
@app.route('/admin/student_drops')
def admin_student_drops():
    drop_requests = StudentInitiatedDrop.query.all()
    return render_template('admin_student_drops.html', drop_requests=drop_requests)
@app.route('/approve_student_drop/<int:request_id>', methods=['POST'])
def approve_student_drop(request_id):
    """Approve a student-initiated drop request and generate a PDF"""
    req_record = StudentInitiatedDrop.query.get(request_id)
    if req_record:
        # Get admin signature if available
        user_id = session.get('user_id')
        admin = Profile.query.get(user_id)
        admin_signature = None  # You'd need to implement signature storage for admins

        # Change status to approved
        req_record.status = 'approved'
        db.session.commit()  # Commit first to save the status

        # Generate PDF with LaTeX
        from pdf_utils import generate_student_drop_pdf
        pdf_path = generate_student_drop_pdf(req_record, admin_signature)

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
    req_record = StudentInitiatedDrop.query.get(request_id)
    if req_record:
        req_record.status = 'rejected'
        db.session.commit()
    return redirect(url_for('notification'))
@app.route('/student_initiated_drop')
def student_initiated_drop():
    return render_template('student_initiated_drop.html')

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