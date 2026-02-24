#!/usr/bin/env python3
"""
web_ui.py

Serves a browser-based form so the user can provide:
  1. Narration script path (.md)
  2. PowerPoint presentation path (.pptx)
  3. Output video path (.mp4)

On submit, validates that the files exist, then streams the pipeline output
live to the browser via Server-Sent Events (SSE).

Start: python /app/scripts/web_ui.py
Open:  http://localhost:8080
"""

import os
import subprocess
from pathlib import Path
from flask import Flask, request, jsonify, Response, stream_with_context

app = Flask(__name__)

# ---------------------------------------------------------------------------
# HTML template (self-contained — no external CDN dependencies)
# ---------------------------------------------------------------------------
HTML = """<!DOCTYPE html>
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

    input[type="text"] {
      width: 100%;
      padding: 10px 14px;
      border: 1.5px solid #e2e8f0;
      border-radius: 8px;
      font-size: 13px;
      font-family: "SFMono-Regular", "Consolas", monospace;
      color: #2d3748;
      background: #fff;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    input[type="text"]:focus {
      border-color: #667eea;
      box-shadow: 0 0 0 3px rgba(102,126,234,0.12);
    }
    input[type="text"].field-invalid {
      border-color: #e53e3e;
      box-shadow: 0 0 0 3px rgba(229,62,62,0.1);
    }

    .hint       { font-size: 11px; color: #a0aec0; margin-top: 4px; font-family: monospace; }
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
      <p>Provide the paths to your files inside the container (everything under <code>/workspace</code>),
         then click <strong>Generate Video</strong> to run the pipeline.</p>
    </div>

    <form id="pipeline-form" novalidate>

      <div class="field">
        <label for="md_file">Narration Script Path</label>
        <input type="text" id="md_file" name="md_file" autocomplete="off"
               placeholder="/workspace/Safe_AI_Usage/Narration_Scripts_Safe_AI_Usage.md" />
        <div class="hint">Full path to the .md file — e.g. /workspace/YourTopic/Narration_Scripts.md</div>
        <div class="field-error" id="md_file-error"></div>
      </div>

      <div class="field">
        <label for="pptx_file">PowerPoint Presentation Path</label>
        <input type="text" id="pptx_file" name="pptx_file" autocomplete="off"
               placeholder="/workspace/Safe_AI_Usage/Safe_AI_Usage_Dexterous_Group.pptx" />
        <div class="hint">Full path to the .pptx file — e.g. /workspace/YourTopic/Presentation.pptx</div>
        <div class="field-error" id="pptx_file-error"></div>
      </div>

      <div class="field">
        <label for="output_path">Output Video Path</label>
        <input type="text" id="output_path" name="output_path" autocomplete="off"
               placeholder="/workspace/Output/output_video.mp4" />
        <div class="hint">Full path for the generated .mp4 — the directory will be created if it does not exist</div>
        <div class="field-error" id="output_path-error"></div>
      </div>

      <button type="submit" class="btn" id="submit-btn">Generate Video</button>
    </form>

    <div class="log-section" id="log-section">
      <div class="log-label">Pipeline Output</div>
      <div class="log-box" id="log-box"></div>
    </div>

    <div class="banner success" id="success-banner"></div>
    <div class="banner failure" id="failure-banner"></div>
  </div>

  <script>
    const form        = document.getElementById('pipeline-form');
    const submitBtn   = document.getElementById('submit-btn');
    const logSection  = document.getElementById('log-section');
    const logBox      = document.getElementById('log-box');
    const successBanner = document.getElementById('success-banner');
    const failureBanner = document.getElementById('failure-banner');

    const FIELDS = ['md_file', 'pptx_file', 'output_path'];
    const LABELS = {
      md_file:     'Narration Script Path',
      pptx_file:   'PowerPoint Presentation Path',
      output_path: 'Output Video Path',
    };

    function clearErrors() {
      FIELDS.forEach(f => {
        document.getElementById(f).classList.remove('field-invalid');
        const el = document.getElementById(f + '-error');
        el.textContent = '';
        el.style.display = 'none';
      });
      successBanner.style.display = 'none';
      failureBanner.style.display = 'none';
    }

    function showFieldError(field, msg) {
      document.getElementById(field).classList.add('field-invalid');
      const el = document.getElementById(field + '-error');
      el.textContent = msg;
      el.style.display = 'block';
    }

    function validateLocally() {
      let ok = true;
      FIELDS.forEach(f => {
        if (!document.getElementById(f).value.trim()) {
          showFieldError(f, `${LABELS[f]} is required.`);
          ok = false;
        }
      });
      return ok;
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      clearErrors();

      if (!validateLocally()) return;

      const md_file     = document.getElementById('md_file').value.trim();
      const pptx_file   = document.getElementById('pptx_file').value.trim();
      const output_path = document.getElementById('output_path').value.trim();

      // Server-side validation (file existence check) before starting the pipeline
      let validation;
      try {
        const res = await fetch('/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ md_file, pptx_file, output_path }),
        });
        validation = await res.json();
      } catch (err) {
        failureBanner.textContent = 'Could not reach the server. Is the container running?';
        failureBanner.style.display = 'block';
        return;
      }

      if (!validation.ok) {
        validation.errors.forEach(({ field, message }) => showFieldError(field, message));
        return;
      }

      // Kick off the pipeline with live log streaming
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span>Running\u2026';
      logSection.style.display = 'block';
      logBox.textContent = '';

      const params = new URLSearchParams({ md_file, pptx_file, output_path });
      const evtSource = new EventSource(`/run?${params}`);

      evtSource.addEventListener('log', (e) => {
        logBox.textContent += e.data + '\\n';
        logBox.scrollTop = logBox.scrollHeight;
      });

      evtSource.addEventListener('done', (e) => {
        evtSource.close();
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        successBanner.textContent = '\\u2713 ' + e.data;
        successBanner.style.display = 'block';
      });

      evtSource.addEventListener('pipeline_error', (e) => {
        evtSource.close();
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        failureBanner.textContent = '\\u2717 ' + e.data;
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
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return HTML


@app.route("/validate", methods=["POST"])
def validate():
    """
    Check that the provided paths are valid before starting the pipeline.
    Returns JSON: { ok: bool, errors: [{ field, message }] }
    """
    data = request.get_json(silent=True) or {}
    md_file     = data.get("md_file", "").strip()
    pptx_file   = data.get("pptx_file", "").strip()
    output_path = data.get("output_path", "").strip()

    errors = []

    if md_file and not Path(md_file).is_file():
        errors.append({"field": "md_file", "message": f"File not found: {md_file}"})

    if pptx_file and not Path(pptx_file).is_file():
        errors.append({"field": "pptx_file", "message": f"File not found: {pptx_file}"})

    if output_path:
        output_dir = Path(output_path).parent
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                errors.append({
                    "field": "output_path",
                    "message": f"Cannot create output directory: {exc}",
                })

    return jsonify({"ok": not errors, "errors": errors})


@app.route("/run")
def run():
    """
    Stream pipeline output as Server-Sent Events.
    Query params: md_file, pptx_file, output_path
    Events emitted: log, done, pipeline_error
    """
    md_file     = request.args.get("md_file", "").strip()
    pptx_file   = request.args.get("pptx_file", "").strip()
    output_path = request.args.get("output_path", "").strip()

    env = {
        **os.environ,
        "NARRATION_SCRIPT": md_file,
        "PPTX_FILE":        pptx_file,
        "OUTPUT_PATH":      output_path,
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
            # SSE data fields must not contain literal newlines
            safe_line = line.replace("\n", " ")
            yield f"event: log\ndata: {safe_line}\n\n"

        proc.wait()

        if proc.returncode == 0:
            yield f"event: done\ndata: Done! Video saved to: {output_path}\n\n"
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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print("  Presentation Video Generator")
    print("  Open http://localhost:8080 in your browser")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
