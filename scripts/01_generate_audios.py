#!/usr/bin/env python3
"""
01_generate_audios.py

Parses a narration Markdown file (## Slide N format) and generates one WAV
audio file per slide using the embedded Kokoro ONNX TTS model.

Optimizations:
  - Uses Kokoro.from_session() with tuned ONNX Runtime SessionOptions
    (intra_op threading, graph optimization, memory arena)
  - Processes slides concurrently via ProcessPoolExecutor (2 workers)

Usage:
    python 01_generate_audios.py --input-dir /workspace
    python 01_generate_audios.py --input-dir /workspace --speed 1.2

Environment:
    ONNX_THREADS  — total CPU threads for ONNX Runtime (0 = auto-detect, default)
"""

import argparse
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import onnxruntime as rt
import soundfile as sf
from kokoro_onnx import Kokoro


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    text = re.sub(r'^---+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def parse_narration_slides(md_path: Path) -> dict[int, str]:
    """
    Parse narration markdown into {slide_number: narration_text}.

    Sections are delimited by '## Slide N' headers. Parsing stops at
    '## Fact-Check Summary' or '*End of narration scripts*'.
    """
    content = md_path.read_text(encoding='utf-8')

    stop_markers = [r'## Fact-Check Summary', r'\*End of narration scripts\*']
    for marker in stop_markers:
        match = re.search(marker, content)
        if match:
            content = content[:match.start()]

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
        slides[slide_num] = clean_markdown(content[start:end])

    return slides


# ---------------------------------------------------------------------------
# ONNX-optimized Kokoro loader
# ---------------------------------------------------------------------------

def create_optimized_kokoro(model_path: str, voices_path: str, num_threads: int) -> Kokoro:
    """
    Create a Kokoro instance with an optimized ONNX Runtime session.

    Uses from_session() to pass a pre-configured InferenceSession with:
      - intra_op_num_threads: parallelism within matrix operations
      - inter_op_num_threads: parallelism across independent graph nodes
      - ORT_ENABLE_ALL: operator fusion, constant folding, etc.
      - enable_cpu_mem_arena: pre-allocated memory pool
    """
    sess_options = rt.SessionOptions()
    sess_options.intra_op_num_threads = num_threads
    sess_options.inter_op_num_threads = 2
    sess_options.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.enable_cpu_mem_arena = True

    session = rt.InferenceSession(
        model_path,
        providers=["CPUExecutionProvider"],
        sess_options=sess_options,
    )
    return Kokoro.from_session(session, voices_path)


# ---------------------------------------------------------------------------
# Worker for concurrent slide generation
# ---------------------------------------------------------------------------

def _generate_one_slide(args: tuple) -> tuple[int, int, float]:
    """
    Worker function for ProcessPoolExecutor.

    Each worker creates its own ONNX session (process-safe) and generates
    audio for a single slide.  Returns (slide_num, file_size_kb, elapsed_s).
    """
    slide_num, text, output_path_str, model_path, voices_path, speed, threads_per_worker = args

    t0 = time.monotonic()
    kokoro = create_optimized_kokoro(model_path, voices_path, threads_per_worker)
    samples, sample_rate = kokoro.create(text, voice="af_bella", speed=speed, lang="en-us")
    sf.write(output_path_str, samples, sample_rate)
    elapsed = time.monotonic() - t0

    size_kb = Path(output_path_str).stat().st_size // 1024
    return slide_num, size_kb, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate per-slide WAV audio via Kokoro ONNX TTS"
    )
    parser.add_argument("--input-dir", default="/workspace",
                        help="Directory containing the .md narration file (auto-detect mode)")
    parser.add_argument("--md-file", default=None,
                        help="Explicit path to the .md narration file")
    parser.add_argument("--audios-dir", default=None,
                        help="Explicit path for saving WAV files")
    parser.add_argument("--model-dir", default="/app/models",
                        help="Directory containing Kokoro ONNX model files")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="TTS speech speed (default: 1.0)")
    args = parser.parse_args()

    # --- Resolve paths ---------------------------------------------------
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

    model_dir = Path(args.model_dir)
    model_path = str(model_dir / "kokoro-v1.0.int8.onnx")
    voices_path = str(model_dir / "voices-v1.0.bin")

    if not Path(model_path).exists():
        print(f"ERROR: Model file not found: {model_path}")
        sys.exit(1)
    if not Path(voices_path).exists():
        print(f"ERROR: Voices file not found: {voices_path}")
        sys.exit(1)

    # --- Threading configuration -----------------------------------------
    total_threads = int(os.environ.get("ONNX_THREADS", 0)) or (os.cpu_count() or 4)
    num_workers = min(2, total_threads)  # cap at 2 parallel workers
    threads_per_worker = max(1, total_threads // num_workers)

    print(f"CPU threads available : {os.cpu_count()}")
    print(f"ONNX threads total   : {total_threads}")
    print(f"Parallel workers     : {num_workers}")
    print(f"Threads per worker   : {threads_per_worker}")
    print()

    # --- Parse narration -------------------------------------------------
    print(f"Narration file: {md_file.name}")
    slides = parse_narration_slides(md_file)
    total = len(slides)
    print(f"Found {total} slide(s) in narration script.\n")

    # Filter out empty slides
    tasks = []
    for slide_num in sorted(slides.keys()):
        text = slides[slide_num]
        if not text:
            print(f"  WARNING: Slide {slide_num} has no narration text. Skipping.")
            continue
        output_path = audios_dir / f"slide_{slide_num:02d}.wav"
        tasks.append((
            slide_num, text, str(output_path),
            model_path, voices_path, args.speed, threads_per_worker,
        ))

    # --- Generate audio (concurrent) -------------------------------------
    overall_start = time.monotonic()

    if num_workers <= 1:
        # Single-worker path: avoid multiprocessing overhead
        print("Loading Kokoro TTS model (optimized session)...")
        kokoro = create_optimized_kokoro(model_path, voices_path, total_threads)
        print("Model loaded.\n")

        for slide_num, text, output_path_str, *_ in tasks:
            t0 = time.monotonic()
            print(f"[{slide_num}/{total}] Generating audio for Slide {slide_num}...")
            samples, sr = kokoro.create(text, voice="af_bella", speed=args.speed, lang="en-us")
            sf.write(output_path_str, samples, sr)
            elapsed = time.monotonic() - t0
            size_kb = Path(output_path_str).stat().st_size // 1024
            print(f"  Saved: {Path(output_path_str).name} ({size_kb} KB, {elapsed:.1f}s)")
    else:
        # Multi-worker path: process slides in parallel
        print(f"Generating audio with {num_workers} parallel workers...\n")
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_map = {
                executor.submit(_generate_one_slide, task): task[0]
                for task in tasks
            }
            for future in as_completed(future_map):
                slide_num = future_map[future]
                try:
                    sn, size_kb, elapsed = future.result()
                    print(f"  [Slide {sn:>2}] slide_{sn:02d}.wav ({size_kb} KB, {elapsed:.1f}s)")
                except Exception as exc:
                    print(f"  ERROR on Slide {slide_num}: {exc}")

    overall_elapsed = time.monotonic() - overall_start
    print(f"\nDone. {len(tasks)} audio file(s) saved to: {audios_dir}")
    print(f"Total audio generation time: {overall_elapsed:.1f}s ({overall_elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
