# Imports 
from flask import Flask, render_template, url_for, request, redirect, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from O365 import Account
import json
from config import client_id, client_secret
from werkzeug.security import generate_password_hash, check_password_hash
import jwt




app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
db = SQLAlchemy(app)

# Microsoft OAuth Credentials
credentials = (client_id, client_secret)
scopes = ['Mail.ReadWrite', 'Mail.Send','email']

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

# Profile Model
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
class Profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(20), nullable=False)
    last_name = db.Column(db.String(20), nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=True)
    pass_word = db.Column(db.String(200), nullable=False)  # Hashed passwords
    privilages_ = db.Column(db.String(20), default='user')
    email_ = db.Column(db.String(100), nullable=True)
    usertokenid= db.Column(db.String(100),nullable=True)
    def set_password(self, password):
        self.pass_word = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pass_word, password)

# Routes
@app.route('/')
def home():
    return render_template('login.html')

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
    return render_template('profile. html')
@app.route('/loginadmin', methods=['GET', 'POST'])
def loginadmin():
    if request.method == 'POST':
        first_name = request.form.get("first_name")
        pass_word = request.form.get("pass_word")
        profiles = Profile.query.all()
        # Check if user exists in the database
        user = Profile.query.filter_by(first_name=first_name).first()

        if user and user.check_password(pass_word) and user.privilages_ == "admin":
            # Check if the user's profile is active
            if not user.active:
                return "Your profile is deactivated. Please contact the administrator."
            
            return render_template('adminpage.html', profiles=profiles)
        else:
            return "Invalid username or password!"

    return render_template('adminlogin.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        first_name = request.form.get("first_name")
        pass_word = request.form.get("pass_word")

        # Check if user exists in the database
        user = Profile.query.filter_by(first_name=first_name).first()

        if user and user.check_password(pass_word):  # Verify hashed password
            # Check if the user's profile is active
            if not user.active:
                return "Your profile is deactivated. Please contact the administrator."
            
            return render_template('userhompage.html', user=user)
        else:
            return "Invalid username or password!"

    return render_template('log.html')  # Show login form for GET requests

# Toggle the active status of a profile
@app.route('/active/<int:id>')
def activate(id):
    profile = Profile.query.get(id)
    if profile is None:
        return redirect('/ap')
    
    # Toggle the boolean value: if True becomes False; if False becomes True
    profile.active = not profile.active

    # Save the changes
    db.session.commit()
    
    return redirect('/ap')

# Updated /ap route to return all profiles
@app.route('/ap')
def ap():
    profiles = Profile.query.all()  # Retrieve all profiles for the admin page
    return render_template('adminpage.html', profiles=profiles)

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

# Add a new profile
@app.route('/add', methods=["POST"])
def profile():
    first_name = request.form.get("first_name")
    pass_word = request.form.get("pass_word")

    if first_name and pass_word:
        p = Profile(first_name=first_name)
        p.set_password(pass_word)  # Hash password before storing
        db.session.add(p)
        db.session.commit()
       
        return redirect('/stepone')
    else:
       
        return redirect('/')

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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  
    app.run(debug=True)