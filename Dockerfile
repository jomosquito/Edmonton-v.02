FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-fonts-recommended \
    texlive-latex-extra \
    build-essential \
    libpq-dev \
    postgresql-client \
    gcc \
    python3-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    sed -i 's/psycopg2==2.9.10/psycopg2-binary==2.9.10/g' requirements.txt && \
    sed -i 's/pi==0.1.2/#pi==0.1.2/g' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir psycopg2-binary==2.9.10 && \
    pip install --no-cache-dir -r requirements.txt --ignore-installed

# Copy the application code
COPY . .

# Create necessary directories
RUN mkdir -p static/pdfs static/temp static/uploads/documentation static/uploads/signatures instance

# Expose the port
EXPOSE 5000

# Create placeholder config if needed
RUN if [ ! -f config.py ]; then \
    echo "# Configuration file\nclient_id = 'your_client_id'\nclient_secret = 'your_client_secret'\nSECRET_KEY = 'your_secret_key'" > config.py; \
    fi

# Simple startup script to avoid entrypoint conflicts
RUN echo '#!/bin/bash\npython migrations.py\npython -c "from main import app; app.run(host=\"0.0.0.0\", port=5000)"' > start.sh && \
    chmod +x start.sh

# Command to run the app
CMD ["./start.sh"]