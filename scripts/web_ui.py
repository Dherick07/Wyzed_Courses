#!/usr/bin/env python3
"""
web_ui.py

Browser-based UI for the Presentation Video Generator pipeline.

Users upload a narration script (.md / .txt) and a presentation (.pptx / .ppt / .odp),
then the pipeline generates TTS audio and combines everything into an MP4 video
that can be downloaded directly from the browser.

Start: python /app/scripts/web_ui.py
Open:  http://localhost:8080
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from flask import (
    Flask,
    jsonify,
    request,
    Response,
    send_file,
    stream_with_context,
)

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SESSIONS_DIR = Path("/workspace/_sessions")
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB per file

NARRATION_EXTS = {".md", ".txt"}
PRESENTATION_EXTS = {".pptx", ".ppt", ".odp"}

# ---------------------------------------------------------------------------
# HTML template (self-contained — no external CDN dependencies)
# ---------------------------------------------------------------------------
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Presentation Video Generator</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      font-family: system-ui, -apple-system, sans-serif;
      background: #f0f4f8;
      min-height: 100vh;
      padding: 40px 20px;
      color: #2d3748;
    }

    .card {
      max-width: 700px;
      margin: 0 auto;
      background: #fff;
      border-radius: 14px;
      padding: 40px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08);
    }

    .header { margin-bottom: 32px; }
    .header h1 { font-size: 22px; font-weight: 700; color: #1a202c; margin-bottom: 6px; }
    .header p  { font-size: 14px; color: #718096; line-height: 1.5; }

    .field { margin-bottom: 22px; }

    label {
      display: block;
      font-size: 12px;
      font-weight: 700;
      color: #4a5568;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      margin-bottom: 6px;
    }

    /* Upload zones */
    .upload-zone {
      border: 2px dashed #cbd5e0;
      border-radius: 10px;
      padding: 24px 18px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s;
      position: relative;
    }
    .upload-zone:hover {
      border-color: #667eea;
      background: #f7faff;
    }
    .upload-zone.selected {
      border-style: solid;
      border-color: #667eea;
      background: #eef2ff;
    }
    .upload-zone.invalid {
      border-color: #e53e3e;
      background: #fff5f5;
    }
    .upload-zone input[type="file"] {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
    }
    .upload-icon {
      font-size: 28px;
      margin-bottom: 6px;
      color: #a0aec0;
      pointer-events: none;
    }
    .upload-zone.selected .upload-icon { color: #667eea; }
    .upload-prompt {
      font-size: 14px;
      color: #718096;
      pointer-events: none;
    }
    .upload-zone.selected .upload-prompt { color: #4c51bf; font-weight: 600; }
    .upload-file-info {
      display: none;
      font-size: 12px;
      color: #667eea;
      margin-top: 4px;
      font-family: "SFMono-Regular", "Consolas", monospace;
      pointer-events: none;
    }
    .upload-zone.selected .upload-file-info { display: block; }

    .hint       { font-size: 11px; color: #a0aec0; margin-top: 6px; }
    .field-error{ font-size: 12px; color: #e53e3e; margin-top: 5px; display: none; font-weight: 500; }

    .btn {
      width: 100%;
      padding: 13px;
      background: #667eea;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      transition: background 0.15s, transform 0.08s;
      margin-top: 4px;
      letter-spacing: 0.2px;
    }
    .btn:hover:not(:disabled) { background: #5a67d8; }
    .btn:active:not(:disabled){ transform: scale(0.99); }
    .btn:disabled { background: #a0aec0; cursor: not-allowed; }

    /* Log output */
    .log-section { margin-top: 28px; display: none; }
    .log-label   { font-size: 12px; font-weight: 700; color: #4a5568; text-transform: uppercase; letter-spacing: 0.6px; margin-bottom: 8px; }
    .log-box {
      background: #1a202c;
      color: #a0f0b0;
      font-family: "SFMono-Regular", "Consolas", monospace;
      font-size: 12px;
      line-height: 1.6;
      padding: 16px;
      border-radius: 8px;
      height: 320px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }

    /* Result banners */
    .banner {
      padding: 14px 18px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 600;
      margin-top: 18px;
      display: none;
      line-height: 1.5;
    }
    .banner.success { background: #c6f6d5; color: #22543d; border: 1px solid #9ae6b4; }
    .banner.failure { background: #fed7d7; color: #742a2a; border: 1px solid #feb2b2; }

    /* Download button */
    .download-section { margin-top: 16px; display: none; text-align: center; }
    .download-btn {
      display: inline-block;
      padding: 14px 36px;
      background: #38a169;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 15px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      transition: background 0.15s, transform 0.08s;
      letter-spacing: 0.2px;
    }
    .download-btn:hover { background: #2f855a; }
    .download-btn:active { transform: scale(0.98); }
    .download-btn svg {
      vertical-align: middle;
      margin-right: 8px;
    }

    /* Spinner */
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255,255,255,0.4);
      border-top-color: #fff;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: middle;
      margin-right: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>Presentation Video Generator</h1>
      <p>Upload your narration script and presentation, then click
         <strong>Generate Video</strong> to create an MP4.</p>
    </div>

    <form id="pipeline-form" novalidate>

      <div class="field">
        <label>Narration Script</label>
        <div class="upload-zone" id="zone-narration">
          <input type="file" id="file-narration" accept=".md,.txt" />
          <div class="upload-icon">&#128196;</div>
          <div class="upload-prompt">Click to choose file</div>
          <div class="upload-file-info" id="info-narration"></div>
        </div>
        <div class="hint">Accepted: .md, .txt &mdash; max 20 MB</div>
        <div class="field-error" id="narration-error"></div>
      </div>

      <div class="field">
        <label>Presentation</label>
        <div class="upload-zone" id="zone-presentation">
          <input type="file" id="file-presentation" accept=".pptx,.ppt,.odp" />
          <div class="upload-icon">&#128202;</div>
          <div class="upload-prompt">Click to choose file</div>
          <div class="upload-file-info" id="info-presentation"></div>
        </div>
        <div class="hint">Accepted: .pptx, .ppt, .odp &mdash; max 20 MB</div>
        <div class="field-error" id="presentation-error"></div>
      </div>

      <button type="submit" class="btn" id="submit-btn">Generate Video</button>
    </form>

    <div class="log-section" id="log-section">
      <div class="log-label">Pipeline Output</div>
      <div class="log-box" id="log-box"></div>
    </div>

    <div class="banner success" id="success-banner"></div>
    <div class="banner failure" id="failure-banner"></div>

    <div class="download-section" id="download-section">
      <a class="download-btn" id="download-btn" href="#" download>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 1v10M8 11L4 7M8 11l4-4" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 14h12" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>
        Download Video
      </a>
    </div>
  </div>

  <script>
    /* ------------------------------------------------------------------ */
    /* DOM references                                                      */
    /* ------------------------------------------------------------------ */
    const form            = document.getElementById('pipeline-form');
    const submitBtn       = document.getElementById('submit-btn');
    const logSection      = document.getElementById('log-section');
    const logBox          = document.getElementById('log-box');
    const successBanner   = document.getElementById('success-banner');
    const failureBanner   = document.getElementById('failure-banner');
    const downloadSection = document.getElementById('download-section');
    const downloadBtn     = document.getElementById('download-btn');

    const fileNarration    = document.getElementById('file-narration');
    const filePres         = document.getElementById('file-presentation');
    const zoneNarration    = document.getElementById('zone-narration');
    const zonePres         = document.getElementById('zone-presentation');
    const infoNarration    = document.getElementById('info-narration');
    const infoPres         = document.getElementById('info-presentation');

    const NARRATION_EXTS   = ['.md', '.txt'];
    const PRESENTATION_EXTS= ['.pptx', '.ppt', '.odp'];
    const MAX_SIZE         = 20 * 1024 * 1024; // 20 MB

    /* ------------------------------------------------------------------ */
    /* Helpers                                                             */
    /* ------------------------------------------------------------------ */
    function ext(name) { return (name.lastIndexOf('.') >= 0 ? name.slice(name.lastIndexOf('.')) : '').toLowerCase(); }

    function humanSize(bytes) {
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    function showFieldError(id, msg) {
      const el = document.getElementById(id);
      el.textContent = msg;
      el.style.display = 'block';
    }

    function clearAll() {
      ['narration-error', 'presentation-error'].forEach(id => {
        const el = document.getElementById(id);
        el.textContent = '';
        el.style.display = 'none';
      });
      zoneNarration.classList.remove('invalid');
      zonePres.classList.remove('invalid');
      successBanner.style.display = 'none';
      failureBanner.style.display = 'none';
      downloadSection.style.display = 'none';
    }

    /* ------------------------------------------------------------------ */
    /* File-change handlers — update zone appearance                       */
    /* ------------------------------------------------------------------ */
    function onFileChange(input, zone, infoEl) {
      if (input.files.length) {
        const f = input.files[0];
        zone.classList.add('selected');
        zone.classList.remove('invalid');
        infoEl.textContent = f.name + '  (' + humanSize(f.size) + ')';
      } else {
        zone.classList.remove('selected');
        infoEl.textContent = '';
      }
    }
    fileNarration.addEventListener('change', () => onFileChange(fileNarration, zoneNarration, infoNarration));
    filePres.addEventListener('change',      () => onFileChange(filePres, zonePres, infoPres));

    /* ------------------------------------------------------------------ */
    /* Form submit                                                         */
    /* ------------------------------------------------------------------ */
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearAll();

      /* ---------- client-side validation ---------- */
      let ok = true;

      if (!fileNarration.files.length) {
        showFieldError('narration-error', 'Please select a narration script file.');
        zoneNarration.classList.add('invalid');
        ok = false;
      } else {
        const f = fileNarration.files[0];
        if (!NARRATION_EXTS.includes(ext(f.name))) {
          showFieldError('narration-error', 'Unsupported format. Accepted: ' + NARRATION_EXTS.join(', '));
          zoneNarration.classList.add('invalid');
          ok = false;
        } else if (f.size > MAX_SIZE) {
          showFieldError('narration-error', 'File too large. Maximum size is 20 MB.');
          zoneNarration.classList.add('invalid');
          ok = false;
        }
      }

      if (!filePres.files.length) {
        showFieldError('presentation-error', 'Please select a presentation file.');
        zonePres.classList.add('invalid');
        ok = false;
      } else {
        const f = filePres.files[0];
        if (!PRESENTATION_EXTS.includes(ext(f.name))) {
          showFieldError('presentation-error', 'Unsupported format. Accepted: ' + PRESENTATION_EXTS.join(', '));
          zonePres.classList.add('invalid');
          ok = false;
        } else if (f.size > MAX_SIZE) {
          showFieldError('presentation-error', 'File too large. Maximum size is 20 MB.');
          zonePres.classList.add('invalid');
          ok = false;
        }
      }

      if (!ok) return;

      /* ---------- upload files ---------- */
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span>Uploading\u2026';

      const fd = new FormData();
      fd.append('narration', fileNarration.files[0]);
      fd.append('presentation', filePres.files[0]);

      let uploadResult;
      try {
        const res = await fetch('/upload', { method: 'POST', body: fd });
        uploadResult = await res.json();
      } catch (err) {
        failureBanner.textContent = 'Upload failed. Is the container running?';
        failureBanner.style.display = 'block';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        return;
      }

      if (!uploadResult.ok) {
        (uploadResult.errors || []).forEach(({ field, message }) => {
          const id = field === 'narration' ? 'narration-error' : 'presentation-error';
          const zone = field === 'narration' ? zoneNarration : zonePres;
          showFieldError(id, message);
          zone.classList.add('invalid');
        });
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        return;
      }

      const sessionId = uploadResult.session_id;

      /* ---------- run pipeline (SSE) ---------- */
      submitBtn.innerHTML = '<span class="spinner"></span>Running\u2026';
      logSection.style.display = 'block';
      logBox.textContent = '';

      const params = new URLSearchParams({ session_id: sessionId });
      const evtSource = new EventSource('/run?' + params);

      evtSource.addEventListener('log', (e) => {
        logBox.textContent += e.data + '\n';
        logBox.scrollTop = logBox.scrollHeight;
      });

      evtSource.addEventListener('done', (e) => {
        evtSource.close();
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        successBanner.textContent = '\u2713 Video generated successfully!';
        successBanner.style.display = 'block';
        downloadBtn.href = '/download/' + sessionId;
        downloadSection.style.display = 'block';
      });

      evtSource.addEventListener('pipeline_error', (e) => {
        evtSource.close();
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        failureBanner.textContent = '\u2717 ' + e.data;
        failureBanner.style.display = 'block';
      });

      evtSource.onerror = () => {
        evtSource.close();
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        if (failureBanner.style.display === 'none' && successBanner.style.display === 'none') {
          failureBanner.textContent = 'Connection lost. Check the container logs for details.';
          failureBanner.style.display = 'block';
        }
      };
    });
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cleanup_sessions():
    """Remove the entire sessions directory (previous runs)."""
    if SESSIONS_DIR.exists():
        shutil.rmtree(SESSIONS_DIR, ignore_errors=True)


def _is_valid_session_id(session_id: str) -> bool:
    """Return True if session_id is a valid UUID v4 string (prevents path traversal)."""
    return bool(UUID_RE.match(session_id))


def _find_by_extensions(directory: Path, extensions: set[str]) -> Path | None:
    """Return the first file in directory matching any of the given extensions."""
    for f in directory.iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            return f
    return None


def _cleanup_after_success(session_dir: Path):
    """Delete uploaded source files and Audios/ dir, keep only output_video.mp4."""
    for f in session_dir.iterdir():
        if f.name == "output_video.mp4":
            continue
        if f.is_dir():
            shutil.rmtree(f, ignore_errors=True)
        else:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return HTML


@app.route("/upload", methods=["POST"])
def upload():
    """
    Accept uploaded narration + presentation files, save to a fresh session
    directory. Returns JSON: { ok, session_id?, errors? }
    """
    errors = []

    narration_file = request.files.get("narration")
    presentation_file = request.files.get("presentation")

    # --- validate narration ---
    if not narration_file or narration_file.filename == "":
        errors.append({"field": "narration", "message": "Narration script file is required."})
    else:
        suffix = Path(narration_file.filename).suffix.lower()
        if suffix not in NARRATION_EXTS:
            errors.append({
                "field": "narration",
                "message": f"Unsupported format ({suffix}). Accepted: {', '.join(sorted(NARRATION_EXTS))}",
            })
        else:
            narration_file.seek(0, 2)  # seek to end
            size = narration_file.tell()
            narration_file.seek(0)
            if size > MAX_FILE_SIZE:
                errors.append({"field": "narration", "message": f"File too large ({size // (1024*1024)} MB). Maximum is 20 MB."})

    # --- validate presentation ---
    if not presentation_file or presentation_file.filename == "":
        errors.append({"field": "presentation", "message": "Presentation file is required."})
    else:
        suffix = Path(presentation_file.filename).suffix.lower()
        if suffix not in PRESENTATION_EXTS:
            errors.append({
                "field": "presentation",
                "message": f"Unsupported format ({suffix}). Accepted: {', '.join(sorted(PRESENTATION_EXTS))}",
            })
        else:
            presentation_file.seek(0, 2)
            size = presentation_file.tell()
            presentation_file.seek(0)
            if size > MAX_FILE_SIZE:
                errors.append({"field": "presentation", "message": f"File too large ({size // (1024*1024)} MB). Maximum is 20 MB."})

    if errors:
        return jsonify({"ok": False, "errors": errors})

    # --- save files ---
    _cleanup_sessions()
    session_id = str(uuid4())
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    narration_path = session_dir / narration_file.filename
    narration_file.save(str(narration_path))

    presentation_path = session_dir / presentation_file.filename
    presentation_file.save(str(presentation_path))

    return jsonify({"ok": True, "session_id": session_id})


@app.route("/run")
def run():
    """
    Stream pipeline output as Server-Sent Events.
    Query param: session_id
    Events emitted: log, done, pipeline_error
    """
    session_id = request.args.get("session_id", "").strip()

    if not _is_valid_session_id(session_id):
        return Response("event: pipeline_error\ndata: Invalid session.\n\n",
                        content_type="text/event-stream")

    session_dir = SESSIONS_DIR / session_id

    if not session_dir.is_dir():
        return Response("event: pipeline_error\ndata: Invalid session.\n\n",
                        content_type="text/event-stream")

    # Locate uploaded files
    narration_path = _find_by_extensions(session_dir, NARRATION_EXTS)
    presentation_path = _find_by_extensions(session_dir, PRESENTATION_EXTS)

    if not narration_path or not presentation_path:
        return Response("event: pipeline_error\ndata: Uploaded files not found in session.\n\n",
                        content_type="text/event-stream")

    output_path = session_dir / "output_video.mp4"

    env = {
        **os.environ,
        "NARRATION_SCRIPT": str(narration_path),
        "PPTX_FILE":        str(presentation_path),
        "OUTPUT_PATH":      str(output_path),
    }

    def generate():
        proc = subprocess.Popen(
            ["bash", "/app/scripts/run_pipeline.sh"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            yield f"event: log\ndata: {line}\n\n"

        proc.wait()

        if proc.returncode == 0:
            # Clean up uploaded files + audios, keep only output_video.mp4
            _cleanup_after_success(session_dir)
            yield f"event: done\ndata: {session_id}\n\n"
        else:
            yield (
                f"event: pipeline_error\n"
                f"data: Pipeline failed (exit {proc.returncode}). See the log above for details.\n\n"
            )

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/download/<session_id>")
def download(session_id):
    """Serve the generated video file as a download."""
    if not _is_valid_session_id(session_id):
        return "Invalid session.", 400

    session_dir = SESSIONS_DIR / session_id
    video_path = session_dir / "output_video.mp4"

    if not video_path.is_file():
        return "Video not found. It may have been cleaned up.", 404

    return send_file(
        str(video_path),
        as_attachment=True,
        download_name="output_video.mp4",
        mimetype="video/mp4",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("  Presentation Video Generator")
    print("  Open http://localhost:8080 in your browser")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
