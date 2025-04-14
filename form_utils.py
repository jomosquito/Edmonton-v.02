import os
import uuid
import subprocess
from datetime import datetime

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def return_choice(choices, keyword):
    if choices and keyword in choices:
        return "yes"
    return "no"

def generate_ferpa(data, form_folder, upload_folder):
    # Define template paths
    templates_folder = os.path.join('static', 'form-templates')
    os.makedirs(templates_folder, exist_ok=True)

    ferpa_template_path = os.path.join(templates_folder, 'ferpa.tex')

    # Create template file if it doesn't exist
    if not os.path.exists(ferpa_template_path):
        with open(ferpa_template_path, "w") as file:
            file.write(FERPA_TEMPLATE)

    # Generate unique ID for the PDF
    unique_id = str(uuid.uuid4())

    # Unique file paths
    tex_file_path = os.path.join(form_folder, f"ferpa_form_{unique_id}.tex")
    pdf_file_path = f"ferpa_form_{unique_id}.pdf"

    # Read the LaTeX template and replace placeholders
    with open(ferpa_template_path, "r") as file:
        latex_content = file.read()

    for key, value in data.items():
        latex_content = latex_content.replace(f"{{{{{key}}}}}", str(value))

    # Save the modified LaTeX file
    with open(tex_file_path, "w") as file:
        file.write(latex_content)

    # Ensure output directory exists
    os.makedirs(form_folder, exist_ok=True)

    # Compile
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", form_folder, tex_file_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Return path to PDF
    return pdf_file_path

def generate_ssn_name(data, form_folder, upload_folder):
    # Define template paths
    templates_folder = os.path.join('static', 'form-templates')
    os.makedirs(templates_folder, exist_ok=True)

    name_ssn_template_path = os.path.join(templates_folder, 'name_ssn_change.tex')

    # Create template file if it doesn't exist
    if not os.path.exists(name_ssn_template_path):
        with open(name_ssn_template_path, "w") as file:
            file.write(NAME_SSN_TEMPLATE)

    # Generate unique ID for the PDF
    unique_id = str(uuid.uuid4())

    # Unique file paths
    tex_file_path = os.path.join(form_folder, f"name_form_{unique_id}.tex")
    pdf_file_path = f"name_form_{unique_id}.pdf"

    # Read the LaTeX template and replace placeholders
    with open(name_ssn_template_path, "r") as file:
        latex_content = file.read()

    for key, value in data.items():
        latex_content = latex_content.replace(f"{{{{{key}}}}}", str(value))

    # Save the modified LaTeX file
    with open(tex_file_path, "w") as file:
        file.write(latex_content)

    # Ensure output directory exists
    os.makedirs(form_folder, exist_ok=True)

    # Compile
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-output-directory", form_folder, tex_file_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Return the generated PDF
    return pdf_file_path

# LaTeX Templates
FERPA_TEMPLATE = r"""
\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{array}
\usepackage{graphicx}
\usepackage{ifthen}
\usepackage{amssymb}
\usepackage{pifont}

% Define CheckedBox command
\newcommand{\CheckedBox}[1]{%
  \ifthenelse{\equal{#1}{yes}}{$\boxtimes$}{$\square$}%
}

\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\fancyhead[R]{Form No. OGC-SF-2006-02}

\setlength{\parindent}{0pt}

\begin{document}

\begin{center}
\textbf{AUTHORIZATION TO RELEASE EDUCATIONAL RECORDS\\
Family Educational Rights and Privacy Act of 1974 as Amended (FERPA)}
\end{center}

\vspace{1em}
I: {{NAME}} hereby voluntarily authorize officials in the University of Houston - {{CAMPUS}} identified below to disclose personally identifiable
information from my educational records. (Please check the box or boxes that apply)

\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{OPT_REGISTRAR}}} Office of the University Registrar
	\item \CheckedBox{{{OPT_AID}}} Scholarships and Financial Aid
	\item \CheckedBox{{{OPT_FINANCIAL}}} Student Financial Services
	\item \CheckedBox{{{OPT_UNDERGRAD}}} Undergraduate Scholars \& US (formally USD)
	\item \CheckedBox{{{OPT_ADVANCEMENT}}} University Advancement
	\item \CheckedBox{{{OPT_DEAN}}} Dean of Students Office
	\item \CheckedBox{{{OPT_OTHER_OFFICIALS}}} Other: {{OTHEROFFICIALS}}
\end{itemize}

Specifically, I authorize disclosure of the following information or category of information: (Please check the box or
boxes that apply)
\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{OPT_ACADEMIC_INFO}}} Academic Advising Profile/Information
	\item \CheckedBox{{{OPT_UNIVERSITY_RECORDS}}} All University Records
	\item \CheckedBox{{{OPT_ACADEMIC_RECORDS}}} Academic Records
	\item \CheckedBox{{{OPT_BILLING}}} Billing/Financial Aid
	\item \CheckedBox{{{OPT_DISCIPLINARY}}} Disciplinary
	\item \CheckedBox{{{OPT_TRANSCRIPTS}}} Grades/Transcripts
	\item \CheckedBox{{{OPT_HOUSING}}} Housing
	\item \CheckedBox{{{OPT_PHOTOS}}} Photos
	\item \CheckedBox{{{OPT_SCHOLARSHIP}}} Scholarship and/or Honors
	\item \CheckedBox{{{OPT_OTHER_INFO}}} Other: {{OTHERINFO}}
\end{itemize}

\vspace{0.5em}
This information may be released to: {{RELEASE}} for the purpose of {{PURPOSE}}\\
\begin{center}
(Print Name(s) of Individual(s) To Whom University May Disclose Information)\\
\vspace{0.5em}
\ifthenelse{\equal{{{ADDITIONALS}}}{}}{}{{{ADDITIONALS}} \\ }
\underline{\hspace{10cm}}\\
(List Additional Individuals if Necessary)
\end{center}

\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{OPT_FAMILY}}} Family
	\item \CheckedBox{{{OPT_INSTITUTION}}} Educational Institution
	\item \CheckedBox{{{OPT_HONOR}}} Honor or Award
	\item \CheckedBox{{{OPT_EMPLOYER}}} Employer/Prospective Employer
	\item \CheckedBox{{{OPT_PUBLIC}}} Public or Media of Scholarship
	\item \CheckedBox{{{OPT_OTHER_RELEASE}}} Other: {{OTHERRELEASE}}
\end{itemize}

\vspace{0.5em}
I designate a password to obtain information via the phone: {{PASSWORD}}. The password should not contain more than ten (10) letters. You must provide the password to the individuals or agencies listed above. The University will not release information to the caller if the caller does not have the password. A new form must be completed to change your password.

\vspace{0.5em}
This is to attest that I am the student signing this form. I understand the information may be released orally or in the form of copies of written records, as preferred by the requester. This authorization will remain in effect from the date it is executed until revoked by me, in writing, and delivered to Department(s) identified above.

\vspace{2em}
\noindent\begin{tabular}{@{}p{0.5\textwidth}p{0.5\textwidth}@{}}
{{NAME}} & {{PEOPLESOFT}} \\
\cline{1-1}\cline{2-2}
Student Name (please print) & PeopleSoft I.D. Number \\
& \\
\includegraphics[width=5cm]{{{SIGNATURE}}} & {{DATE}} \\
\cline{1-1}\cline{2-2}
Student Signature & Date \\
\end{tabular}

\vspace{1em}
\textbf{Please Retain a Copy for your Records}\\
\textbf{Original may be submitted to Registrar's Office}\\
\textbf{Degree auditors or academic advisors}\\
\textbf{OGC-S-2006-02-Form}\\
Page 1 of 1 \hfill \textit{Note: Modification of this Form requires approval of OGC}

\end{document}
"""

NAME_SSN_TEMPLATE = r"""
\documentclass[12pt]{article}
\usepackage[margin=1in]{geometry}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{array}
\usepackage{graphicx}
\usepackage{ifthen}
\usepackage{amssymb}
\usepackage{pifont}

% Define CheckedBox command
\newcommand{\CheckedBox}[1]{%
  \ifthenelse{\equal{#1}{yes}}{$\boxtimes$}{$\square$}%
}

\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}

\setlength{\parindent}{0pt}

\begin{document}

\begin{center}
\textbf{Name and/or Social Security Number Change}\\
University of Houston | Office of the University Registrar\\
Houston, Texas 77204-2027 | (713) 743-1010, option 7
\end{center}

\vspace{1em}
\noindent\begin{tabular}{@{}p{0.5\textwidth}p{0.5\textwidth}@{}}
Student Name (as listed on university record) & myUH ID Number\\
{{NAME}} & {{PEOPLESOFT}}\\
\end{tabular}

\vspace{1em}
\noindent\textbf{*What are you requesting to add or update?}\\
\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{EDIT_NAME}}} Update Name (Complete Section A)
	\item \CheckedBox{{{EDIT_SSN}}} Update/Add Social Security Number (Complete Section B)
\end{itemize}

\vspace{1em}
\noindent\textbf{Section A: Student Name Change}\\
The University of Houston record of your name was originally taken from your application for admission and may be changed if:
\begin{enumerate}
\item You have married, remarried, or divorced (a copy of marriage license or portion of divorce decree indicating new name must be provided)
\item You have changed your name by court order (a copy of the court order must be provided)
\item Your legal name is listed incorrectly and satisfactory evidence exists for its correction (driver license, state ID, birth certificate, valid passport, etc., must be provided)
\end{enumerate}

\noindent\textbf{NOTE:} A request to omit a first or middle name or to reverse the order of the first and middle names cannot be honored unless accompanied by appropriate documentation. All documents must also be submitted with a valid government-issued photo ID (such as a driver license, passport, or military ID).

\vspace{1em}
\noindent Please print and complete the following information:\\
I request that my legal name be changed and reflected on University of Houston records as listed below:

\vspace{0.5em}
\noindent\begin{tabular}{@{}p{0.15\textwidth}p{0.35\textwidth}|p{0.15\textwidth}p{0.35\textwidth}@{}}
FROM: & & TO: & \\
First name & \makebox[4cm][l]{\textbf{{{FN_OLD}}}} \underline{\hspace{4cm}} & First name & \makebox[4cm][l]{\textbf{{{FN_NEW}}}} \underline{\hspace{4cm}} \\
Middle name & \makebox[4cm][l]{\textbf{{{MN_OLD}}}} \underline{\hspace{4cm}} & Middle name & \makebox[4cm][l]{\textbf{{{MN_NEW}}}} \underline{\hspace{4cm}} \\
Last name & \makebox[4cm][l]{\textbf{{{LN_OLD}}}} \underline{\hspace{4cm}} & Last name & \makebox[4cm][l]{\textbf{{{LN_NEW}}}} \underline{\hspace{4cm}} \\
Suffix & \makebox[4cm][l]{\textbf{{{SUF_OLD}}}} \underline{\hspace{4cm}} & Suffix & \makebox[4cm][l]{\textbf{{{SUF_NEW}}}} \underline{\hspace{4cm}} \\
\end{tabular}

\vspace{1em}
Check reason for name change request:
\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{OPT_MARITAL}}} Marriage/Divorce
	\item \CheckedBox{{{OPT_COURT}}} Court Order
	\item \CheckedBox{{{OPT_ERROR_NAME}}} Correction of Error
\end{itemize}

\vspace{1em}
\noindent\textbf{Section B: Student Social Security Number Change}\\
The University of Houston record of your Social Security Number was originally taken from your application for admission and may be changed only if the student has obtained a new social security number or an error was made. In either case, the student must provide a copy of the Social Security Card. The Social Security card must include the student's signature and must be submitted with a valid government-issued photo ID (such as a driver license, passport, or military ID).

\vspace{1em}
\noindent Please print and complete the following information: I request that my Social Security Number be changed and reflected on University of Houston records as listed below:

\vspace{0.5em}
\noindent FROM: {{SSN_OLD}}

\vspace{0.5em}
\noindent TO: {{SSN_NEW}}

\vspace{0.5em}
\begin{itemize}[leftmargin=0.7cm]
	\item \CheckedBox{{{OPT_ERROR_SSN}}} Marriage/Divorce
	\item \CheckedBox{{{OPT_ADD_SSN}}} Court Order
\end{itemize}

\vspace{1em}
\noindent I authorize the University of Houston Main Campus to make the updates/changes to my student record as requested above.

\vspace{1em}
\noindent\textbf{*SIGNATURE (REQUIRED)} \includegraphics[width=5cm]{{{SIGNATURE}}} Date {{DATE}}

\vspace{1em}
\footnotesize{*State law requires that you be informed of the following: (1) with few exceptions, you are entitled on request to be informed about the information the University collects about you by use of this form; (2) under sections 552.021 and 552.023 of the Government Code, you are entitled to receive and review the information; and (3) under section 559.004 of the Government Code, you are entitled to have the University correct information about you that is incorrect.}

\end{document}
"""