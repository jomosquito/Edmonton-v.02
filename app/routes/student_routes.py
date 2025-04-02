from flask import Blueprint, render_template, request, redirect, url_for, session
from app.models import StudentInitiatedDrop, Profile
from app import db
from datetime import datetime
import json  # Add this import at the top
from werkzeug.utils import secure_filename
import os  # Add if you're doing file operations

student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.route('/initiated-drop')
def student_initiated_drop():
    return render_template('student_initiated_drop.html')

@student_bp.route('/submit-drop', methods=['POST'])
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

    return redirect(url_for('settings'))

@student_bp.route('/approve/<int:request_id>', methods=['POST'])
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

@student_bp.route('/reject/<int:request_id>', methods=['POST'])
def reject_student_drop(request_id):
    req_record = StudentInitiatedDrop.query.get(request_id)
    if req_record:
        req_record.status = 'rejected'
        db.session.commit()
    return redirect(url_for('notification'))