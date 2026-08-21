import os
import base64
import tempfile
import subprocess
import logging
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_KEY = os.environ.get("API_KEY", "")


def check_api_key():
    """Validates API key if one is configured."""
    if not API_KEY:
        return True  # No key configured, allow all
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    return key == API_KEY


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "audio-converter"})


@app.route("/convert/mp3-to-ogg", methods=["POST"])
def convert_mp3_to_ogg():
    """
    Converts base64-encoded MP3 audio to OGG Opus (WhatsApp PTT compatible).

    Request body (JSON):
        {
            "audio": "<base64-encoded MP3 data>"
        }

    Response (JSON):
        {
            "audio": "<base64-encoded OGG Opus data>",
            "mime": "audio/ogg",
            "size": <bytes>
        }
    """
    if not check_api_key():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data or "audio" not in data:
        return jsonify({"error": "Missing 'audio' field in request body"}), 400

    try:
        mp3_bytes = base64.b64decode(data["audio"])
    except Exception:
        return jsonify({"error": "Invalid base64 in 'audio' field"}), 400

    input_path = None
    output_path = None

    try:
        # Write MP3 to temp file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            input_path = f.name

        output_path = input_path.replace(".mp3", ".ogg")

        # Convert MP3 → OGG Opus using ffmpeg
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",                  # Overwrite output without asking
                "-i", input_path,      # Input file
                "-c:a", "libopus",     # Opus codec (required for WhatsApp PTT)
                "-b:a", "64k",         # Bitrate (64kbps is good for voice)
                "-ar", "48000",        # Sample rate (Opus standard)
                "-ac", "1",            # Mono audio (voice messages are mono)
                "-application", "voip",# Optimized for voice
                output_path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            return jsonify({
                "error": "Conversion failed",
                "detail": result.stderr[-500:]  # Last 500 chars of stderr
            }), 500

        with open(output_path, "rb") as f:
            ogg_bytes = f.read()

        ogg_base64 = base64.b64encode(ogg_bytes).decode("utf-8")

        logger.info(f"Converted {len(mp3_bytes)} bytes MP3 → {len(ogg_bytes)} bytes OGG Opus")

        return jsonify({
            "audio": ogg_base64,
            "mime": "audio/ogg",
            "size": len(ogg_bytes)
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "Conversion timed out"}), 504
    except Exception as e:
        logger.exception("Unexpected error during conversion")
        return jsonify({"error": str(e)}), 500
    finally:
        # Always clean up temp files
        if input_path and os.path.exists(input_path):
            os.unlink(input_path)
        if output_path and os.path.exists(output_path):
            os.unlink(output_path)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
