import subprocess
import os
import tempfile
import re
import uuid
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from flask import Flask, render_template, request, jsonify, send_file, Response

# --- NEW: Speech-to-Text Imports ---
try:
    import whisper
    WHISPER_AVAILABLE = True
    # Load Whisper model (you can change to 'medium' or 'large' for better accuracy)
    whisper_model = whisper.load_model("base")
    print("✅ Whisper loaded successfully")
except ImportError:
    WHISPER_AVAILABLE = False
    whisper_model = None
    print("⚠️ Whisper not available. Install with: pip install openai-whisper")

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    print("⚠️ Librosa not available. Install with: pip install librosa")

# --- Backend Changes Implementation ---

# Import for potential audio format conversion
try:
    import ffmpeg
except ImportError:
    print("Warning: ffmpeg-python not installed. Audio format conversion (if enabled) will not work.")
    ffmpeg = None

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ttsKOKORO")

# Global variables
piper_exe = "piper.exe"
voices_directory = os.path.join(os.getcwd(), "voices")
voice_speed = 1.0 # This variable seems unused, so I'll ignore it.

# NEW: Base adjustment for Piper's length-scale to fine-tune perceived "normal" speed
# A value > 1.0 will slow down the audio; < 1.0 will speed it up.
# This helps if Piper's default 1.0 length-scale is perceived as too fast.
BASE_LENGTH_SCALE_ADJUSTMENT = 1.1 # Adjust this value as needed. 1.0 for no adjustment.

# Ensure directories exist
AUDIO_DIR = os.path.join(os.getcwd(), "static", "audio")
UPLOADS_DIR = os.path.join(os.getcwd(), "uploads")  # NEW: For STT uploads
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
STATIC_DIR = os.path.join(os.getcwd(), "static")

# Create necessary directories
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)  # NEW
os.makedirs(voices_directory, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Cache for last response
last_response = {"text": "", "voice_id": None, "voice_type": "piper"}

# Thread pool
speech_executor = ThreadPoolExecutor(max_workers=2)

def clean_text_for_speech(text):
    """Clean text for speech synthesis and basic preprocessing for Piper."""
    if not text:
        return ""

    # Basic cleaning
    cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # Bold
    cleaned = re.sub(r'\*(.+?)\*', r'\1', cleaned)  # Italic
    cleaned = re.sub(r'`(.+?)`', r'\1', cleaned)  # Code
    cleaned = re.sub(r'##+\s*(.+)', r'\1', cleaned)  # Headers
    cleaned = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', cleaned)  # Links
    cleaned = re.sub(r'https?://\S+', '', cleaned)  # URLs

    # Smart Preprocessing
    cleaned = re.sub(r'\bDr\.', 'Doctor', cleaned)

    # Remove special characters that might interfere with TTS
    cleaned = re.sub(r'[^\w\s\.,!?;:\-\'"()]', '', cleaned)
    cleaned = cleaned.replace('\n', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Ensure text ends with punctuation
    if cleaned and not cleaned[-1] in '.!?':
        cleaned += '.'

    return cleaned

# --- NEW: Speech-to-Text Functions ---

def transcribe_audio_whisper(audio_path):
    """Transcribe audio using Whisper."""
    if not WHISPER_AVAILABLE or not whisper_model:
        return None, "Whisper not available"

    try:
        logger.info(f"🎤 Transcribing audio: {audio_path}")
        result = whisper_model.transcribe(audio_path)
        text = result["text"].strip()

        # Get detected language
        detected_language = result.get("language", "unknown")

        logger.info(f"✅ Transcription complete. Detected language: {detected_language}")
        return text, detected_language

    except Exception as e:
        logger.error(f"❌ Whisper transcription error: {e}")
        return None, str(e)

def convert_audio_for_whisper(input_path, output_path):
    """Convert audio to WAV format for Whisper processing."""
    try:
        if LIBROSA_AVAILABLE:
            # Use librosa for audio conversion
            audio_data, sample_rate = librosa.load(input_path, sr=16000)
            import soundfile as sf
            sf.write(output_path, audio_data, sample_rate)
            return True
        elif ffmpeg:
            # Use ffmpeg for conversion
            command = [
                'ffmpeg', '-i', input_path,
                '-ar', '16000',  # 16kHz sample rate
                '-ac', '1',      # Mono
                '-f', 'wav',
                output_path, '-y'  # Overwrite output
            ]
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        else:
            logger.error("No audio conversion library available")
            return False
    except Exception as e:
        logger.error(f"Audio conversion error: {e}")
        return False

# --- Existing TTS Functions (changed `length_scale`) ---

@lru_cache(maxsize=32)
def get_voice(voice_id):
    """Load and cache voice models."""
    voice_model_path = os.path.join(voices_directory, voice_id)
    if not os.path.exists(voice_model_path):
        logger.error(f"❌ Voice file not found: {voice_model_path}")
        return None
    return voice_model_path

def generate_speech_piper(text, voice_file, speed=1.0):
    """Generate speech using Piper."""
    if not text.strip() or not voice_file:
        logger.error("❌ Empty text or missing voice file")
        return None

    try:
        text = clean_text_for_speech(text)
        output_filename = f"piper_speech_{uuid.uuid4().hex}.wav"
        output_path = os.path.join(AUDIO_DIR, output_filename)

        # Create temporary text file
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as text_file:
            text_file_path = text_file.name
            text_file.write(text)

        voice_model_path = get_voice(voice_file)
        if not voice_model_path:
            try:
                os.unlink(text_file_path)
            except OSError:
                pass
            return None

        # Check if piper.exe exists
        if not os.path.exists(piper_exe):
            logger.error(f"❌ Piper executable not found: {piper_exe}")
            try:
                os.unlink(text_file_path)
            except OSError:
                pass
            return None

        # Calculate length_scale: 1.0 / speed from frontend * BASE_LENGTH_SCALE_ADJUSTMENT
        # Higher length_scale means slower speech.
        length_scale = (1.0 / speed) * BASE_LENGTH_SCALE_ADJUSTMENT

        command = [
            piper_exe,
            "--model", voice_model_path,
            "--output_file", output_path,
            "--length-scale", str(length_scale)
        ]

        logger.info(f"🎤 Generating Piper speech for: {text[:50]}...")

        # Run Piper command
        with open(text_file_path, "r", encoding="utf-8") as input_file:
            process = subprocess.run(
                command,
                stdin=input_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8"
            )

        # Clean up temp file
        try:
            os.unlink(text_file_path)
        except OSError:
            pass

        if process.returncode != 0:
            logger.error(f"❌ Piper error: {process.stderr}")
            return None

        # Check if output file was created
        if not os.path.exists(output_path):
            logger.error("❌ Piper did not create output file")
            return None

        logger.info("✅ Piper speech generation complete!")
        return f"/static/audio/{output_filename}"

    except Exception as e:
        logger.error(f"❌ Error generating Piper speech: {e}")
        return None

def convert_audio_format(wav_path, output_format='mp3'):
    """Convert WAV to other formats using ffmpeg."""
    if not ffmpeg:
        logger.error("FFmpeg not available for audio format conversion.")
        return None

    try:
        output_path = wav_path.replace('.wav', f'.{output_format}')
        command = [
            'ffmpeg', '-i', wav_path,
            '-codec:a', 'libmp3lame' if output_format == 'mp3' else 'libvorbis',
            '-qscale:a', '2',
            output_path
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"Converted {wav_path} to {output_path}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion error: {e.stderr}")
        return None
    except Exception as e:
        logger.error(f"Error in audio format conversion: {e}")
        return None

# --- NEW: Speech-to-Text Routes ---

@app.route('/transcribe_audio', methods=['POST'])
def transcribe_audio():
    """Transcribe uploaded audio file to text."""
    try:
        if not WHISPER_AVAILABLE:
            return jsonify({
                'success': False,
                'error': 'Speech recognition not available. Please install Whisper: pip install openai-whisper'
            })

        # Check if file was uploaded
        if 'audio_file' not in request.files:
            return jsonify({'success': False, 'error': 'No audio file provided'})

        file = request.files['audio_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})

        # Save uploaded file
        file_extension = file.filename.split('.')[-1].lower()
        if file_extension not in ['wav', 'mp3', 'ogg', 'm4a', 'flac', 'webm']:
            return jsonify({'success': False, 'error': 'Unsupported audio format'})

        upload_filename = f"upload_{uuid.uuid4().hex}.{file_extension}"
        upload_path = os.path.join(UPLOADS_DIR, upload_filename)
        file.save(upload_path)

        # Convert to WAV if needed
        if file_extension != 'wav':
            wav_filename = f"converted_{uuid.uuid4().hex}.wav"
            wav_path = os.path.join(UPLOADS_DIR, wav_filename)

            if not convert_audio_for_whisper(upload_path, wav_path):
                return jsonify({'success': False, 'error': 'Failed to convert audio format'})

            # Clean up original file
            try:
                os.remove(upload_path)
            except OSError:
                pass

            transcribe_path = wav_path
        else:
            transcribe_path = upload_path

        # Transcribe audio
        transcribed_text, detected_language = transcribe_audio_whisper(transcribe_path)

        # Clean up files
        try:
            os.remove(transcribe_path)
        except OSError:
            pass

        if transcribed_text:
            return jsonify({
                'success': True,
                'text': transcribed_text,
                'detected_language': detected_language,
                'character_count': len(transcribed_text)
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Transcription failed: {detected_language}'
            })

    except Exception as e:
        logger.error(f"❌ Transcription error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_stt_availability', methods=['GET'])
def check_stt_availability():
    """Check if speech-to-text features are available."""
    return jsonify({
        'whisper_available': WHISPER_AVAILABLE,
        'librosa_available': LIBROSA_AVAILABLE,
        'ffmpeg_available': ffmpeg is not None
    })

# --- Existing Routes (unchanged, except for /generate_speech and /index) ---

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/generate_speech', methods=['POST'])
def generate_speech():
    data = request.json
    text = data.get('text')
    voice_id = data.get('voice_id')
    speed = data.get('speed', 1.0)
    output_format = data.get('format', 'wav')

    if not text:
        return jsonify({'success': False, 'error': 'No text provided.'})
    if not voice_id:
        return jsonify({'success': False, 'error': 'No voice selected.'})

    voice_type, actual_voice_id = voice_id.split(':', 1)

    audio_url = None
    if voice_type == 'piper':
        audio_url = generate_speech_piper(text, actual_voice_id, speed)
    else:
        return jsonify({'success': False, 'error': 'Unsupported voice type.'})

    if audio_url:
        # If output format is different from what Piper generates (WAV), convert it
        if output_format != 'wav':
            original_wav_path = os.path.join(AUDIO_DIR, os.path.basename(audio_url))
            converted_path = convert_audio_format(original_wav_path, output_format)
            if converted_path:
                # Remove original WAV after conversion to save space
                try:
                    os.remove(original_wav_path)
                except OSError as e:
                    logger.warning(f"Failed to remove original WAV file {original_wav_path}: {e}")
                audio_url = f"/static/audio/{os.path.basename(converted_path)}"
            else:
                return jsonify({'success': False, 'error': 'Failed to convert audio format.'})

        last_response["text"] = text
        last_response["voice_id"] = voice_id
        last_response["voice_type"] = voice_type

        return jsonify({'success': True, 'audio_url': audio_url})
    else:
        return jsonify({'success': False, 'error': 'Failed to generate speech.'})

@app.route('/get_voices', methods=['GET'])
def get_voices():
    # This route is not directly used by index.html but can be helpful for debugging
    piper_voices = []
    if os.path.exists(voices_directory):
        for file in os.listdir(voices_directory):
            if file.endswith(".onnx"):
                voice_name = file.replace('.onnx', '').replace('_', ' ').title()
                gender = "Unknown"
                if "male" in voice_name.lower():
                    gender = "Male"
                elif "female" in voice_name.lower():
                    gender = "Female"
                language = "English" # Assuming English for Piper models without explicit language info
                piper_voices.append({
                    "id": file,
                    "name": voice_name,
                    "type": "piper",
                    "language": language,
                    "gender": gender
                })
    return jsonify({'piper_voices': piper_voices})

@app.route('/stream_audio/<filename>')
def stream_audio(filename):
    """Stream audio file."""
    audio_path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(audio_path):
        return jsonify({'success': False, 'error': 'Audio file not found'}), 404

    def generate():
        with open(audio_path, 'rb') as f:
            while True:
                data = f.read(1024)
                if not data:
                    break
                yield data

    return Response(generate(), mimetype='audio/wav')

@app.route('/')
def index():
    """Render the main interface."""
    try:
        # Get available Piper voices
        piper_voices = []
        if os.path.exists(voices_directory):
            for file in os.listdir(voices_directory):
                if file.endswith(".onnx"):
                    voice_name = file.replace('.onnx', '').replace('_', ' ').title()
                    gender = "Unknown"
                    if "male" in voice_name.lower():
                        gender = "Male"
                    elif "female" in voice_name.lower():
                        gender = "Female"
                    language = "English"
                    piper_voices.append({
                        "id": file,
                        "name": voice_name,
                        "type": "piper",
                        "language": language,
                        "gender": gender
                    })
            logger.info(f"📋 Found {len(piper_voices)} Piper voices")
            if not piper_voices:
                logger.warning("⚠️ No .onnx voice files found in voices/ directory")

        # Check for necessary files and directories during startup
        if not os.path.exists(piper_exe):
            logger.error(f"❌ Piper executable not found: {piper_exe}")
        else:
            logger.info("✅ Piper executable found")

        if WHISPER_AVAILABLE:
            logger.info("✅ Whisper STT available")
        else:
            logger.warning("⚠️ Whisper STT not available - install with: pip install openai-whisper")

        if LIBROSA_AVAILABLE:
            logger.info("✅ Librosa audio processing available")
        else:
            logger.warning("⚠️ Librosa not available - install with: pip install librosa soundfile")

        # Check voice files
        if os.path.exists(voices_directory):
            voice_files = [f for f in os.listdir(voices_directory) if f.endswith('.onnx')]
            logger.info(f"🎤 Found {len(voice_files)} voice files")
            if not voice_files:
                logger.warning("⚠️ No .onnx voice files found in voices/ directory")
        else:
            logger.warning("⚠️ Voices directory not found")

        # Create directories
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        os.makedirs(voices_directory, exist_ok=True)
        os.makedirs(TEMPLATES_DIR, exist_ok=True)

        logger.info("🚀 Starting web server...")
        logger.info("🌐 Open your browser to http://127.0.0.1:5000/")

        return render_template('index.html', piper_voices=piper_voices, coqui_voices=[], stt_available=WHISPER_AVAILABLE)
    except Exception as e:
        logger.error(f"❌ Error rendering template: {e}")
        return f"""
        <html>
        <head><title>TTS KOKORO - Setup Required</title></head>
        <body style="font-family: Arial, sans-serif; padding: 40px; background: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <h1 style="color: #d32f2f;">⚠️ Setup Required</h1>
                <p><strong>Error:</strong> {str(e)}</p>
                <h3>📁 Required File Structure:</h3>
                <pre style="background: #f5f5f5; padding: 15px; border-radius: 5px;">
📁 Your Project Folder/
├── 📁 templates/
│   └── 📄 index.html
├── 📁 static/
│   └── 📁 audio/
├── 📁 voices/
│   └── 📄 your_voice.onnx
├── 📁 uploads/ (NEW - for STT)
├── 📄 ttsKOKORO.py
└── 📄 piper.exe (or equivalent executable for your OS)
                </pre>
                <p>Please ensure all necessary files and directories are in place.</p>
                <p>Make sure 'piper.exe' (or 'piper' for Linux/macOS) is in the root project folder.</p>
                <p>Download Piper voices from <a href="https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en" target="_blank">Hugging Face</a> and place them in the 'voices' folder.</p>
            </div>
        </body>
        </html>
        """, 500



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Use Render's PORT env
    app.run(host="0.0.0.0", port=port)
