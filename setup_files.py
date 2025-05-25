#!/usr/bin/env python3
"""
TTS KOKORO Setup Script
This script helps organize your files in the correct structure for the Flask app to work.
"""

import os
import shutil
import sys

def create_directory_structure():
    """Create the required directory structure"""
    directories = [
        'templates',
        'static',
        'static/audio',
        'voices'
    ]
    
    print("🏗️  Creating directory structure...")
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Created: {directory}/")
        else:
            print(f"📁 Exists: {directory}/")

def move_html_file():
    """Move index.html to templates folder if it exists"""
    html_files = ['index.html', 'template.html', 'main.html']
    
    for html_file in html_files:
        if os.path.exists(html_file):
            target_path = os.path.join('templates', 'index.html')
            if not os.path.exists(target_path):
                shutil.copy2(html_file, target_path)
                print(f"✅ Moved {html_file} → templates/index.html")
            else:
                print(f"📄 HTML template already exists in templates/")
            return True
    
    print("⚠️  No HTML file found in current directory")
    return False

def check_requirements():
    """Check if required files exist"""
    required_files = {
        'ttsKOKORO.py': 'Main Python script',
        'piper.exe': 'Piper TTS executable',
        'templates/index.html': 'HTML template'
    }
    
    print("\n🔍 Checking required files...")
    missing_files = []
    
    for file_path, description in required_files.items():
        if os.path.exists(file_path):
            print(f"✅ {file_path} - {description}")
        else:
            print(f"❌ {file_path} - {description} (MISSING)")
            missing_files.append(file_path)
    
    return missing_files

def check_voice_files():
    """Check for voice files"""
    voices_dir = 'voices'
    voice_files = []
    
    if os.path.exists(voices_dir):
        voice_files = [f for f in os.listdir(voices_dir) if f.endswith('.onnx')]
    
    print(f"\n🎤 Found {len(voice_files)} voice files:")
    for voice_file in voice_files:
        print(f"   📢 {voice_file}")
    
    if not voice_files:
        print("⚠️  No .onnx voice files found in voices/ directory")
        print("   Download voice files from: https://github.com/rhasspy/piper/releases")

def create_sample_html():
    """Create a minimal HTML template if none exists"""
    template_path = os.path.join('templates', 'index.html')
    
    if os.path.exists(template_path):
        return False
    
    sample_html = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TTS KOKORO - Text Reader</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { background-color: #f8f9fa; font-family: 'Segoe UI', sans-serif; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .btn-primary { background-color: #4a6baf; border-color: #4a6baf; }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="text-center mb-4">🎙️ TTS KOKORO</h1>
        <div class="alert alert-info">
            <h4>Setup Required</h4>
            <p>This is a minimal template. Please replace this file with your complete index.html template.</p>
        </div>
        
        <div class="mb-3">
            <label for="voiceSelect" class="form-label">Voice:</label>
            <select class="form-select" id="voiceSelect">
                <option value="">Select Voice</option>
                {% for voice in piper_voices %}
                <option value="piper:{{ voice.id }}">{{ voice.name }}</option>
                {% endfor %}
                {% for voice in coqui_voices %}
                <option value="mms:{{ voice.id }}">{{ voice.name }}</option>
                {% endfor %}
            </select>
        </div>
        
        <button id="setupBtn" class="btn btn-primary">Initialize Reader</button>
        
        <div id="status" class="mt-3"></div>
    </div>
</body>
</html>'''
    
    with open(template_path, 'w', encoding='utf-8') as f:
        f.write(sample_html)
    
    print(f"✅ Created minimal template: {template_path}")
    return True

def main():
    """Main setup function"""
    print("=" * 60)
    print("🎙️  TTS KOKORO Setup Script")
    print("=" * 60)
    
    # Create directory structure
    create_directory_structure()
    
    # Try to move HTML file
    html_moved = move_html_file()
    
    # Create sample HTML if needed
    if not html_moved:
        created_sample = create_sample_html()
        if created_sample:
            print("📝 Created a minimal HTML template. Please replace with your full template.")
    
    # Check requirements
    missing_files = check_requirements()
    
    # Check voice files
    check_voice_files()
    
    print("\n" + "=" * 60)
    if missing_files:
        print("❌ Setup incomplete. Missing files:")
        for file_path in missing_files:
            print(f"   • {file_path}")
        print("\n📋 Next steps:")
        print("   1. Ensure all required files are in place")
        print("   2. Download Piper voices if needed")
        print("   3. Run the TTS server: python ttsKOKORO.py")
    else:
        print("✅ Setup complete! Your file structure is ready.")
        print("\n🚀 To start the server, run:")
        print("   python ttsKOKORO.py")
        print("\n🌐 Then open your browser to: http://localhost:5000")
    
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⏹️  Setup cancelled by user")
    except Exception as e:
        print(f"\n❌ Error during setup: {e}")
        input("Press Enter to exit...")