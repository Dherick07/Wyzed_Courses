#!/usr/bin/env python3
"""
02_create_video.py

Converts a PowerPoint file to slide images, pairs each slide image with its
matching WAV audio, and exports a single MP4 video. Slide transitions happen
exactly when the audio for each slide ends.

Usage:
    python 02_create_video.py --input-dir /workspace
    python 02_create_video.py --input-dir /workspace --output-dir /workspace/Output
"""

import argparse
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from pdf2image import convert_from_path
from moviepy.editor import AudioFileClip, ImageClip, concatenate_videoclips
from PIL import Image


def find_file(directory: Path, extension: str) -> Path:
    """Auto-detect the first file with the given extension in directory."""
    matches = list(directory.glob(f"*{extension}"))
    if not matches:
        print(f"ERROR: No {extension} file found in {directory}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"WARNING: Multiple {extension} files found. Using: {matches[0].name}")
    return matches[0]


def pptx_to_images(pptx_path: Path, work_dir: Path) -> list[Path]:
    """
    Convert PPTX to per-slide PNG images via LibreOffice (PPTX→PDF) + pdf2image (PDF→PNGs).
    Returns list of PNG paths ordered by slide number.
    """
    print("Converting PPTX to PDF via LibreOffice...")
    result = subprocess.run(
        [
            "libreoffice",
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(work_dir),
            str(pptx_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: LibreOffice conversion failed:\n{result.stderr}")
        sys.exit(1)

    pdf_path = work_dir / (pptx_path.stem + ".pdf")
    if not pdf_path.exists():
        print(f"ERROR: Expected PDF not found at {pdf_path}")
        sys.exit(1)

    print("Converting PDF pages to PNG images...")
    pil_images = convert_from_path(str(pdf_path), dpi=150)

    png_paths = []
    for i, img in enumerate(pil_images, start=1):
        png_path = work_dir / f"slide_{i:02d}.png"
        img.save(str(png_path), "PNG")
        png_paths.append(png_path)

    print(f"  {len(png_paths)} slide image(s) created.")
    return png_paths


def get_wav_duration(wav_path: Path) -> float:
    """Return duration of a WAV file in seconds using stdlib wave module."""
    with wave.open(str(wav_path), 'rb') as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)


def build_video_clips(slide_images: list[Path], audios_dir: Path) -> list:
    """
    For each slide image, pair it with the matching WAV audio and build a
    moviepy clip whose duration equals the audio length.
    """
    clips = []
    total = len(slide_images)

    for i, img_path in enumerate(slide_images, start=1):
        audio_path = audios_dir / f"slide_{i:02d}.wav"

        if not audio_path.exists():
            print(f"  WARNING: Audio not found for Slide {i} ({audio_path.name}). Skipping slide.")
            continue

        duration = get_wav_duration(audio_path)
        print(f"  Slide {i:02d}/{total}: {img_path.name} + {audio_path.name} ({duration:.1f}s)")

        audio_clip = AudioFileClip(str(audio_path))
        image_clip = (
            ImageClip(str(img_path))
            .set_duration(duration)
            .set_audio(audio_clip)
        )
        clips.append(image_clip)

    return clips


def main():
    parser = argparse.ArgumentParser(description="Combine PPTX slides and WAV audio into an MP4 video")
    parser.add_argument("--input-dir", default="/workspace", help="Directory containing the .pptx file and Audios/ folder")
    parser.add_argument("--output-dir", default=None, help="Directory for the output MP4 (default: <input-dir>/Output)")
    parser.add_argument("--fps", type=int, default=24, help="Video frame rate (default: 24)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    audios_dir = input_dir / "Audios"
    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir / "Output"
    output_dir.mkdir(exist_ok=True)

    if not audios_dir.exists():
        print(f"ERROR: Audios/ directory not found at {audios_dir}")
        print("  Run 01_generate_audios.py first.")
        sys.exit(1)

    pptx_file = find_file(input_dir, ".pptx")
    print(f"Presentation: {pptx_file.name}")
    print(f"Audios dir:   {audios_dir}")
    print(f"Output dir:   {output_dir}\n")

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        # Step 1: PPTX → PNG images
        slide_images = pptx_to_images(pptx_file, work_dir)

        # Step 2: Build per-slide video clips
        print("\nBuilding video clips...")
        clips = build_video_clips(slide_images, audios_dir)

        if not clips:
            print("ERROR: No video clips were created. Check that audio files exist in Audios/.")
            sys.exit(1)

        # Step 3: Concatenate and export
        print(f"\nConcatenating {len(clips)} clip(s) and exporting to MP4...")
        final_video = concatenate_videoclips(clips, method="compose")
        output_path = output_dir / "output_video.mp4"

        final_video.write_videofile(
            str(output_path),
            fps=args.fps,
            codec="libx264",
            audio_codec="aac",
            logger="bar",
        )

        print(f"\nDone. Video saved to: {output_path}")


if __name__ == "__main__":
    main()
