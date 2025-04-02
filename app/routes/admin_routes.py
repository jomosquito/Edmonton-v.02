from flask import Blueprint, render_template, redirect, url_for, request
from app.models import Profile, StudentInitiatedDrop, MedicalWithdrawalRequest
from app import db

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/')
def admin():
    profiles = Profile.query.all()
    return render_template('adminpage.html', profiles=profiles)

@admin_bp.route('/active/<int:id>')
def activate(id):
    profile = Profile.query.get(id)
    if profile is None:
        return redirect(url_for('admin.admin'))
    profile.active = not profile.active
    db.session.commit()
    return redirect(url_for('admin.admin'))

@admin_bp.route('/priv/<int:id>')
def change_privileges(id):
    data = Profile.query.get(id)
    if data is None:
        return redirect(url_for('admin.admin'))
    if data.privilages_ == "user":
        data.privilages_ = "admin"
    else:
        data.privilages_ = "user"
    db.session.commit()
    return redirect(url_for('admin.admin'))

@admin_bp.route('/delete/<int:id>')
def erase(id):
    data = Profile.query.get(id)
    if data:
        db.session.delete(data)
        db.session.commit()
    return redirect(url_for('adminpage.html'))

@admin_bp.route('/student_drops')
def admin_student_drops():
    drop_requests = StudentInitiatedDrop.query.all()
    return render_template('admin_student_drops.html', drop_requests=drop_requests)
