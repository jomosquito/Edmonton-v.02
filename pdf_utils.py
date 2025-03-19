import os
import json
import subprocess
import shutil
from datetime import datetime

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
        template_dir = os.path.join('templates')
        os.makedirs(pdf_dir, exist_ok=True)
        os.makedirs(temp_dir, exist_ok=True)
        
        # Status and unique identifier for the file
        status = request_data.status
        file_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Check if LaTeX template exists
        template_path = os.path.join(template_dir, 'medical_withdrawal_template.tex')
        if not os.path.exists(template_path):
            print(f"Template not found at {template_path}")
            return None
            
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
        
        # Use absolute path for signature
        signature_path = os.path.abspath(request_data.signature) if hasattr(request_data, 'signature') and request_data.signature else None
        if signature_path and os.path.exists(signature_path):
            template_content = template_content.replace('SIGNATURE_PATH', signature_path)
        else:
            # No signature available
            template_content = template_content.replace('\\includegraphics[width=5cm]{SIGNATURE_PATH}', 'No signature provided')
        
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
            
        template_content = template_content.replace('ADMIN_SIGNATURE_SECTION', admin_sig_section)
        
        # Create a temporary tex file
        tex_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.tex"
        tex_path = os.path.join(temp_dir, tex_filename)
        
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        # Generate PDF filename
        pdf_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        # Compile the LaTeX file to create a PDF
        try:
            # Try to find pdflatex
            pdflatex_paths = [
                "pdflatex",  # Try system PATH first
                r"C:\Program Files\MiKTeX\miktex\bin\x64\pdflatex.exe",
                r"C:\Program Files (x86)\MiKTeX\miktex\bin\pdflatex.exe",
            ]
            
            pdflatex = None
            for path in pdflatex_paths:
                try:
                    result = subprocess.run([path, "--version"], 
                                           stdout=subprocess.PIPE, 
                                           stderr=subprocess.PIPE)
                    if result.returncode == 0:
                        pdflatex = path
                        break
                except:
                    continue
                
            if not pdflatex:
                print("pdflatex not found. Make sure LaTeX is installed.")
                return None
                
            # Run pdflatex
            process = subprocess.run(
                [pdflatex, '-interaction=nonstopmode', 
                 f'-output-directory={os.path.abspath(pdf_dir)}', 
                 os.path.abspath(tex_path)],
                capture_output=True, text=True
            )
            
            # Check if PDF was created
            if process.returncode != 0:
                print("Error compiling LaTeX file:")
                print(process.stderr)
                return None
                
            # Clean up auxiliary files
            for ext in ['.aux', '.log', '.out']:
                aux_file = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}{ext}")
                if os.path.exists(aux_file):
                    os.remove(aux_file)
            
            # Clean up temporary tex file
            os.remove(tex_path)
                
            print(f"PDF generated successfully: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            print(f"Error running pdflatex: {str(e)}")
            return None
            
    except Exception as e:
        print(f"Error generating PDF: {str(e)}")
        return None