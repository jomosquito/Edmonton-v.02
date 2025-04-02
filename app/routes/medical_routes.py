from flask import Blueprint, render_template, request, redirect, url_for, session, send_file, current_app
from app.models import MedicalWithdrawalRequest, Profile
from app import db
from datetime import datetime
import json
import os
from werkzeug.utils import secure_filename

medical_bp = Blueprint('medical', __name__, url_prefix='/medical')

@medical_bp.route('/withdrawal-form')
def medical_withdrawal_form():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    user = Profile.query.get(user_id)
    # Add today's date for the form
    today_date = datetime.now().strftime('%Y-%m-%d')
    return render_template('medical.medical_withdrawal.html', user=user, today_date=today_date)

@medical_bp.route('/submit', methods=['POST'])
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
                    upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'documentation')
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
                signature_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'signatures')
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
                signature_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'signatures')
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


@medical_bp.route('/view/<int:request_id>')
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


@medical_bp.route('/approve/<int:request_id>', methods=['POST'])
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
    
@medical_bp.route('/reject/<int:request_id>', methods=['POST'])
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
    
@medical_bp.route('/download/<int:request_id>/<string:status>')
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