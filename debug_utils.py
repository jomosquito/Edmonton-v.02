def generate_ferpa(data, form_folder, upload_folder):
    try:
        # Import debugging functions
        from debug_utils import debug_pdf_generation, ensure_directory_exists
    except ImportError:
        # Define them locally if import fails
        def debug_pdf_generation(function_name, data, output_path, error=None):
            import logging
            logging.basicConfig(level=logging.DEBUG, filename='pdf_generation.log')
            logger = logging.getLogger('pdf_debug')
            logger.debug(f"Debug for {function_name}: Path={output_path}, Error={error}")

        def ensure_directory_exists(directory_path):
            if not os.path.exists(directory_path):
                os.makedirs(directory_path, exist_ok=True)

    try:
        # Define template paths - ensure these are absolute paths
        current_dir = os.path.abspath(os.getcwd())
        templates_folder = os.path.join(current_dir, 'static', 'form-templates')
        ensure_directory_exists(templates_folder)

        ferpa_template_path = os.path.join(templates_folder, 'ferpa.tex')

        # Create template file if it doesn't exist
        if not os.path.exists(ferpa_template_path):
            with open(ferpa_template_path, "w") as file:
                file.write(FERPA_TEMPLATE)

        # Generate unique ID for the PDF
        unique_id = str(uuid.uuid4())

        # Create absolute paths for the output files
        full_form_folder = os.path.join(current_dir, form_folder)
        ensure_directory_exists(full_form_folder)

        tex_file_path = os.path.join(full_form_folder, f"ferpa_form_{unique_id}.tex")
        pdf_file_path = f"ferpa_form_{unique_id}.pdf"
        full_pdf_path = os.path.join(full_form_folder, pdf_file_path)

        # Read the LaTeX template and replace placeholders
        with open(ferpa_template_path, "r") as file:
            latex_content = file.read()

        for key, value in data.items():
            latex_content = latex_content.replace(f"{{{{{key}}}}}", str(value))

        # Save the modified LaTeX file
        with open(tex_file_path, "w") as file:
            file.write(latex_content)

        # Compile - use full paths and capture output for debugging
        process = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", f"-output-directory={full_form_folder}", tex_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Check if compilation was successful
        if process.returncode != 0:
            debug_pdf_generation("generate_ferpa", data, full_pdf_path,
                                f"pdflatex error: {process.stderr}")

            # Try running pdflatex a second time
            process = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", f"-output-directory={full_form_folder}", tex_file_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

        # Verify the PDF was created
        if os.path.exists(full_pdf_path):
            debug_pdf_generation("generate_ferpa", data, full_pdf_path, "PDF generated successfully")
        else:
            debug_pdf_generation("generate_ferpa", data, full_pdf_path, "PDF file not found after compilation")

        # Return path to PDF
        return pdf_file_path

    except Exception as e:
        debug_pdf_generation("generate_ferpa", data, None, str(e))
        import traceback
        debug_pdf_generation("generate_ferpa", data, None, traceback.format_exc())
        return None