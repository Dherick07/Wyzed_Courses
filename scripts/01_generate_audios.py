#!/usr/bin/env python3
"""
01_generate_audios.py

Parses a narration Markdown file (## Slide N format) and generates one WAV
audio file per slide using a local Kokoro FastAPI instance.

Usage:
    python 01_generate_audios.py --input-dir /workspace
    python 01_generate_audios.py --input-dir /workspace --kokoro-host localhost --kokoro-port 8880
"""

import argparse
import os
import re
import sys
import requests
from pathlib import Path


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


def generate_audio(text: str, output_path: Path, host: str, port: int) -> None:
    """Call Kokoro FastAPI and save WAV audio to output_path."""
    url = f"http://{host}:{port}/v1/audio/speech"
    payload = {
        "model": "kokoro",
        "voice": "af_bella",
        "input": text,
        "speed": 1.0,
        "response_format": "wav",
    }

    try:
        response = requests.post(url, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to Kokoro at {url}")
        print("  Make sure Kokoro FastAPI Docker container is running.")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: Kokoro API returned an error: {e}")
        print(f"  Response: {response.text[:500]}")
        sys.exit(1)

    output_path.write_bytes(response.content)


def main():
    parser = argparse.ArgumentParser(description="Generate per-slide WAV audio via Kokoro FastAPI")
    parser.add_argument("--input-dir", default="/workspace", help="Directory containing the .md narration file")
    parser.add_argument("--kokoro-host", default="host.docker.internal", help="Kokoro FastAPI hostname")
    parser.add_argument("--kokoro-port", type=int, default=8880, help="Kokoro FastAPI port")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    audios_dir = input_dir / "Audios"
    audios_dir.mkdir(exist_ok=True)

    md_file = find_file(input_dir, ".md")
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

        generate_audio(text, output_path, args.kokoro_host, args.kokoro_port)
        size_kb = output_path.stat().st_size // 1024
        print(f"  Saved: {output_path.name} ({size_kb} KB)")

    print(f"\nDone. {total} audio file(s) saved to: {audios_dir}")


if __name__ == "__main__":
    main()
