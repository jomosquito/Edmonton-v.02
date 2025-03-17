# Imports
from flask import Flask, render_template, url_for, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from O365 import Account
import json
from config import client_id, client_secret, SECRET_KEY
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
db = SQLAlchemy(app)

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

# Profile Model helper for O365 token
def open1():
    with open('o365_token.txt', 'r') as token_file:
        token_data = json.load(token_file)
        account_data = token_data.get("Account")
        id_data = token_data.get("IdToken")
        for account in account_data.values():
            email = account.get("username")
            # Note: 'idtoken' assignment in loop is ambiguous; adjust as needed.
            idtoken = account.get
        for account in id_data.values():
            idtoken = account.get("home_account_id")
        return email, idtoken

# Profile Model
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
    profile_pic = db.Column(db.String(200), nullable=True)
    phoneN_ = db.Column(db.String(200), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    enroll_status = db.Column(db.String(200), nullable=True)
    date_created = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)

# -------------------------------
# New Model for Term Withdrawal Requests
# -------------------------------
class TermWithdrawalRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to access the requesting user's profile
    user = db.relationship('Profile', backref='withdrawal_requests')

    # Helper properties for display in the admin portal
    @property
    def request_type(self):
        return "Term Withdrawal"

    @property
    def details(self):
        return f"Reason: {self.reason}"

# -------------------------------
# Routes
# -------------------------------

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/notifications')
def notification():
    pending_requests = TermWithdrawalRequest.query.filter_by(status='pending').all()
    return render_template('notifications.html', pending_requests=pending_requests)

@app.route('/creat')
def index():
    return render_template('add_profile.html')

# Admin login page and route
@app.route('/admin')
def admin():
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
            user.email_ = new_email  # Use email_ from model
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

# Microsoft OAuth Step One
@app.route('/stepone')
def auth_step_one():
    callback = url_for('auth_step_two_callback', _external=True).replace("127.0.0.1", "localhost")
    account = Account(credentials)
    url, flow = account.con.get_authorization_url(requested_scopes=scopes, redirect_uri=callback)
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
    requested_url = request.url
    result = account.con.request_token(requested_url, flow=my_saved_flow)
    email, idtoken = open1()
    if result:
        profile = Profile.query.order_by(Profile.id.desc()).first()
        if profile:
            profile.email_ = email
            profile.usertokenid = idtoken
            db.session.commit()
        return redirect('/')
    return "Authentication failed", 400

# Add a new profile
@app.route('/add', methods=["POST"])
def add_profile():
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    phone_number = request.form.get("phoneN_")
    pass_word = request.form.get("pass_word")
    address = request.form.get("address")
    enroll_status = request.form.get("enroll_status")
    if first_name and pass_word:
        p = Profile(first_name=first_name, last_name=last_name, phoneN_=phone_number)
        p.set_password(pass_word)
        db.session.add(p)
        db.session.commit()
        return redirect('/stepone')
    else:
        return render_template('userhompage.html')

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
# New Endpoints for Term Withdrawal Requests
# -------------------------------

# Endpoint to receive a term withdrawal request from the user
@app.route('/Termdroprequest', methods=['POST'])
def term_withdraw_request():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    reason = request.form.get("reason")
    if not reason:
        return "No reason selected", 400
    new_request = TermWithdrawalRequest(user_id=user.id, reason=reason)
    db.session.add(new_request)
    db.session.commit()
    return redirect(url_for('settings'))

# Admin endpoint to view pending term withdrawal requests
@app.route('/approvals')
def approvals():
    pending_requests = TermWithdrawalRequest.query.filter_by(status='pending').all()
    return render_template('admin_notifications.html', pending_requests=pending_requests)

# Endpoint to approve a pending request
@app.route('/approve_request/<int:request_id>', methods=['POST'])
def approve_request(request_id):
    req_record = TermWithdrawalRequest.query.get(request_id)
    if req_record:
        req_record.status = 'approved'
        user = Profile.query.get(req_record.user_id)
        if user:
            user.enroll_status = req_record.reason
        db.session.commit()
    return redirect(url_for('approvals'))

# Endpoint to reject a pending request
@app.route('/reject_request/<int:request_id>', methods=['POST'])
def reject_request(request_id):
    req_record = TermWithdrawalRequest.query.get(request_id)
    if req_record:
        req_record.status = 'rejected'
        db.session.commit()
    return redirect(url_for('approvals'))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
