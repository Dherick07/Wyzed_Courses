#!/bin/bash
# run_pipeline.sh
# Runs both pipeline scripts in sequence inside the Docker container.
#
# EXPLICIT MODE (used by the web UI):
#   Set these environment variables before calling this script:
#     NARRATION_SCRIPT  — full container path to the .md narration file
#     PPTX_FILE         — full container path to the .pptx presentation
#     OUTPUT_PATH       — full container path for the output .mp4
#   The Audios/ folder is automatically placed next to the PPTX file.
#
# LEGACY MODE (backward compatibility — auto-detects files in INPUT_DIR):
#   INPUT_DIR  (default: /workspace)
#
# TTS config (both modes):
#   SPEED       (default: 1.0) — TTS speech speed
#   MODEL_DIR   (default: /app/models) — directory containing Kokoro ONNX model files
#
# Video config (both modes):
#   PRE_DELAY   (default: 1.5)  — seconds of silence before narration on each slide

set -e

SPEED="${SPEED:-1.0}"
MODEL_DIR="${MODEL_DIR:-/app/models}"
PRE_DELAY="${PRE_DELAY:-1.5}"

if [ -n "$NARRATION_SCRIPT" ] && [ -n "$PPTX_FILE" ] && [ -n "$OUTPUT_PATH" ]; then
    # -----------------------------------------------------------------
    # Explicit mode: all three paths were provided by the web UI
    # -----------------------------------------------------------------
    AUDIOS_DIR="$(dirname "$PPTX_FILE")/Audios"

    echo "============================================"
    echo " Presentation Video Pipeline"
    echo "============================================"
    echo " Narration script : $NARRATION_SCRIPT"
    echo " Presentation     : $PPTX_FILE"
    echo " Output video     : $OUTPUT_PATH"
    echo " Audios dir       : $AUDIOS_DIR"
    echo " TTS speed        : $SPEED"
    echo " Pre-delay        : ${PRE_DELAY}s"
    echo "============================================"
    echo ""

    echo "=== Step 1: Generating audio files ==="
    python /app/scripts/01_generate_audios.py \
      --md-file     "$NARRATION_SCRIPT" \
      --audios-dir  "$AUDIOS_DIR" \
      --model-dir   "$MODEL_DIR" \
      --speed       "$SPEED"

    echo ""
    echo "=== Step 2: Creating video ==="
    python /app/scripts/02_create_video.py \
      --pptx-file   "$PPTX_FILE" \
      --audios-dir  "$AUDIOS_DIR" \
      --output-path "$OUTPUT_PATH" \
      --pre-delay   "$PRE_DELAY"

else
    # -----------------------------------------------------------------
    # Legacy mode: auto-detect files inside INPUT_DIR
    # -----------------------------------------------------------------
    INPUT_DIR="${INPUT_DIR:-/workspace}"

    echo "============================================"
    echo " Presentation Video Pipeline"
    echo "============================================"
    echo " Input dir   : $INPUT_DIR"
    echo " TTS speed   : $SPEED"
    echo " Pre-delay   : ${PRE_DELAY}s"
    echo "============================================"
    echo ""

    echo "=== Step 1: Generating audio files ==="
    python /app/scripts/01_generate_audios.py \
      --input-dir   "$INPUT_DIR" \
      --model-dir   "$MODEL_DIR" \
      --speed       "$SPEED"

    echo ""
    echo "=== Step 2: Creating video ==="
    python /app/scripts/02_create_video.py \
      --input-dir   "$INPUT_DIR" \
      --output-dir  "$INPUT_DIR/Output" \
      --pre-delay   "$PRE_DELAY"
fi

echo ""
echo "============================================"
echo " Pipeline complete!"
echo "============================================"
