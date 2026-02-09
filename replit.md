# GNSLG Discord Bot Project

## Overview

A comprehensive Discord bot called "GNSLG Bot" that provides AI-powered chat responses in Tagalog, voice message processing, automated greetings, gaming features, and Discord server management capabilities.

## Recent Changes

### October 28, 2025 - Production Deployment Ready
- ✅ **Fixed Opus Library Loading**: Added automatic libopus loading in main.py for voice support
- ✅ **Created Deployment Files**: Added render_requirements.txt, render.yaml, and verify_deployment.py
- ✅ **Optimized Dependencies**: Verified all Python packages in pyproject.toml and render_requirements.txt
- ✅ **Updated .gitignore**: Added attached_assets/ exclusion, kept render_requirements.txt tracked
- ✅ **Fixed Type Warnings**: Added type: ignore comments for false positive LSP errors
- ✅ **Verified Bot Functionality**: All 37 commands working including voice, TTS, and AI chat
- ✅ **Docker Ready**: Dockerfile configured with all system dependencies (libopus, ffmpeg, libsodium)
- ✅ **Deployment Verification**: Created automated script to check all dependencies before deployment

## System Architecture

### Core Components
- **Discord Bot**: Main bot application using discord.py with voice support
- **AI Integration**: Groq API with DeepSeek R1 model for Tagalog responses
- **Database**: Firebase Firestore for user data and conversation history
- **Voice Processing**: Text-to-speech (edge-tts) and speech recognition capabilities
- **Web Interface**: Simple Flask app showing bot status on port 5000
- **Scheduled Tasks**: Automated greetings at 8 AM and 10 PM

### Technical Stack
- **Backend**: Python 3.11 with Flask and discord.py
- **AI Model**: Groq API with DeepSeek R1 Distill LLama 70B
- **Database**: Firebase Firestore (production mode)
- **Voice**: edge-tts for advanced TTS with male/female voice options
- **Deployment**: Docker + Render with automated health checks

## Key Features

### Discord Bot Commands (37 Total)
- **AI Chat**: `g!usap`, `g!ask`, `g!asklog` - Chat with AI in Tagalog
- **Gaming**: `g!daily`, `g!balance`, `g!toss`, `g!blackjack`, `g!give` - Virtual economy
- **Voice**: `g!joinvc`, `g!vc`, `g!listen`, `g!autotts`, `g!change` - Voice interaction
- **Utility**: `g!tulong`, `g!view`, `g!leaderboard` - Help and info
- **Admin**: `g!admin`, `g!announcement`, `g!maintenance`, `g!status` - Server management

### Voice Features
- Text-to-speech with Filipino and English support
- Male/Female voice preferences (saved per user in Firebase)
- AI-powered voice responses
- Automatic TTS for designated channels
- Voice channel connection management

## Deployment Configuration

### Docker (Render Platform)
The project is fully configured for Docker deployment on Render:

1. **Dockerfile**: Multi-layer build optimized for caching
   - Layer 1: Build tools and dependencies
   - Layer 2: Audio libraries (ffmpeg, libopus, libsodium)
   - Layer 3: Security libraries
   - Automatic libopus loading for Discord voice

2. **render.yaml**: Blueprint for one-click deployment
   - Service type: Web (with Docker)
   - Region: Singapore
   - Health check: HTTP endpoint on port 5000
   - Environment variables: DISCORD_TOKEN, GROQ_API_KEY, FIREBASE_CREDENTIALS

3. **Aptfile**: System dependencies for Replit environment
   - All audio codecs and development libraries

### Deployment Verification
Run `python verify_deployment.py` before deploying to check:
- ✅ All required files exist
- ✅ Environment variables are set
- ✅ Python packages are installed
- ✅ Audio packages are available
- ✅ Required directories exist

## Required Environment Variables

### Production Secrets
- `DISCORD_TOKEN` - Bot authentication token
- `GROQ_API_KEY` - AI model API access
- `FIREBASE_CREDENTIALS` - Firebase connection (JSON string)

### Optional Configuration
- `RENDER=true` - Set automatically on Render
- `DISABLE_PYAUDIO=false` - Enable audio features
- `PORT=5000` - Web interface port

## File Structure

```
.
├── bot/
│   ├── __init__.py
│   ├── cog.py                      # Main command handlers
│   ├── config.py                   # Configuration settings
│   ├── firebase_db.py              # Firebase integration
│   ├── rate_limiter.py             # Rate limiting
│   ├── runtime_config.py           # Environment detection
│   ├── speech_recognition_cog.py   # Voice command handlers
│   └── status_monitor.py           # Bot status monitoring
├── templates/
│   └── index.html                  # Web interface
├── logs/                           # Runtime logs
├── temp_audio/                     # Temporary TTS files
├── Dockerfile                      # Docker build configuration
├── render.yaml                     # Render deployment blueprint
├── render_requirements.txt         # Python dependencies for Docker
├── pyproject.toml                  # Python dependencies for Replit
├── Aptfile                         # System dependencies for Replit
├── main.py                         # Bot entry point
├── verify_deployment.py            # Pre-deployment checks
├── .gitignore                      # Git exclusions
└── replit.md                       # This file
```

## Python Dependencies

### Core Libraries
- discord.py>=2.6.4 - Discord API
- groq==0.18.0 - AI API client
- firebase-admin==6.5.0 - Database
- flask>=3.1.2 - Web server

### Voice & Audio
- edge-tts>=7.0.0 - Advanced TTS
- gtts==2.5.4 - Google TTS
- pydub==0.25.1 - Audio processing
- SpeechRecognition==3.14.2 - Voice input
- PyNaCl==1.5.0 - Voice encryption

### System Dependencies (via Dockerfile/Aptfile)
- ffmpeg - Audio processing
- libopus0, libopus-dev - Opus codec
- libsodium23, libsodium-dev - Crypto
- portaudio19-dev - Audio I/O

## Testing & Verification

### Local Testing (Replit)
1. All dependencies automatically installed via pyproject.toml
2. Bot runs with Flask keep-alive on port 5000
3. Voice features fully functional

### Deployment Testing (Render)
1. Run `python verify_deployment.py`
2. Check Docker build logs
3. Verify health check endpoint: `curl http://localhost:5000/`
4. Test voice connection in Discord

## Known Limitations

- Voice features require libopus (automatically installed)
- Firebase credentials must be provided as JSON string in environment variables
- Temp audio files cleaned up automatically after playback
- Rate limiting in place for Discord API compliance

## User Preferences

- Preferred communication: Simple, everyday language
- Focus: Discord bot with full voice capabilities
- Target platform: Docker deployment on Render
- Database: Firebase Firestore (production mode)

## Notes

- Bot requires admin permissions for g!status and other admin commands
- Bot automatically formats member nicknames based on roles
- Maintenance mode can be toggled to disable automated greetings
- All 37 commands verified working as of October 28, 2025
- Voice connections use Opus encoding for optimal Discord compatibility
