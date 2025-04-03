import os
import json
import subprocess
import shutil
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                   filename='pdf_generation.log',
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def generate_student_drop_pdf(request_data, admin_signature=None):
    """
    Generate a PDF from the student drop request using LaTeX
    
    Args:
        request_data: The StudentInitiatedDrop object
        admin_signature: Path to admin signature image file (if approved)
        
    Returns:
        str: Path to the generated PDF file
    """
    try:
        # Create necessary directories
        pdf_dir = os.path.join('static', 'pdfs')
        temp_dir = os.path.join('static', 'temp')
        
        # Look in the static/templates directory for the template
        template_dir = os.path.join('static', 'templates')
        
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        
        logger.debug(f"PDF directory: {os.path.abspath(pdf_dir)}")
        logger.debug(f"Template directory: {os.path.abspath(template_dir)}")
        
        # Status and unique identifier for the file
        status = request_data.status
        file_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Check if LaTeX template exists - first see if the specific template exists
        template_path = os.path.join(template_dir, 'student_drop_template.tex')
        logger.debug(f"Looking for template at: {os.path.abspath(template_path)}")
        
        # If the specific template doesn't exist, fall back to the existing medical withdrawal template
        if not os.path.exists(template_path):
            logger.info(f"Student drop template not found, using medical withdrawal template")
            template_path = os.path.join(template_dir, 'medical_withdrawal_template.tex')
            
            if not os.path.exists(template_path):
                logger.error(f"Template not found at {template_path}")
                # Try finding it in a different location as a fallback
                alt_template_path = os.path.join('templates', 'medical_withdrawal_template.tex')
                logger.debug(f"Trying alternative template location: {os.path.abspath(alt_template_path)}")
                
                if os.path.exists(alt_template_path):
                    logger.info(f"Found template at alternative location: {alt_template_path}")
                    template_path = alt_template_path
                else:
                    logger.error("Template not found in alternative location either")
                    return None
            else:
                logger.info(f"Template found at: {template_path}")
            
        # Read the LaTeX template
        with open(template_path, 'r', encoding='utf-8') as file:
            template_content = file.read()
        
        # Replace placeholders with actual values - we'll adapt the medical withdrawal format
        template_content = template_content.replace('FORMID', str(request_data.id))
        template_content = template_content.replace('University of Houston - Medical/Administrative Term Withdrawal Form', 'University of Houston - Student-Initiated Drop Form')
        template_content = template_content.replace('Medical/Administrative Term Withdrawal Request Form', 'Student-Initiated Drop Request Form')
        
        # Student Information
        template_content = template_content.replace('FULLNAME', request_data.student_name)
        template_content = template_content.replace('MYUHID', request_data.student_id)
        
        # Remove or adapt sections that don't apply to student drop
        # We can simplify sections by replacing them with appropriate content
        template_content = template_content.replace('\\section*{1. Student Information}', '\\section*{Student Information}')
        
        # Course information - adapt for the drop request
        course_content = f"\\begin{{tabular}}{{ll}}\nCourse Title / Number: & \\textbf{{{request_data.course_title}}} \\\\\n\\end{{tabular}}"
        
        # Replace the original address section
        address_section_start = "\\section*{2. Current Mailing Address}"
        address_section_end = "\\section*{3. Term Information}"
        
        # Find the index where the address section starts and ends
        start_idx = template_content.find(address_section_start)
        end_idx = template_content.find(address_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Replace the entire address section with course information
            original_section = template_content[start_idx:end_idx]
            new_section = "\\section*{Course Information}\n" + course_content + "\n\n"
            template_content = template_content.replace(original_section, new_section)
        
        # Replace term information with drop reason
        term_section_start = "\\section*{3. Term Information}"
        term_section_end = "\\section*{4. Last Date Attended Classes}"
        
        # Find the index where the term section starts and ends
        start_idx = template_content.find(term_section_start)
        end_idx = template_content.find(term_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Replace the entire term section with reason information
            original_section = template_content[start_idx:end_idx]
            new_section = "\\section*{Reason for Drop}\n"
            new_section += "\\begin{tabular}{p{12cm}}\n"
            new_section += f"\\textbf{{{request_data.reason}}}\n"
            new_section += "\\end{tabular}\n\n"
            template_content = template_content.replace(original_section, new_section)
        
        # Replace the last date attended section with drop date
        last_date_section_start = "\\section*{4. Last Date Attended Classes}"
        last_date_section_end = "\\section*{5. Reason for Request}"
        
        # Find the index where the section starts and ends
        start_idx = template_content.find(last_date_section_start)
        end_idx = template_content.find(last_date_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Replace with drop date information
            original_section = template_content[start_idx:end_idx]
            date_str = request_data.date.strftime('%B %d, %Y') if hasattr(request_data, 'date') else datetime.utcnow().strftime('%B %d, %Y')
            new_section = "\\section*{Drop Request Date}\n"
            new_section += "\\begin{tabular}{ll}\n"
            new_section += f"Date: & \\textbf{{{date_str}}} \\\\\n"
            new_section += "\\end{tabular}\n\n"
            template_content = template_content.replace(original_section, new_section)
        
        # Remove the reason section since we've already handled it
        reason_section_start = "\\section*{5. Reason for Request}"
        reason_section_end = "\\section*{6. Additional Information}"
        
        start_idx = template_content.find(reason_section_start)
        end_idx = template_content.find(reason_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Remove the section
            original_section = template_content[start_idx:end_idx]
            template_content = template_content.replace(original_section, "")
        
        # Remove the additional info section
        additional_info_start = "\\section*{6. Additional Information}"
        additional_info_end = "\\section*{7. Courses to be Withdrawn}"
        
        start_idx = template_content.find(additional_info_start)
        end_idx = template_content.find(additional_info_end)
        
        if start_idx != -1 and end_idx != -1:
            # Remove the section
            original_section = template_content[start_idx:end_idx]
            template_content = template_content.replace(original_section, "")
        
        # Remove the courses section
        courses_section_start = "\\section*{7. Courses to be Withdrawn}"
        courses_section_end = "\\section*{Acknowledgement}"
        
        start_idx = template_content.find(courses_section_start)
        end_idx = template_content.find(courses_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Remove the section
            original_section = template_content[start_idx:end_idx]
            template_content = template_content.replace(original_section, "")
        
        # Update the acknowledgement text
        acknowledgement_section_start = "\\section*{Acknowledgement}"
        acknowledgement_section_end = "\\section*{Student Signature}"
        
        start_idx = template_content.find(acknowledgement_section_start)
        end_idx = template_content.find(acknowledgement_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Replace the acknowledgement text
            original_section = template_content[start_idx:end_idx]
            new_section = "\\section*{Acknowledgement}\n"
            new_section += "\\noindent\\fbox{\\parbox{\\dimexpr\\textwidth-2\\fboxsep-2\\fboxrule}{\n"
            new_section += "I understand that by submitting this request, I am asking to drop the specified course. "
            new_section += "I understand that this may affect my academic progress, financial aid eligibility, "
            new_section += "and enrollment status. I certify that I have consulted with my academic advisor "
            new_section += "regarding this decision, and I authorize the University of Houston to process my request.\n"
            new_section += "}}\n\n"
            template_content = template_content.replace(original_section, new_section)
        
        # Handle signature - similar to medical withdrawal function
        signature_section_start = "\\section*{Student Signature}"
        signature_section_end = "\\section*{Documentation}"
        
        start_idx = template_content.find(signature_section_start)
        end_idx = template_content.find(signature_section_end)
        
        # Process signature if we can find the signature section
        if start_idx != -1 and end_idx != -1:
            # Replace with signature information
            original_section = template_content[start_idx:end_idx]
            
            signature_content = "\\section*{Student Signature}\n\\begin{tabular}{ll}\n"
            
            # Handle signature based on its type
            sig_replaced = False
            if hasattr(request_data, 'signature') and request_data.signature:
                if os.path.exists(request_data.signature):
                    # It's a file path
                    signature_path = os.path.abspath(request_data.signature)
                    signature_content += f"Signature: & \\includegraphics[width=5cm]{{{signature_path}}} \\\\\n"
                    sig_replaced = True
                    logger.debug(f"Using signature file path: {signature_path}")
                elif request_data.signature.startswith('data:image'):
                    # It's a data URL, save it as an image
                    import base64
                    sig_dir = os.path.join('static', 'uploads', 'signatures')
                    os.makedirs(sig_dir, exist_ok=True)
                    
                    sig_filename = f"temp_sig_{request_data.id}_{file_id}.png"
                    sig_path = os.path.join(sig_dir, sig_filename)
                    
                    try:
                        img_data = request_data.signature.split(',')[1]
                        with open(sig_path, "wb") as f:
                            f.write(base64.b64decode(img_data))
                            
                        signature_content += f"Signature: & \\includegraphics[width=5cm]{{{os.path.abspath(sig_path)}}} \\\\\n"
                        sig_replaced = True
                        logger.debug(f"Created signature image from data URL: {sig_path}")
                    except Exception as e:
                        logger.error(f"Error processing signature data URL: {str(e)}")
                else:
                    # It's text
                    signature_content += f"Signature: & {request_data.signature} \\\\\n"
                    sig_replaced = True
            
            if not sig_replaced:
                # No signature or couldn't process
                signature_content += "Signature: & No signature provided \\\\\n"
            
            # Add the date
            date_str = request_data.date.strftime('%B %d, %Y') if hasattr(request_data, 'date') else datetime.utcnow().strftime('%B %d, %Y')
            signature_content += f"Date: & {date_str} \\\\\n"
            signature_content += "\\end{tabular}\n\n"
            
            template_content = template_content.replace(original_section, signature_content)
        
        # Remove the documentation section since it's not needed for student drops
        documentation_section_start = "\\section*{Documentation}"
        documentation_section_end = "\\section*{Request Information}"
        
        start_idx = template_content.find(documentation_section_start)
        end_idx = template_content.find(documentation_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Remove the section
            original_section = template_content[start_idx:end_idx]
            template_content = template_content.replace(original_section, "")
        
        # Update request information
        request_info_section_start = "\\section*{Request Information}"
        request_info_section_end = "ADMIN_SIGNATURE_SECTION"
        
        start_idx = template_content.find(request_info_section_start)
        end_idx = template_content.find(request_info_section_end)
        
        if start_idx != -1 and end_idx != -1:
            # Replace with request information
            original_section = template_content[start_idx:end_idx]
            
            new_section = "\\section*{Request Information}\n"
            new_section += "\\begin{tabular}{ll}\n"
            
            # Add creation date
            created_date = request_data.created_at.strftime('%B %d, %Y') if hasattr(request_data, 'created_at') else datetime.utcnow().strftime('%B %d, %Y')
            new_section += f"Date Submitted: & {created_date} \\\\\n"
            
            # Add status
            new_section += f"Request Status: & \\textbf{{{status.upper()}}} \\\\\n"
            
            new_section += "\\end{tabular}\n\n"
            template_content = template_content.replace(original_section, new_section)
        
        # Admin signature if approved
        admin_sig_section = ""
        if admin_signature and status == 'approved':
            admin_sig_path = os.path.abspath(admin_signature)
            admin_sig_section = f"""\\section*{{Administrative Approval}}
            \\begin{{tabular}}{{l l}}
            Administrator Signature: & \\includegraphics[width=5cm]{{{admin_sig_path}}} \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
        elif status == 'approved':
            admin_sig_section = f"""\\section*{{Administrative Approval}}
            \\begin{{tabular}}{{l l}}
            Administrator: & Approved electronically \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
        elif status == 'rejected':
            admin_sig_section = f"""\\section*{{Administrative Decision}}
            \\begin{{tabular}}{{l l}}
            Status: & \\textbf{{REJECTED}} \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
            
        template_content = template_content.replace('ADMIN_SIGNATURE_SECTION', admin_sig_section)
        
        # Create a temporary tex file
        tex_filename = f"student_drop_{request_data.id}_{status}_{file_id}.tex"
        tex_path = os.path.join(temp_dir, tex_filename)
        
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        logger.debug(f"Created temporary LaTeX file at: {tex_path}")
        
        # Generate PDF filename
        pdf_filename = f"student_drop_{request_data.id}_{status}_{file_id}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        # Compile the LaTeX file to create a PDF - this part is the same as in generate_medical_withdrawal_pdf
        try:
            # Try to find pdflatex in various locations
            logger.debug("Searching for pdflatex executable...")
            pdflatex_paths = [
                "pdflatex",  # Try system PATH first
                r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
                r"C:\Program Files (x86)\MiKTeX\miktex\bin\pdflatex.exe",
                r"/usr/bin/pdflatex",  # Linux
                r"/usr/local/bin/pdflatex",  # macOS
                r"C:\texlive\2022\bin\win32\pdflatex.exe",  # TexLive on Windows
            ]
            
            pdflatex = None
            for path in pdflatex_paths:
                try:
                    logger.debug(f"Trying pdflatex at: {path}")
                    result = subprocess.run([path, "--version"], 
                                         stdout=subprocess.PIPE, 
                                         stderr=subprocess.PIPE)
                    if result.returncode == 0:
                        pdflatex = path
                        logger.info(f"Found pdflatex at: {path}")
                        break
                except Exception as e:
                    logger.debug(f"Failed to execute {path}: {str(e)}")
            
            if not pdflatex:
                logger.error("pdflatex not found. Make sure LaTeX is installed.")
                return None
                
            # Run pdflatex with extended error reporting
            logger.debug(f"Running pdflatex with output directory: {os.path.abspath(pdf_dir)}")
            logger.debug(f"Source file: {os.path.abspath(tex_path)}")
            
            # Create directory if it doesn't exist
            os.makedirs(pdf_dir, exist_ok=True)
            
            # Run pdflatex
            process = subprocess.run(
                [pdflatex, '-interaction=nonstopmode', 
                 f'-output-directory={os.path.abspath(pdf_dir)}', 
                 os.path.abspath(tex_path)],
                capture_output=True, text=True
            )
            
            # Check if PDF was created
            if process.returncode != 0:
                logger.error("Error compiling LaTeX file:")
                logger.error(process.stderr)
                logger.error(process.stdout)  # Also log stdout for more context
                return None
            
            # Run pdflatex a second time to resolve references
            process = subprocess.run(
                [pdflatex, '-interaction=nonstopmode', 
                 f'-output-directory={os.path.abspath(pdf_dir)}', 
                 os.path.abspath(tex_path)],
                capture_output=True, text=True
            )
                
            # Check if PDF file was actually created
            expected_pdf_path = os.path.join(pdf_dir, pdf_filename)
            if os.path.exists(expected_pdf_path):
                logger.info(f"PDF generated successfully at: {expected_pdf_path}")
            else:
                logger.error(f"PDF not found at expected location: {expected_pdf_path}")
                # Check if PDF has a different name (without file_id perhaps)
                base_name = f"student_drop_{request_data.id}_{status}"
                for file in os.listdir(pdf_dir):
                    if file.startswith(base_name) and file.endswith('.pdf'):
                        expected_pdf_path = os.path.join(pdf_dir, file)
                        logger.info(f"Found PDF with different name: {expected_pdf_path}")
                        break
            
            # Clean up auxiliary files
            for ext in ['.aux', '.log', '.out']:
                aux_file = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}{ext}")
                if os.path.exists(aux_file):
                    os.remove(aux_file)
                    logger.debug(f"Removed auxiliary file: {aux_file}")
            
            # Clean up temporary tex file
            os.remove(tex_path)
            logger.debug(f"Removed temporary LaTeX file: {tex_path}")
                
            return expected_pdf_path
            
        except Exception as e:
            logger.error(f"Error running pdflatex: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Error generating student drop PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

def generate_medical_withdrawal_pdf(request_data, admin_signature=None):
    """
    Generate a PDF from the medical withdrawal request using LaTeX
    
    Args:
        request_data: The MedicalWithdrawalRequest object
        admin_signature: Path to admin signature image file (if approved)
        
    Returns:
        str: Path to the generated PDF file
    """
    try:
        # Create necessary directories
        pdf_dir = os.path.join('static', 'pdfs')
        temp_dir = os.path.join('static', 'temp')
        
        # IMPORTANT: Look in the static/templates directory instead of templates
        template_dir = os.path.join('static', 'templates')
        
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        
        logger.debug(f"PDF directory: {os.path.abspath(pdf_dir)}")
        logger.debug(f"Template directory: {os.path.abspath(template_dir)}")
        
        # Status and unique identifier for the file
        status = request_data.status
        file_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Check if LaTeX template exists
        template_path = os.path.join(template_dir, 'medical_withdrawal_template.tex')
        logger.debug(f"Looking for template at: {os.path.abspath(template_path)}")
        
        if not os.path.exists(template_path):
            logger.error(f"Template not found at {template_path}")
            # Try finding it in a different location as a fallback
            alt_template_path = os.path.join('templates', 'medical_withdrawal_template.tex')
            logger.debug(f"Trying alternative template location: {os.path.abspath(alt_template_path)}")
            
            if os.path.exists(alt_template_path):
                logger.info(f"Found template at alternative location: {alt_template_path}")
                template_path = alt_template_path
            else:
                logger.error("Template not found in alternative location either")
                return None
        else:
            logger.info(f"Template found at: {template_path}")
            
        # Read the LaTeX template
        with open(template_path, 'r', encoding='utf-8') as file:
            template_content = file.read()
        
        # Replace placeholders with actual values
        template_content = template_content.replace('FORMID', str(request_data.id))
        template_content = template_content.replace('FULLNAME', f"{request_data.first_name} {request_data.middle_name or ''} {request_data.last_name}".strip())
        template_content = template_content.replace('MYUHID', request_data.myuh_id)
        template_content = template_content.replace('COLLEGE', request_data.college)
        template_content = template_content.replace('DEGREE', request_data.plan_degree)
        template_content = template_content.replace('PHONE', request_data.phone)
        template_content = template_content.replace('EMAIL', request_data.user.email_ or '')
        
        # Address information
        template_content = template_content.replace('ADDRESS', request_data.address)
        template_content = template_content.replace('CITY', request_data.city)
        template_content = template_content.replace('STATE', request_data.state)
        template_content = template_content.replace('ZIP', request_data.zip_code)
        
        # Term and last date
        template_content = template_content.replace('TERM_YEAR', request_data.term_year)
        template_content = template_content.replace('LAST_DATE', request_data.last_date.strftime('%B %d, %Y'))
        
        # Reason
        template_content = template_content.replace('REASON_TYPE', request_data.reason_type)
        template_content = template_content.replace('DETAILS', request_data.details or 'No additional details provided.')
        
        # Additional questions - Yes/No
        template_content = template_content.replace('FINANCIAL_ASSISTANCE', 'Yes' if request_data.financial_assistance else 'No')
        template_content = template_content.replace('HEALTH_INSURANCE', 'Yes' if request_data.health_insurance else 'No')
        template_content = template_content.replace('CAMPUS_HOUSING', 'Yes' if request_data.campus_housing else 'No')
        template_content = template_content.replace('VISA_STATUS', 'Yes' if request_data.visa_status else 'No')
        template_content = template_content.replace('GI_BILL', 'Yes' if request_data.gi_bill else 'No')
        
        # Course listings
        courses_content = ""
        if request_data.courses:
            courses = json.loads(request_data.courses)
            for course in courses:
                courses_content += f"{course['subject']} & {course['number']} & {course['section']} \\\\\n"
        
        template_content = template_content.replace('COURSES', courses_content)
        
        # Initial and signature
        template_content = template_content.replace('INITIAL', request_data.initial)
        
        # Handle signature based on its type
        sig_replaced = False
        if request_data.signature and os.path.exists(request_data.signature):
            # It's a file path
            signature_path = os.path.abspath(request_data.signature)
            template_content = template_content.replace('SIGNATURE_PATH', signature_path)
            sig_replaced = True
            logger.debug(f"Using signature file path: {signature_path}")
        elif request_data.signature and request_data.signature.startswith('data:image'):
            # It's a data URL, save it as an image
            import base64
            sig_dir = os.path.join('static', 'uploads', 'signatures')
            os.makedirs(sig_dir, exist_ok=True)
            
            sig_filename = f"temp_sig_{request_data.id}_{file_id}.png"
            sig_path = os.path.join(sig_dir, sig_filename)
            
            try:
                img_data = request_data.signature.split(',')[1]
                with open(sig_path, "wb") as f:
                    f.write(base64.b64decode(img_data))
                    
                template_content = template_content.replace('SIGNATURE_PATH', os.path.abspath(sig_path))
                sig_replaced = True
                logger.debug(f"Created signature image from data URL: {sig_path}")
            except Exception as e:
                logger.error(f"Error processing signature data URL: {str(e)}")
        
        if not sig_replaced:
            # Text signature or no signature
            sig_text = request_data.signature or 'No signature provided'
            template_content = template_content.replace('\\includegraphics[width=5cm]{SIGNATURE_PATH}', sig_text)
            logger.debug(f"Using text for signature: {sig_text}")
        
        # Signature date
        signature_date = request_data.signature_date.strftime('%B %d, %Y') if hasattr(request_data, 'signature_date') and request_data.signature_date else datetime.utcnow().strftime('%B %d, %Y')
        template_content = template_content.replace('SIGNATURE_DATE', signature_date)
        
        # Documentation files
        doc_count = 0
        doc_files = ""
        if request_data.documentation_files:
            files = json.loads(request_data.documentation_files)
            doc_count = len(files)
            for file_path in files:
                doc_files += os.path.basename(file_path) + ", "
            doc_files = doc_files.rstrip(", ")
        
        template_content = template_content.replace('DOCUMENTATION_COUNT', str(doc_count))
        template_content = template_content.replace('DOCUMENTATION_FILES', doc_files or "None")
        
        # Status and timestamps
        template_content = template_content.replace('STATUS', status.upper())
        template_content = template_content.replace('CREATED_DATE', request_data.created_at.strftime('%B %d, %Y'))
        
        # Admin signature if approved
        admin_sig_section = ""
        if admin_signature and status == 'approved':
            admin_sig_path = os.path.abspath(admin_signature)
            admin_sig_section = f"""\\section*{{Administrative Approval}}
            \\begin{{tabular}}{{l l}}
            Administrator Signature: & \\includegraphics[width=5cm]{{{admin_sig_path}}} \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
        elif status == 'approved':
            admin_sig_section = f"""\\section*{{Administrative Approval}}
            \\begin{{tabular}}{{l l}}
            Administrator: & Approved electronically \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
        elif status == 'rejected':
            admin_sig_section = f"""\\section*{{Administrative Decision}}
            \\begin{{tabular}}{{l l}}
            Status: & \\textbf{{REJECTED}} \\\\
            Date: & {datetime.utcnow().strftime('%B %d, %Y')} \\\\
            \\end{{tabular}}"""
            
        template_content = template_content.replace('ADMIN_SIGNATURE_SECTION', admin_sig_section)
        
        # Create a temporary tex file
        tex_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.tex"
        tex_path = os.path.join(temp_dir, tex_filename)
        
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        logger.debug(f"Created temporary LaTeX file at: {tex_path}")
        
        # Generate PDF filename
        pdf_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        # Compile the LaTeX file to create a PDF
        try:
            # Try to find pdflatex in various locations
            logger.debug("Searching for pdflatex executable...")
            pdflatex_paths = [
                "pdflatex",  # Try system PATH first
                r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
                r"C:\Program Files (x86)\MiKTeX\miktex\bin\pdflatex.exe",
                r"/usr/bin/pdflatex",  # Linux
                r"/usr/local/bin/pdflatex",  # macOS
                r"C:\texlive\2022\bin\win32\pdflatex.exe",  # TexLive on Windows
            ]
            
            pdflatex = None
            for path in pdflatex_paths:
                try:
                    logger.debug(f"Trying pdflatex at: {path}")
                    result = subprocess.run([path, "--version"], 
                                         stdout=subprocess.PIPE, 
                                         stderr=subprocess.PIPE)
                    if result.returncode == 0:
                        pdflatex = path
                        logger.info(f"Found pdflatex at: {path}")
                        break
                except Exception as e:
                    logger.debug(f"Failed to execute {path}: {str(e)}")
            
            if not pdflatex:
                logger.error("pdflatex not found. Make sure LaTeX is installed.")
                return None
                
            # Run pdflatex with extended error reporting
            logger.debug(f"Running pdflatex with output directory: {os.path.abspath(pdf_dir)}")
            logger.debug(f"Source file: {os.path.abspath(tex_path)}")
            
            # Create directory if it doesn't exist
            os.makedirs(pdf_dir, exist_ok=True)
            
            # Run pdflatex
            process = subprocess.run(
                [pdflatex, '-interaction=nonstopmode', 
                 f'-output-directory={os.path.abspath(pdf_dir)}', 
                 os.path.abspath(tex_path)],
                capture_output=True, text=True
            )
            
            # Check if PDF was created
            if process.returncode != 0:
                logger.error("Error compiling LaTeX file:")
                logger.error(process.stderr)
                logger.error(process.stdout)  # Also log stdout for more context
                return None
            
            # Run pdflatex a second time to resolve references
            process = subprocess.run(
                [pdflatex, '-interaction=nonstopmode', 
                 f'-output-directory={os.path.abspath(pdf_dir)}', 
                 os.path.abspath(tex_path)],
                capture_output=True, text=True
            )
                
            # Check if PDF file was actually created
            expected_pdf_path = os.path.join(pdf_dir, pdf_filename)
            if os.path.exists(expected_pdf_path):
                logger.info(f"PDF generated successfully at: {expected_pdf_path}")
            else:
                logger.error(f"PDF not found at expected location: {expected_pdf_path}")
                # Check if PDF has a different name (without file_id perhaps)
                base_name = f"medical_withdrawal_{request_data.id}_{status}"
                for file in os.listdir(pdf_dir):
                    if file.startswith(base_name) and file.endswith('.pdf'):
                        expected_pdf_path = os.path.join(pdf_dir, file)
                        logger.info(f"Found PDF with different name: {expected_pdf_path}")
                        break
            
            # Clean up auxiliary files
            for ext in ['.aux', '.log', '.out']:
                aux_file = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}{ext}")
                if os.path.exists(aux_file):
                    os.remove(aux_file)
                    logger.debug(f"Removed auxiliary file: {aux_file}")
            
            # Clean up temporary tex file
            os.remove(tex_path)
            logger.debug(f"Removed temporary LaTeX file: {tex_path}")
                
            return expected_pdf_path
            
        except Exception as e:
            logger.error(f"Error running pdflatex: {str(e)}")
            return None
            
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None