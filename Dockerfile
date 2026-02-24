FROM python:3.11-slim

# System dependencies:
#   libreoffice  — converts PPTX to PDF (headless)
#   ffmpeg       — required by moviepy for video encoding
#   poppler-utils — required by pdf2image to convert PDF pages to PNG
RUN apt-get update && apt-get install -y \
    libreoffice \
    ffmpeg \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy scripts into the image
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/run_pipeline.sh

# Working directory is the mounted project volume
WORKDIR /workspace

CMD ["bash", "/app/scripts/run_pipeline.sh"]
