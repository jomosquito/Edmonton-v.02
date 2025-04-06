import os
import json
import subprocess
import shutil
from datetime import datetime, date
import logging
import re

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
        # Create necessary directories with explicit absolute paths
        current_dir = os.path.abspath(os.path.dirname(__file__))
        pdf_dir = os.path.join(current_dir, 'static', 'pdfs')
        temp_dir = os.path.join(current_dir, 'static', 'temp')
        template_dir = os.path.join(current_dir, 'static', 'templates')
        
        # Create directories if they don't exist
        for directory in [pdf_dir, temp_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                logger.info(f"Created directory: {directory}")
        
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
        
        # Function to get attribute value safely with a default fallback
        def get_attr_value(obj, attr_name, default=""):
            if hasattr(obj, attr_name):
                value = getattr(obj, attr_name)
                if value is not None:
                    return value
            return default
        
        # Escape special LaTeX characters
        def latex_escape(text):
            if text is None:
                return ""
            # Escape special LaTeX characters
            chars = {'&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#', '_': '\\_', 
                    '{': '\\{', '}': '\\}', '~': '\\textasciitilde{}', '^': '\\textasciicircum{}',
                    '\\': '\\textbackslash{}'}
            text = str(text)
            for char, replacement in chars.items():
                text = text.replace(char, replacement)
            return text
        
        # Create a dictionary of replacements
        replacements = {
            "##FORMID##": str(request_data.id),
            "##STATUS##": status.upper()
        }
        
        # Replace the title
        template_content = template_content.replace("Medical/Administrative Term Withdrawal Request Form", "Student-Initiated Drop Request Form")
        template_content = template_content.replace("Medical/Administrative Term Withdrawal Form", "Student-Initiated Drop Form")
        
        # Student Information
        replacements["##FULLNAME##"] = latex_escape(request_data.student_name)
        replacements["##MYUHID##"] = latex_escape(request_data.student_id)
        
        # Remove or adapt sections that don't apply to student drop
        # We can simplify sections by replacing them with appropriate content
        template_content = template_content.replace('\\section*{1. Student Information}', '\\section*{Student Information}')
        
        # Course information - adapt for the drop request
        course_content = f"\\begin{{tabular}}{{ll}}\nCourse Title / Number: & \\textbf{{{latex_escape(request_data.course_title)}}} \\\\\n\\end{{tabular}}"
        
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
            new_section += f"\\textbf{{{latex_escape(request_data.reason)}}}\n"
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
                    signature_path = os.path.abspath(request_data.signature).replace('\\', '/')
                    signature_content += f"Signature: & \\includegraphics[width=5cm]{{{signature_path}}} \\\\\n"
                    sig_replaced = True
                    logger.debug(f"Using signature file path: {signature_path}")
                elif isinstance(request_data.signature, str) and request_data.signature.startswith('data:image'):
                    # It's a data URL, save it as an image
                    import base64
                    sig_dir = os.path.join(current_dir, 'static', 'uploads', 'signatures')
                    os.makedirs(sig_dir, exist_ok=True)
                    
                    sig_filename = f"temp_sig_{request_data.id}_{file_id}.png"
                    sig_path = os.path.join(sig_dir, sig_filename)
                    
                    try:
                        img_data = request_data.signature.split(',')[1]
                        with open(sig_path, "wb") as f:
                            f.write(base64.b64decode(img_data))
                            
                        signature_content += f"Signature: & \\includegraphics[width=5cm]{{{os.path.abspath(sig_path).replace('\\', '/')}}} \\\\\n"
                        sig_replaced = True
                        logger.debug(f"Created signature image from data URL: {sig_path}")
                    except Exception as e:
                        logger.error(f"Error processing signature data URL: {str(e)}")
                else:
                    # It's text
                    signature_content += f"Signature: & {latex_escape(request_data.signature)} \\\\\n"
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
        request_info_section_end = "##ADMIN_SIGNATURE_SECTION##"
        
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
            admin_sig_path = os.path.abspath(admin_signature).replace('\\', '/')
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
            
        template_content = template_content.replace('##ADMIN_SIGNATURE_SECTION##', admin_sig_section)
        
        # Create a temporary tex file
        tex_filename = f"student_drop_{request_data.id}_{status}_{file_id}.tex"
        tex_path = os.path.join(temp_dir, tex_filename)
        
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        logger.debug(f"Created temporary LaTeX file at: {tex_path}")
        
        # Generate PDF filename
        pdf_filename = f"student_drop_{request_data.id}_{status}_{file_id}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        # Apply all replacements to the template
        for key, value in replacements.items():
            template_content = template_content.replace(key, value)
            logger.info(f"Replaced {key} with {value}")
        
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
            
            # Run pdflatex directly in the directory of the tex file
            current_dir = os.getcwd()
            os.chdir(os.path.dirname(tex_path))
            
            pdf_output_dir = '-output-directory=' + os.path.abspath(pdf_dir).replace('\\', '/')
            
            # Run pdflatex command
            cmd = [pdflatex, '-interaction=nonstopmode', pdf_output_dir, os.path.basename(tex_path)]
            logger.info(f"Running command: {' '.join(cmd)}")
            
            process = subprocess.run(
                cmd,
                capture_output=True, 
                text=True
            )
            
            # Check if PDF was created
            if process.returncode != 0:
                logger.error("Error compiling LaTeX file:")
                logger.error(process.stderr)
                logger.error(process.stdout)  # Also log stdout for more context
                return None
            
            # Run pdflatex a second time to resolve references
            process = subprocess.run(
                cmd,
                capture_output=True, 
                text=True
            )
            
            # Change back to original directory
            os.chdir(current_dir)
                
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
        # Create necessary directories with explicit absolute paths
        current_dir = os.path.abspath(os.path.dirname(__file__))
        pdf_dir = os.path.join(current_dir, 'static', 'pdfs')
        temp_dir = os.path.join(current_dir, 'static', 'temp')
        template_dir = os.path.join(current_dir, 'static', 'templates')
        
        # Create directories if they don't exist
        for directory in [pdf_dir, temp_dir]:
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                logger.info(f"Created directory: {directory}")
        
        logger.info(f"PDF directory (absolute): {pdf_dir}")
        logger.info(f"Template directory (absolute): {template_dir}")
        
        # Status and unique identifier for the file
        status = request_data.status
        file_id = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Check if LaTeX template exists
        template_path = os.path.join(template_dir, 'medical_withdrawal_template.tex')
        logger.info(f"Looking for template at: {template_path}")
        
        if not os.path.exists(template_path):
            logger.error(f"Template not found at {template_path}")
            
            # Look for templates in various locations
            possible_locations = [
                os.path.join(current_dir, 'templates', 'medical_withdrawal_template.tex'),
                os.path.join('templates', 'medical_withdrawal_template.tex'),
                os.path.join('static', 'templates', 'medical_withdrawal_template.tex')
            ]
            
            template_found = False
            for alt_path in possible_locations:
                logger.info(f"Trying alternative template location: {alt_path}")
                if os.path.exists(alt_path):
                    template_path = alt_path
                    template_found = True
                    logger.info(f"Found template at alternative location: {alt_path}")
                    break
            
            if not template_found:
                logger.error("Template not found in any location. Creating a basic template.")
                # Create a basic template as a fallback
                basic_template = r"""
\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{graphicx}
\begin{document}
\begin{center}
  \textbf{\Large Medical/Administrative Term Withdrawal Request Form}\\[0.2cm]
  \textbf{Form ID: ##FORMID##}\\[0.2cm]
  \textbf{Status: ##STATUS##}
\end{center}
\section*{Student Information}
Name: ##FULLNAME##\\
ID: ##MYUHID##\\
\section*{Request Details}
Status: ##STATUS##\\
\end{document}
"""
                template_path = os.path.join(temp_dir, 'fallback_template.tex')
                with open(template_path, 'w', encoding='utf-8') as f:
                    f.write(basic_template)
                logger.info(f"Created fallback template at: {template_path}")
            
        # Read the LaTeX template
        with open(template_path, 'r', encoding='utf-8') as file:
            template_content = file.read()
            logger.info(f"Successfully read template ({len(template_content)} bytes)")
        
        # Function to get attribute value safely with a default fallback
        def get_attr_value(obj, attr_name, default=""):
            if hasattr(obj, attr_name):
                value = getattr(obj, attr_name)
                if value is not None:
                    return value
            return default
        
        # Escape special LaTeX characters
        def latex_escape(text):
            if text is None:
                return ""
            # Escape special LaTeX characters
            chars = {'&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#', '_': '\\_', 
                    '{': '\\{', '}': '\\}', '~': '\\textasciitilde{}', '^': '\\textasciicircum{}',
                    '\\': '\\textbackslash{}'}
            text = str(text)
            for char, replacement in chars.items():
                text = text.replace(char, replacement)
            return text
        
        # Replace the "For Office Use Only" section
        if "For Office Use Only" in template_content:
            logger.info("Removing 'For Office Use Only' section")
            office_use_section_start = "\\vspace{2cm}"
            office_use_section_end = "\\label{LastPage}"
            
            start_idx = template_content.find(office_use_section_start)
            end_idx = template_content.find(office_use_section_end)
            
            if start_idx != -1 and end_idx != -1:
                # Keep just the LastPage label
                template_content = template_content[:start_idx] + "\\label{LastPage}" + template_content[end_idx + len("\\label{LastPage}"):]
        
        # Replace placeholders with actual values
        replacements = {}
        
        # Basic information
        replacements["##FORMID##"] = str(get_attr_value(request_data, 'id'))
        replacements["##STATUS##"] = status.upper()
        replacements["##FULLNAME##"] = latex_escape(f"{get_attr_value(request_data, 'first_name')} {get_attr_value(request_data, 'middle_name', '')} {get_attr_value(request_data, 'last_name')}".strip())
        replacements["##MYUHID##"] = latex_escape(get_attr_value(request_data, 'myuh_id'))
        replacements["##COLLEGE##"] = latex_escape(get_attr_value(request_data, 'college'))
        replacements["##DEGREE##"] = latex_escape(get_attr_value(request_data, 'plan_degree'))
        replacements["##PHONE##"] = latex_escape(get_attr_value(request_data, 'phone'))
        
        # Address information
        replacements["##ADDRESS##"] = latex_escape(get_attr_value(request_data, 'address'))
        replacements["##CITY##"] = latex_escape(get_attr_value(request_data, 'city'))
        replacements["##STATE##"] = latex_escape(get_attr_value(request_data, 'state'))
        replacements["##ZIP##"] = latex_escape(get_attr_value(request_data, 'zip_code'))
        
        # Email - check if user attribute exists
        if hasattr(request_data, 'user') and hasattr(request_data.user, 'email_'):
            replacements["##EMAIL##"] = latex_escape(request_data.user.email_ or '')
        else:
            replacements["##EMAIL##"] = ''
        
        # Term information
        replacements["##TERM_YEAR##"] = latex_escape(get_attr_value(request_data, 'term_year'))
        
        # Last date attended
        if hasattr(request_data, 'last_date') and request_data.last_date:
            if isinstance(request_data.last_date, (datetime, date)):
                replacements["##LAST_DATE##"] = request_data.last_date.strftime('%B %d, %Y')
            else:
                replacements["##LAST_DATE##"] = str(request_data.last_date)
        else:
            replacements["##LAST_DATE##"] = ''
        
        # Reason
        replacements["##REASON_TYPE##"] = latex_escape(get_attr_value(request_data, 'reason_type'))
        replacements["##DETAILS##"] = latex_escape(get_attr_value(request_data, 'details'))
        
        # Additional information
        replacements["##FINANCIAL_ASSISTANCE##"] = 'Yes' if get_attr_value(request_data, 'financial_assistance', False) else 'No'
        replacements["##HEALTH_INSURANCE##"] = 'Yes' if get_attr_value(request_data, 'health_insurance', False) else 'No'
        replacements["##CAMPUS_HOUSING##"] = 'Yes' if get_attr_value(request_data, 'campus_housing', False) else 'No'
        replacements["##VISA_STATUS##"] = 'Yes' if get_attr_value(request_data, 'visa_status', False) else 'No'
        replacements["##GI_BILL##"] = 'Yes' if get_attr_value(request_data, 'gi_bill', False) else 'No'
        
        # Initial
        replacements["##INITIAL##"] = latex_escape(get_attr_value(request_data, 'initial'))
        
        # Signature date
        if hasattr(request_data, 'signature_date') and request_data.signature_date:
            if isinstance(request_data.signature_date, (datetime, date)):
                replacements["##SIGNATURE_DATE##"] = request_data.signature_date.strftime('%B %d, %Y')
            else:
                replacements["##SIGNATURE_DATE##"] = str(request_data.signature_date)
        else:
            replacements["##SIGNATURE_DATE##"] = datetime.utcnow().strftime('%B %d, %Y')
        
        # Created date
        if hasattr(request_data, 'created_at') and request_data.created_at:
            if isinstance(request_data.created_at, (datetime, date)):
                replacements["##CREATED_DATE##"] = request_data.created_at.strftime('%B %d, %Y')
            else:
                replacements["##CREATED_DATE##"] = str(request_data.created_at)
        else:
            replacements["##CREATED_DATE##"] = datetime.utcnow().strftime('%B %d, %Y')
        
        # Course listings
        courses_content = ""
        if hasattr(request_data, 'courses') and request_data.courses:
            try:
                courses = json.loads(request_data.courses)
                for course in courses:
                    if isinstance(course, dict) and 'subject' in course and 'number' in course and 'section' in course:
                        courses_content += f"{latex_escape(course['subject'])} & {latex_escape(course['number'])} & {latex_escape(course['section'])} \\\\\n"
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"Error parsing courses: {str(e)}")
                courses_content = "Error parsing course data"
        replacements["##COURSES##"] = courses_content
        
        
        # Admin signature
        admin_sig_section = ""
        if admin_signature and status == 'approved':
            admin_sig_path = os.path.abspath(admin_signature).replace('\\', '/')
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
        replacements["##ADMIN_SIGNATURE_SECTION##"] = admin_sig_section
        
        # Handle signature - this is complex
        temp_signature_path = None
        sig_command = "\\includegraphics[width=5cm]{SIGNATURE_PATH}"
        
        # First check if we have a signature
        if hasattr(request_data, 'signature') and request_data.signature:
            if isinstance(request_data.signature, str) and request_data.signature.startswith('data:image'):
                # It's a data URL, save it as an image
                import base64
                sig_dir = os.path.join(current_dir, 'static', 'uploads', 'signatures')
                os.makedirs(sig_dir, exist_ok=True)
                
                sig_filename = f"sig_{request_data.id}_{file_id}.png"
                temp_signature_path = os.path.join(sig_dir, sig_filename)
                
                try:
                    img_data = request_data.signature.split(',')[1]
                    with open(temp_signature_path, "wb") as f:
                        f.write(base64.b64decode(img_data))
                    logger.info(f"Created signature image from data URL at: {temp_signature_path}")
                    
                    # Use absolute path for LaTeX with forward slashes
                    sig_path_for_latex = os.path.abspath(temp_signature_path).replace('\\', '/')
                    template_content = template_content.replace(sig_command, f'\\includegraphics[width=5cm]{{{sig_path_for_latex}}}')
                    logger.info(f"Set signature path to: {sig_path_for_latex}")
                except Exception as e:
                    logger.error(f"Error processing signature data URL: {str(e)}")
                    template_content = template_content.replace(sig_command, "Signature unavailable")
            
            # Check if it's a file path
            elif isinstance(request_data.signature, str) and os.path.exists(request_data.signature):
                # It's a file path that exists
                signature_path = os.path.abspath(request_data.signature).replace('\\', '/')
                template_content = template_content.replace(sig_command, f'\\includegraphics[width=5cm]{{{signature_path}}}')
                logger.info(f"Using existing signature file: {signature_path}")
            
            # Otherwise use text signature or placeholder
            else:
                sig_text = request_data.signature
                if isinstance(sig_text, str):
                    # For text signatures, replace the image with text
                    template_content = template_content.replace(sig_command, latex_escape(sig_text))
                    logger.info(f"Using text for signature: {sig_text}")
                else:
                    template_content = template_content.replace(sig_command, "Signature unavailable")
                    logger.info("Signature not in usable format, using placeholder")
        else:
            template_content = template_content.replace(sig_command, "No signature provided")
            logger.info("No signature provided, using placeholder")
        
        # Apply all replacements
        for key, value in replacements.items():
            template_content = template_content.replace(key, value)
            logger.info(f"Replaced {key} with {value}")
        
        # Create a temporary tex file with absolute path
        tex_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.tex"
        tex_path = os.path.join(temp_dir, tex_filename)
        
        with open(tex_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        
        logger.info(f"Created temporary LaTeX file at: {tex_path}")
        
        # Debug: Save a copy of the template for inspection
        debug_template_path = os.path.join(temp_dir, f"debug_template_{file_id}.tex")
        with open(debug_template_path, 'w', encoding='utf-8') as f:
            f.write(template_content)
        logger.info(f"Saved debug template at: {debug_template_path}")
        
        # Generate PDF filename with absolute path
        pdf_filename = f"medical_withdrawal_{request_data.id}_{status}_{file_id}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)
        
        # Compile the LaTeX file to create a PDF
        try:
            # Try to find pdflatex in various locations
            logger.info("Searching for pdflatex executable...")
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
                    logger.info(f"Trying pdflatex at: {path}")
                    result = subprocess.run([path, "--version"], 
                                         stdout=subprocess.PIPE, 
                                         stderr=subprocess.PIPE)
                    if result.returncode == 0:
                        pdflatex = path
                        logger.info(f"Found pdflatex at: {path}")
                        break
                except Exception as e:
                    logger.info(f"Failed to execute {path}: {str(e)}")
            
            if not pdflatex:
                logger.error("pdflatex not found. Make sure LaTeX is installed.")
                return None
                
            # Run pdflatex with extended error reporting
            logger.info(f"Running pdflatex with output directory: {pdf_dir}")
            logger.info(f"Source file: {tex_path}")
            
            # Create directory if it doesn't exist
            os.makedirs(pdf_dir, exist_ok=True)
            
            # Run pdflatex directly in the directory of the tex file
            current_dir = os.getcwd()
            os.chdir(os.path.dirname(tex_path))
            
            pdf_output_dir = '-output-directory=' + os.path.abspath(pdf_dir).replace('\\', '/')
            
            # Run pdflatex command
            cmd = [pdflatex, '-interaction=nonstopmode', pdf_output_dir, os.path.basename(tex_path)]
            logger.info(f"Running command: {' '.join(cmd)}")
            
            process = subprocess.run(
                cmd,
                capture_output=True, 
                text=True
            )
            
            # Log the output for debugging
            logger.info(f"pdflatex stdout: {process.stdout[:500]}...")
            if process.stderr:
                logger.error(f"pdflatex stderr: {process.stderr}")
            
            # Change back to original directory
            os.chdir(current_dir)
            
            # Check if PDF was created
            if process.returncode != 0:
                logger.error(f"Error compiling LaTeX file (exit code {process.returncode})")
                return None
            
            # Run pdflatex a second time to resolve references (using the same approach)
            os.chdir(os.path.dirname(tex_path))
            process = subprocess.run(
                cmd,
                capture_output=True, 
                text=True
            )
            os.chdir(current_dir)
                
            # Check if PDF file was actually created
            if os.path.exists(pdf_path):
                logger.info(f"PDF generated successfully at: {pdf_path}")
                pdf_size = os.path.getsize(pdf_path)
                logger.info(f"PDF file size: {pdf_size} bytes")
                
                # Return the PDF path
                return pdf_path
            else:
                logger.error(f"PDF not found at expected location: {pdf_path}")
                # Look for the PDF in various locations
                potential_pdf_locations = [
                    os.path.join(os.path.dirname(tex_path), pdf_filename),
                    os.path.join(pdf_dir, os.path.splitext(os.path.basename(tex_path))[0] + '.pdf'),
                    os.path.join(current_dir, pdf_filename)
                ]
                
                for potential_location in potential_pdf_locations:
                    if os.path.exists(potential_location):
                        logger.info(f"Found PDF at alternative location: {potential_location}")
                        # Copy it to the expected location
                        shutil.copy(potential_location, pdf_path)
                        logger.info(f"Copied PDF to expected location: {pdf_path}")
                        return pdf_path
                else:
                    # If we didn't find the PDF anywhere, look for any PDF with similar name
                    base_name = f"medical_withdrawal_{request_data.id}_{status}"
                    for file in os.listdir(pdf_dir):
                        if file.startswith(base_name) and file.endswith('.pdf'):
                            found_pdf_path = os.path.join(pdf_dir, file)
                            logger.info(f"Found PDF with similar name: {found_pdf_path}")
                            return found_pdf_path
                    
                    # Try one more time with simplified approach
                    try:
                        # Run pdflatex in the current directory
                        os.chdir(temp_dir)
                        simplified_cmd = [pdflatex, os.path.basename(tex_path)]
                        logger.info(f"Final attempt with simplified command: {' '.join(simplified_cmd)}")
                        
                        process = subprocess.run(
                            simplified_cmd,
                            capture_output=True,
                            text=True
                        )
                        
                        # Look for the PDF in the current directory
                        output_pdf = os.path.splitext(os.path.basename(tex_path))[0] + '.pdf'
                        if os.path.exists(output_pdf):
                            # Copy it to the expected location
                            shutil.copy(output_pdf, pdf_path)
                            logger.info(f"Created PDF with simplified command at: {pdf_path}")
                            
                            # Return to the original directory
                            os.chdir(current_dir)
                            return pdf_path
                        else:
                            os.chdir(current_dir)
                            logger.error("PDF still not found after simplified approach")
                            return None
                    except Exception as e:
                        os.chdir(current_dir)
                        logger.error(f"Error in simplified PDF generation attempt: {str(e)}")
                        return None
            
        except Exception as e:
            logger.error(f"Error running pdflatex: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    except Exception as e:
        logger.error(f"Error generating PDF: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None