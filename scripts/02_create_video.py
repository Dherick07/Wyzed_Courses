#!/usr/bin/env python3
"""
02_create_video.py

Converts a PowerPoint file to slide images, pairs each slide image with its
matching WAV audio, and exports a single MP4 video. Slide transitions happen
exactly when the audio for each slide ends.

Uses direct ffmpeg subprocess calls for fast encoding with -tune stillimage.

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
    Convert PPTX to per-slide PNG images via LibreOffice (PPTX->PDF) + pdf2image (PDF->PNGs).
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


def encode_slide_segment(
    img_path: Path, audio_path: Path, output_path: Path, fps: int = 24
) -> Path:
    """
    Encode a single slide image + WAV audio into an MP4 segment using ffmpeg.
    The segment duration matches the audio length via -shortest.
    """
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", "1",
        "-i", str(img_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-crf", "23",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg failed for {img_path.name}:\n{result.stderr}")
        sys.exit(1)
    return output_path


def concatenate_segments(segment_paths: list[Path], output_path: Path) -> None:
    """
    Concatenate pre-encoded MP4 segments into a single video using the
    ffmpeg concat demuxer with stream copy (no re-encoding).
    """
    concat_list = segment_paths[0].parent / "concat_list.txt"
    with open(concat_list, "w") as f:
        for seg in segment_paths:
            f.write(f"file '{seg}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg concat failed:\n{result.stderr}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Combine PPTX slides and WAV audio into an MP4 video")
    parser.add_argument("--input-dir", default="/workspace", help="Directory containing the .pptx file and Audios/ folder (auto-detect mode)")
    parser.add_argument("--pptx-file", default=None, help="Explicit path to the .pptx file (overrides --input-dir auto-detection)")
    parser.add_argument("--audios-dir", default=None, help="Explicit path to the Audios/ directory (overrides <input-dir>/Audios/)")
    parser.add_argument("--output-path", default=None, help="Full output path for the .mp4 file (overrides --output-dir)")
    parser.add_argument("--output-dir", default=None, help="Directory for the output MP4 (default: <input-dir>/Output)")
    parser.add_argument("--fps", type=int, default=24, help="Video frame rate (default: 24)")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()

    if args.pptx_file:
        pptx_file = Path(args.pptx_file).resolve()
    else:
        pptx_file = find_file(input_dir, ".pptx")

    if args.audios_dir:
        audios_dir = Path(args.audios_dir).resolve()
    else:
        audios_dir = input_dir / "Audios"

    if args.output_path:
        output_path = Path(args.output_path).resolve()
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir / "Output"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output_video.mp4"

    if not audios_dir.exists():
        print(f"ERROR: Audios/ directory not found at {audios_dir}")
        print("  Run 01_generate_audios.py first.")
        sys.exit(1)

    print(f"Presentation: {pptx_file.name}")
    print(f"Audios dir:   {audios_dir}")
    print(f"Output path:  {output_path}\n")

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)

        # Step 1: PPTX -> PNG images
        slide_images = pptx_to_images(pptx_file, work_dir)

        # Step 2: Encode per-slide segments
        print("\nEncoding slide segments...")
        total = len(slide_images)
        segment_paths = []

        for i, img_path in enumerate(slide_images, start=1):
            audio_path = audios_dir / f"slide_{i:02d}.wav"

            if not audio_path.exists():
                print(f"  WARNING: Audio not found for Slide {i} ({audio_path.name}). Skipping slide.")
                continue

            duration = get_wav_duration(audio_path)
            print(f"  Slide {i:02d}/{total}: {img_path.name} + {audio_path.name} ({duration:.1f}s)")

            segment_path = work_dir / f"segment_{i:02d}.mp4"
            encode_slide_segment(img_path, audio_path, segment_path, fps=args.fps)
            segment_paths.append(segment_path)

        if not segment_paths:
            print("ERROR: No segments were created. Check that audio files exist in Audios/.")
            sys.exit(1)

        # Step 3: Concatenate segments (stream copy — no re-encoding)
        print(f"\nConcatenating {len(segment_paths)} segment(s) into final video...")
        concatenate_segments(segment_paths, output_path)

        print(f"\nDone. Video saved to: {output_path}")


if __name__ == "__main__":
    main()
