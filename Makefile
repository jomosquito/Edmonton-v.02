# Makefile for generating PDFs from LaTeX templates

# Directories
TEMPLATES_DIR = templates
TEMP_DIR = static/temp
PDF_DIR = static/pdfs
LOGO_DIR = static/templates

# LaTeX command
LATEX = pdflatex
LATEX_OPTS = -interaction=nonstopmode

# Rules
.PHONY: all clean setup create_logo

# Default rule
all: setup create_logo

# Rule to compile a specific LaTeX file to PDF
%.pdf: %.tex
    $(LATEX) $(LATEX_OPTS) -output-directory=$(PDF_DIR) $<

# Setup directory structure
setup:
    @mkdir -p $(TEMP_DIR)
    @mkdir -p $(PDF_DIR)
    @mkdir -p $(LOGO_DIR)
    @echo "Directory structure created"

# Create UH logo
create_logo:
    @python create_logo.py

# Generate Medical Withdrawal PDF
medical_withdrawal:
    @cp $(TEMPLATES_DIR)/medical_withdrawal_template.tex $(TEMP_DIR)/temp_medical_withdrawal.tex
    $(LATEX) $(LATEX_OPTS) -output-directory=$(PDF_DIR) $(TEMP_DIR)/temp_medical_withdrawal.tex
    @echo "Medical Withdrawal PDF generated"

# Clean temporary files
clean:
    @rm -f $(PDF_DIR)/*.aux $(PDF_DIR)/*.log $(PDF_DIR)/*.out
    @rm -f $(TEMP_DIR)/temp_*.tex
    @echo "Temporary files cleaned"