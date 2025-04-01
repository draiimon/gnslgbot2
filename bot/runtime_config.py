import os

# Configuration to handle PyAudio disable on Render
# Set DISABLE_PYAUDIO=false in Dockerfile to enable audio features in Render
DISABLE_PYAUDIO = os.getenv('DISABLE_PYAUDIO', 'false').lower() == 'true'

def is_render_environment():
    """Check if we're running on Render environment"""
    return os.getenv('RENDER', 'false').lower() == 'true'

def can_use_audio_features():
    """Check if audio features (PyAudio) should be enabled"""
    # If DISABLE_PYAUDIO is explicitly set to true, disable regardless of environment
    if DISABLE_PYAUDIO:
        print("⚠️ PyAudio features disabled by configuration")
        return False
        
    # On Render, use PyAudio if explicitly enabled in Dockerfile
    if is_render_environment():
        if os.getenv('DISABLE_PYAUDIO', 'true').lower() == 'false':
            print("✅ PyAudio features ENABLED for Render environment by explicit configuration")
            return True
        else:
            print("⚠️ PyAudio features disabled for Render environment")
            return False
            
    # On non-Render environments, always enable PyAudio
    return True