FROM python:3.11-slim

# System dependencies:
#   libreoffice  — converts PPTX to PDF (headless)
#   ffmpeg       — video encoding engine (called directly via subprocess)
#   poppler-utils — required by pdf2image to convert PDF pages to PNG
#   espeak-ng    — phonemizer backend for Kokoro TTS
RUN apt-get update && apt-get install -y \
    libreoffice \
    ffmpeg \
    poppler-utils \
    espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy pre-downloaded Kokoro TTS model files from local models/ directory.
# One-time setup: download before first build —
#   wget -P models/ https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx
#   wget -P models/ https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
COPY models/ /app/models/

# Copy scripts into the image
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/run_pipeline.sh

# Working directory is the mounted project volume
WORKDIR /workspace

EXPOSE 8080

# Start the web UI — open http://localhost:8080 in your browser to run the pipeline.
CMD ["python", "/app/scripts/web_ui.py"]
