#!/usr/bin/env python3
"""
01_generate_audios.py

Parses a narration Markdown file (## Slide N format) and generates one WAV
audio file per slide using the embedded Kokoro ONNX TTS model.

Usage:
    python 01_generate_audios.py --input-dir /workspace
    python 01_generate_audios.py --input-dir /workspace --speed 1.2
"""

import argparse
import re
import sys
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro


def find_file(directory: Path, extension: str) -> Path:
    """Auto-detect the first file with the given extension in directory."""
    matches = list(directory.glob(f"*{extension}"))
    if not matches:
        print(f"ERROR: No {extension} file found in {directory}")
        sys.exit(1)
    if len(matches) > 1:
        print(f"WARNING: Multiple {extension} files found. Using: {matches[0].name}")
    return matches[0]


def clean_markdown(text: str) -> str:
    """Strip markdown formatting symbols from text before sending to TTS."""
    # Remove horizontal rules
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    # Remove blockquote markers
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    # Remove inline code
    text = re.sub(r'`[^`]+`', '', text)
    # Remove heading markers (## or ###)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Collapse multiple blank lines into one
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def parse_narration_slides(md_path: Path) -> dict[int, str]:
    """
    Parse narration markdown file into a dict of {slide_number: narration_text}.

    Sections are delimited by '## Slide N' headers. Parsing stops at
    '## Fact-Check Summary' or '*End of narration scripts*'.
    """
    content = md_path.read_text(encoding='utf-8')

    # Stop at fact-check/end markers
    stop_markers = [
        r'## Fact-Check Summary',
        r'\*End of narration scripts\*',
    ]
    for marker in stop_markers:
        match = re.search(marker, content)
        if match:
            content = content[:match.start()]

    # Split on slide headers: ## Slide N — ...
    slide_pattern = re.compile(r'^## Slide (\d+)', re.MULTILINE)
    matches = list(slide_pattern.finditer(content))

    if not matches:
        print("ERROR: No '## Slide N' sections found in the narration file.")
        sys.exit(1)

    slides = {}
    for i, match in enumerate(matches):
        slide_num = int(match.group(1))
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        raw_text = content[start:end]
        slides[slide_num] = clean_markdown(raw_text)

    return slides


def main():
    parser = argparse.ArgumentParser(description="Generate per-slide WAV audio via Kokoro ONNX TTS")
    parser.add_argument("--input-dir", default="/workspace", help="Directory containing the .md narration file (auto-detect mode)")
    parser.add_argument("--md-file", default=None, help="Explicit path to the .md narration file (overrides --input-dir auto-detection)")
    parser.add_argument("--audios-dir", default=None, help="Explicit path for saving WAV files (overrides <input-dir>/Audios/)")
    parser.add_argument("--model-dir", default="/app/models", help="Directory containing Kokoro ONNX model files")
    parser.add_argument("--speed", type=float, default=1.0, help="TTS speech speed (default: 1.0)")
    args = parser.parse_args()

    if args.md_file:
        md_file = Path(args.md_file).resolve()
    else:
        input_dir = Path(args.input_dir).resolve()
        md_file = find_file(input_dir, ".md")

    if args.audios_dir:
        audios_dir = Path(args.audios_dir).resolve()
    else:
        input_dir = Path(args.input_dir).resolve()
        audios_dir = input_dir / "Audios"

    audios_dir.mkdir(parents=True, exist_ok=True)

    # Load Kokoro ONNX model
    model_dir = Path(args.model_dir)
    model_path = model_dir / "kokoro-v1.0.int8.onnx"
    voices_path = model_dir / "voices-v1.0.bin"

    if not model_path.exists():
        print(f"ERROR: Model file not found: {model_path}")
        sys.exit(1)
    if not voices_path.exists():
        print(f"ERROR: Voices file not found: {voices_path}")
        sys.exit(1)

    print("Loading Kokoro TTS model...")
    kokoro = Kokoro(str(model_path), str(voices_path))
    print("Model loaded.\n")

    print(f"Narration file: {md_file.name}")

    slides = parse_narration_slides(md_file)
    total = len(slides)
    print(f"Found {total} slide(s) in narration script.\n")

    for slide_num in sorted(slides.keys()):
        text = slides[slide_num]
        output_path = audios_dir / f"slide_{slide_num:02d}.wav"
        print(f"[{slide_num}/{total}] Generating audio for Slide {slide_num}...")

        if not text:
            print(f"  WARNING: Slide {slide_num} has no narration text. Skipping.")
            continue

        samples, sample_rate = kokoro.create(
            text, voice="af_bella", speed=args.speed, lang="en-us"
        )
        sf.write(str(output_path), samples, sample_rate)

        size_kb = output_path.stat().st_size // 1024
        print(f"  Saved: {output_path.name} ({size_kb} KB)")

    print(f"\nDone. {total} audio file(s) saved to: {audios_dir}")


if __name__ == "__main__":
    main()
