# GNSLG Discord Bot Project

## Overview

A comprehensive Discord bot called "GNSLG Bot" that provides AI-powered chat responses in Tagalog, voice message processing, automated greetings, gaming features, and Discord server management capabilities. This project was cloned from https://github.com/draiimon/gnslgbot2 with the g!status command functionality preserved.

## User Preferences

- Preferred communication style: Simple, everyday language
- Prefers minimal web interfaces - just status pages
- Wants all Discord commands to be fully functional
- Uses Tagalog for bot interactions
- Wanted to clone the repository and keep only the g!status command

## System Architecture

### Core Components
- **Discord Bot**: Main bot application using discord.py
- **AI Integration**: Groq API with DeepSeek R1 model for Tagalog responses
- **Database**: Firebase Firestore for user data and conversation history
- **Voice Processing**: Text-to-speech and speech recognition capabilities
- **Web Interface**: Simple Flask app showing bot status
- **Scheduled Tasks**: Automated greetings at 8 AM and 10 PM

### Technical Stack
- **Backend**: Python with Flask and discord.py
- **AI Model**: Groq API with DeepSeek R1 Distill LLama 70B
- **Database**: Firebase Firestore (production mode)
- **Voice**: gTTS for text-to-speech, edge-tts for advanced TTS
- **Deployment**: Replit with Flask keep-alive server

## Key Features

### Discord Bot Commands
- **AI Chat**: `g!usap`, `g!ask`, `g!asklog` - Chat with AI in Tagalog
- **Gaming**: `g!daily`, `g!balance`, `g!toss`, `g!blackjack`, `g!give` - Virtual economy
- **Voice**: `g!joinvc`, `g!vc`, `g!listen`, `g!autotts` - Voice interaction
- **Utility**: `g!tulong`, `g!view`, `g!leaderboard` - Help and info
- **Admin**: `g!admin`, `g!announcement`, `g!maintenance`, `g!status` - Server management

### Admin Commands
- **g!status** - Set or view the bot's custom status message (admin only)
  - `g!status` - View current status
  - `g!status <message>` - Set new status
- **g!maintenance** - Toggle maintenance mode
- **g!set_words** - Manage banned words with custom actions
- **g!roles** - Configure role emoji mappings
- **g!clear_messages** - Remove all bot messages from a channel

### Automated Features
- **Greetings**: Automated good morning (8 AM) and good night (10 PM) messages
- **Nickname Management**: Automatic nickname formatting with role-based emojis
- **Profanity Filter**: Custom banned words with muting/disconnection actions
- **Rate Limiting**: Anti-spam protection for commands

## Recent Changes

### October 28, 2025
- ✅ Cloned repository from https://github.com/draiimon/gnslgbot2
- ✅ Deleted all previous Node.js bot files
- ✅ Replaced with Python-based Discord bot
- ✅ Added g!status command to the Python bot (admin only)
- ✅ Fixed cog registration to use await for universal compatibility
- ✅ Updated workflow to run Python bot with Flask keep-alive
- ✅ Installed all required Python packages

## External Dependencies

### Required API Keys
- `DISCORD_TOKEN` - Bot authentication
- `GROQ_API_KEY` - AI model access
- `FIREBASE_CREDENTIALS` - Database connection (JSON format)

### Python Libraries
- discord.py - Discord API integration
- groq - AI model API client
- firebase-admin - Database management
- flask - Web interface
- gtts - Text-to-speech
- edge-tts - Advanced text-to-speech
- psutil - System monitoring
- All other dependencies in render_requirements.txt

## Deployment Strategy

- **Platform**: Replit with Python runtime
- **Port**: 5000 (Flask web interface for keep-alive)
- **Background Process**: Discord bot runs with Flask in separate thread
- **Database**: Firebase Firestore (cloud-hosted)
- **Monitoring**: Flask endpoint returns "✅ Bot is running!"

## File Structure

```
.
├── bot/
│   ├── __init__.py
│   ├── cog.py              # Main command handlers and bot logic
│   ├── config.py           # Configuration settings
│   ├── firebase_db.py      # Firebase database integration
│   ├── rate_limiter.py     # Rate limiting utilities
│   ├── runtime_config.py   # Runtime environment detection
│   ├── speech_recognition_cog.py  # Voice command handlers
│   └── status_monitor.py   # Bot status monitoring
├── templates/
│   └── index.html          # Web interface template
├── main.py                 # Bot entry point
├── render_requirements.txt # Python dependencies
└── replit.md              # This file
```

## Notes

- The g!status command was specifically preserved from the previous implementation
- Bot requires admin permissions to use g!status and other admin commands
- Firebase credentials must be provided as a JSON string in environment variable
- Bot automatically formats member nicknames based on roles
- Maintenance mode can be toggled to disable automated greetings
