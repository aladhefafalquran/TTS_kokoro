from flask import Flask, render_template, request, jsonify, send_file
import subprocess
import os
import tempfile
import re
import uuid
import time
import logging
from concurrent.futures import ThreadPoolExecutor

# --- Backend Changes Implementation ---

# Import for potential audio format conversion (though not fully implemented in this backend-only update)
try:
    import ffmpeg  # This requires 'ffmpeg-python' and ffmpeg executable
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
voice_speed = 1.0

# Ensure directories exist
AUDIO_DIR = os.path.join(os.getcwd(), "static", "audio")
TEMPLATES_DIR = os.path.join(os.getcwd(), "templates")
STATIC_DIR = os.path.join(os.getcwd(), "static")

# Create necessary directories
os.makedirs(AUDIO_DIR, exist_ok=True)
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
    
    # Smart Preprocessing (conceptual for backend, actual implementation depends on complexity)
    # Convert "Dr." to "Doctor" (example)
    cleaned = re.sub(r'\bDr\.', 'Doctor', cleaned)
    # Spell out numbers contextually (simplified example, a full implementation is complex)
    # For a full implementation, consider a dedicated NLP library.
    
    # Remove special characters that might interfere with TTS (keep common punctuation)
    cleaned = re.sub(r'[^\w\s\.,!?;:\-\'"()]', '', cleaned)
    cleaned = cleaned.replace('\n', ' ')
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    
    # Ensure text ends with punctuation
    if cleaned and not cleaned[-1] in '.!?':
        cleaned += '.'
    
    return cleaned

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
            
        voice_model_path = os.path.join(voices_directory, voice_file)
        
        # Check if voice file exists
        if not os.path.exists(voice_model_path):
            logger.error(f"❌ Voice file not found: {voice_model_path}")
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
            
        length_scale = 1.0 / speed
        
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

# Placeholder for audio format conversion (requires ffmpeg)
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

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/')
def index():
    """Render the main interface."""
    try:
        # Get available Piper voices
        piper_voices = []
        if os.path.exists(voices_directory):
            for file in os.listdir(voices_directory):
                if file.endswith(".onnx"):
                    # Extract voice info (conceptual, more detailed info would need metadata files)
                    voice_name = file.replace('.onnx', '').replace('_', ' ').title()
                    # Example for gender/language from filename or config
                    gender = "Unknown"
                    if "male" in voice_name.lower():
                        gender = "Male"
                    elif "female" in voice_name.lower():
                        gender = "Female"
                    language = "English" # Default or derive from filename
                    
                    piper_voices.append({
                        "id": file,
                        "name": voice_name,
                        "type": "piper",
                        "language": language, # Voice Info
                        "gender": gender # Voice Info
                    })
        
        logger.info(f"📋 Found {len(piper_voices)} Piper voices")
        
        if not piper_voices:
            logger.warning("⚠️ No .onnx voice files found in voices/ directory")
        
        # Note: Frontend (index.html) would need updates to display new voice info fields.
        return render_template('index.html', piper_voices=piper_voices, coqui_voices=[])
    
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
├── 📄 ttsKOKORO.py
└── 📄 piper.exe
                </pre>
                <p><strong>Steps to Fix:</strong></p>
                <ol>
                    <li>Create a <code>templates</code> folder</li>
                    <li>Move your <code>index.html</code> file into the <code>templates</code> folder</li>
                    <li>Make sure you have voice files (.onnx) in the <code>voices</code> folder</li>
                    <li>Make sure <code>piper.exe</code> is in the main folder</li>
                    <li>Restart the server</li>
                </ol>
            </div>
        </body>
        </html>
        """, 500

@app.route('/health')
def health_check():
    """Health check endpoint."""
    voices_count = 0
    if os.path.exists(voices_directory):
        voices_count = len([f for f in os.listdir(voices_directory) if f.endswith('.onnx')])
    
    return jsonify({
        'status': 'healthy',
        'piper_available': os.path.exists(piper_exe),
        'voices_count': voices_count,
        'templates_exist': os.path.exists(os.path.join(TEMPLATES_DIR, 'index.html'))
    })

@app.route('/setup', methods=['POST'])
def setup():
    """Set up the voice selection."""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
            
        voice_data = data.get('voice')
        if not voice_data:
            return jsonify({'success': False, 'error': 'No voice selected'})
        
        # Check if it's a piper voice
        if not voice_data.startswith('piper:'):
            return jsonify({'success': False, 'error': 'Only Piper voices are supported'})
        
        if 'speed' in data:
            try:
                global voice_speed
                voice_speed = float(data.get('speed', 1.0))
            except ValueError:
                voice_speed = 1.0
        
        voice_type, voice_id = voice_data.split(':', 1)
        
        # Check if voice file exists
        if not os.path.exists(os.path.join(voices_directory, voice_id)):
            return jsonify({'success': False, 'error': f'Voice file not found: {voice_id}'})
        
        # Check if piper.exe exists
        if not os.path.exists(piper_exe):
            return jsonify({'success': False, 'error': f'Piper executable not found: {piper_exe}'})
        
        # Test voice setup
        welcome_message = "Hello! I'm ready to provide high-quality speech synthesis using Piper."
        audio_path = generate_speech_piper(welcome_message, voice_id, voice_speed)
        
        if audio_path:
            global last_response
            last_response = {
                "text": welcome_message, 
                "voice_id": voice_id,
                "voice_type": voice_type
            }
            
            return jsonify({
                'success': True,
                'voice': voice_data,
                'speed': voice_speed,
                'message': welcome_message,
                'audioPath': audio_path
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to generate welcome speech'})
        
    except Exception as e:
        logger.error(f"❌ Setup error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/generate_speech', methods=['POST'])
def generate_speech():
    """Generate speech using Piper."""
    try:
        data = request.json
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
            
        text = data.get('text')
        voice_data = data.get('voice')
        output_format = data.get('output_format', 'wav') # New: Output format option
        
        if not text or not voice_data:
            return jsonify({'success': False, 'error': 'Missing text or voice'})
        
        if not voice_data.startswith('piper:'):
            return jsonify({'success': False, 'error': 'Only Piper voices are supported'})
        
        voice_type, voice_id = voice_data.split(':', 1)
        speed = float(data.get('speed', 1.0))
        
        audio_path = generate_speech_piper(text, voice_id, speed)
        
        if audio_path:
            # Handle audio format conversion if requested
            if output_format != 'wav':
                converted_audio_path = convert_audio_format(os.path.join(os.getcwd(), audio_path[1:]), output_format)
                if converted_audio_path:
                    # Remove original .wav file if converted successfully
                    try:
                        os.remove(os.path.join(os.getcwd(), audio_path[1:]))
                    except OSError:
                        pass
                    audio_path = f"/static/audio/{os.path.basename(converted_audio_path)}"
                else:
                    logger.warning(f"Could not convert audio to {output_format}, serving WAV.")
            
            global last_response
            last_response = {
                "text": text, 
                "voice_id": voice_id,
                "voice_type": voice_type
            }
            
            # Enhanced Progress Feedback - Add character count and estimated time
            char_count = len(text)
            estimated_time = char_count * 0.01 # Rough estimate, can be refined
            
            return jsonify({
                'success': True, 
                'audioPath': audio_path,
                'taskId': str(uuid.uuid4()),
                'estimatedTime': estimated_time, # Enhanced Progress Feedback
                'characterCount': char_count # Enhanced Progress Feedback
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to generate speech'})
    
    except Exception as e:
        logger.error(f"❌ Speech generation error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/generation_progress/<task_id>', methods=['GET'])
def get_generation_progress(task_id):
    """Progress endpoint - Piper is fast so always complete."""
    # For Piper, progress is almost instant from the server perspective.
    # A more sophisticated progress would involve monitoring the subprocess if it were long-running.
    return jsonify({
        'success': True,
        'progress': 100,
        'status': 'complete',
        'message': 'Speech generation complete'
    })

@app.route('/download_audio/<filename>', methods=['GET'])
def download_audio(filename):
    """Download audio file."""
    try:
        # Sanitize filename to prevent directory traversal
        filename = os.path.basename(filename)
        file_path = os.path.join(AUDIO_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'error': 'File not found'}), 404
        
        download_name = request.args.get('download_name', filename)
        mimetype = 'audio/wav'
        if filename.endswith('.mp3'):
            mimetype = 'audio/mpeg'
        elif filename.endswith('.ogg'):
            mimetype = 'audio/ogg'

        return send_file(file_path, mimetype=mimetype, as_attachment=True, download_name=download_name)
    except Exception as e:
        logger.error(f"❌ Download error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up old audio files."""
    try:
        if not os.path.exists(AUDIO_DIR):
            return jsonify({'success': True, 'message': 'Audio directory does not exist'})
        
        # Remove files older than 1 hour (3600 seconds)
        cutoff_time = time.time() - 3600
        removed_count = 0
        
        for filename in os.listdir(AUDIO_DIR):
            file_path = os.path.join(AUDIO_DIR, filename)
            if os.path.isfile(file_path) and os.path.getmtime(file_path) < cutoff_time:
                try:
                    os.remove(file_path)
                    removed_count += 1
                except OSError as e:
                    logger.warning(f"Could not remove old file {file_path}: {e}")
        
        return jsonify({'success': True, 'removed': removed_count})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# New route for voice preview
@app.route('/preview_voice', methods=['POST'])
def preview_voice():
    """Generate a quick audio sample for voice preview."""
    try:
        data = request.json
        voice_id = data.get('voice_id')
        sample_text = data.get('sample_text', "Hello! This is how I sound.") # Default sample text
        
        if not voice_id:
            return jsonify({'success': False, 'error': 'No voice_id provided'})
        
        voice_file = voice_id.replace('piper:', '') # Remove 'piper:' prefix
        
        audio_path = generate_speech_piper(sample_text, voice_file, speed=1.0) # Always 1.0 speed for preview
        
        if audio_path:
            return jsonify({
                'success': True,
                'audioPath': audio_path
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to generate voice preview'})
            
    except Exception as e:
        logger.error(f"❌ Voice preview error: {e}")
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    logger.info("🎙️ Starting Simple Piper TTS Server")
    
    # Check if piper.exe exists
    if not os.path.exists(piper_exe):
        logger.error(f"❌ Piper executable not found: {piper_exe}")
        logger.info("💡 Make sure piper.exe is in the same folder as this script")
    else:
        logger.info("✅ Piper executable found")
    
    # Check voice files
    if os.path.exists(voices_directory):
        voice_files = [f for f in os.listdir(voices_directory) if f.endswith('.onnx')]
        logger.info(f"🎤 Found {len(voice_files)} voice files")
        if not voice_files:
            logger.warning("⚠️ No .onnx voice files found in voices/ directory")
            logger.info("💡 Download voice files from: https://github.com/rhasspy/piper/releases")
    else:
        logger.warning("⚠️ Voices directory not found")
    
    # Check template
    template_path = os.path.join(TEMPLATES_DIR, 'index.html')
    if not os.path.exists(template_path):
        logger.warning(f"⚠️ Template file not found: {template_path}")
        logger.info("💡 Please create templates/ folder and put your index.html file inside it")
    else:
        logger.info("✅ Template file found")
    
    # Create directories
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(voices_directory, exist_ok=True)
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    
    # Start Flask app
    logger.info("🚀 Starting web server...")
    logger.info("🌐 Open your browser and go to: http://localhost:5000")
    logger.info("💡 For system status, visit: http://localhost:5000/health")
    
    try:
        app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)
    except Exception as e:
        logger.error(f"❌ Failed to start server: {e}")
        input("Press Enter to exit...")