.PHONY: all clean

# Define the target PDF directory
PDF_DIR = static/pdfs
TEMP_DIR = static/temp

# Check if directories exist, create if needed
$(shell mkdir -p $(PDF_DIR) $(TEMP_DIR))

# Define the rule to compile a LaTeX file to PDF
%.pdf: %.tex
    pdflatex -interaction=nonstopmode -output-directory=$(dir $@) $<
    pdflatex -interaction=nonstopmode -output-directory=$(dir $@) $<

# Define a rule to create a PDF from a request ID
pdf-from-request: 
    @echo "Generating PDF from request ID $(REQUEST_ID)"
    python -c "from pdf_utils import generate_medical_withdrawal_pdf; from main import MedicalWithdrawalRequest, db; request = MedicalWithdrawalRequest.query.get($(REQUEST_ID)); generate_medical_withdrawal_pdf(request)"

# More thorough clean command
clean-all:
    @echo "Cleaning all LaTeX auxiliary files..."
    @find $(PDF_DIR) -name "*.aux" -o -name "*.log" -o -name "*.out" -type f -delete
    @find $(TEMP_DIR) -type f -delete
    @echo "Cleanup complete."

# Scheduled cleanup (can be called from cron/scheduled task)
scheduled-cleanup:
    @echo "Running scheduled cleanup of auxiliary files..."
    python clean_latex_files.py
    @echo "Scheduled cleanup complete."