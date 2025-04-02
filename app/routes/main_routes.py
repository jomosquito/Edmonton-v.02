from flask import Blueprint, render_template, session, redirect, url_for, request, send_file
from app.models import Profile, MedicalWithdrawalRequest, StudentInitiatedDrop
from app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
from werkzeug.utils import secure_filename

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def home():
    return render_template('login.html')

@main_bp.route('/status')
def status():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))

    medical_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id).all()
    student_drop_requests = StudentInitiatedDrop.query.filter_by(student_id=user_id).all()

    return render_template(
        'status.html',
        medical_requests=medical_requests,
        student_drop_requests=student_drop_requests
    )

@main_bp.route('/notifications')
def notification():
    pending_medical_requests = MedicalWithdrawalRequest.query.filter_by(status='pending').all()
    pending_student_drops = StudentInitiatedDrop.query.filter_by(status='pending').all()
    
    return render_template(
        'notifications.html',
        pending_medical_requests=pending_medical_requests,
        pending_student_drops=pending_student_drops
    )

@main_bp.route('/profile')
def profileview():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = Profile.query.get(user_id)
    return render_template('profile.html', user=user)

@main_bp.route('/userhompage')
def user_home():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = Profile.query.get(user_id)
    return render_template('userhompage.html', user=user)

@main_bp.route('/settings', methods=['GET', 'POST'])
def settings():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = Profile.query.get(user_id)
    if request.method == 'POST':
        new_email = request.form.get("email")
        if new_email:
            user.email_ = new_email
            db.session.commit()
        return redirect(url_for('main.settings'))
    return render_template('settings.html', user=user)

@main_bp.route('/reports')
def reports():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = Profile.query.get(user_id)
    return render_template('reports.html', user=user)

@main_bp.route('/drafts')
def drafts():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    
    draft_requests = MedicalWithdrawalRequest.query.filter_by(user_id=user_id, status='draft').all()
    return render_template('drafts.html', draft_requests=draft_requests)

@main_bp.route('/creat')
def index():
    return render_template('add_profile.html')

@main_bp.route('/add', methods=["POST"])
def add_profile():
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    phone_number = request.form.get("phoneN_")
    pass_word = request.form.get("pass_word")
    confirm_password = request.form.get("confirm_password")
    address = request.form.get("address")
    enroll_status = request.form.get("enroll_status")
    
    errors = []
    import re
    phone_pattern = re.compile(r'^\d{3}-\d{3}-\d{4}$')
    if not phone_pattern.match(phone_number):
        errors.append("Invalid phone number format. Please use XXX-XXX-XXXX format.")
    
    if not address or len(address.strip()) < 5:
        errors.append("Please provide a complete address (minimum 5 characters).")
    
    if pass_word != confirm_password:
        errors.append("Passwords do not match.")
    
    if errors:
        return render_template('add_profile.html', errors=errors)
    
    if first_name and pass_word:
        p = Profile(first_name=first_name, last_name=last_name, phoneN_=phone_number, address=address)
        p.set_password(pass_word)
        db.session.add(p)
        db.session.commit()
        return redirect(url_for('auth.stepone'))
    else:
        return render_template('add_profile.html', errors=["First name and password are required"])

@main_bp.route("/create", methods=["GET", "POST"])
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
        return redirect(url_for('admin.admin'))
    return render_template("create.html")

@main_bp.route('/update/<int:id>', methods=['GET', 'POST'])
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
        return redirect(url_for('admin.admin'))
    return render_template('update.html', profile=user)

# Delete a profile
@main_bp.route('/delete/<int:id>')
def erase(id):
    data = Profile.query.get(id)
    if data:
        db.session.delete(data)
        db.session.commit()
    return redirect('/ap')

# Change privileges for a profile
@main_bp.route('/priv/<int:id>')
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