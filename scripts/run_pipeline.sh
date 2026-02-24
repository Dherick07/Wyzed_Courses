#!/bin/bash
# run_pipeline.sh
# Runs both scripts in sequence inside the Docker container.
# Environment variables (set via docker-compose.yml or -e flags):
#   KOKORO_HOST  (default: host.docker.internal)
#   KOKORO_PORT  (default: 8880)

set -e

INPUT_DIR="${INPUT_DIR:-/workspace}"
KOKORO_HOST="${KOKORO_HOST:-host.docker.internal}"
KOKORO_PORT="${KOKORO_PORT:-8880}"

echo "============================================"
echo " Presentation Video Pipeline"
echo "============================================"
echo " Input dir   : $INPUT_DIR"
echo " Kokoro host : $KOKORO_HOST:$KOKORO_PORT"
echo "============================================"
echo ""

echo "=== Step 1: Generating audio files ==="
python /app/scripts/01_generate_audios.py \
  --input-dir "$INPUT_DIR" \
  --kokoro-host "$KOKORO_HOST" \
  --kokoro-port "$KOKORO_PORT"

echo ""
echo "=== Step 2: Creating video ==="
python /app/scripts/02_create_video.py \
  --input-dir "$INPUT_DIR" \
  --output-dir "$INPUT_DIR/Output"

echo ""
echo "============================================"
echo " Done! Video saved to: $INPUT_DIR/Output/output_video.mp4"
echo "============================================"
