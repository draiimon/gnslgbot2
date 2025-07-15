# GNSLG Discord Bot Project

## Overview

A comprehensive Discord bot called "GNSLG Bot" that provides AI-powered chat responses in Tagalog, voice message processing, automated greetings, gaming features, and Discord server management capabilities.

## User Preferences

- Preferred communication style: Simple, everyday language
- Prefers minimal web interfaces - just status pages
- Wants all Discord commands to be fully functional
- Uses Tagalog for bot interactions

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
- **Voice**: gTTS for text-to-speech, PyAudio for voice processing
- **Deployment**: Replit with gunicorn server

## Key Features

### Discord Bot Commands (36 total)
- **AI Chat**: `g!usap`, `g!ask`, `g!asklog` - Chat with AI in Tagalog
- **Gaming**: `g!daily`, `g!balance`, `g!toss`, `g!blackjack`, `g!give` - Virtual economy
- **Voice**: `g!joinvc`, `g!vc`, `g!listen`, `g!autotts` - Voice interaction
- **Utility**: `g!tulong`, `g!view`, `g!leaderboard`, `g!rules` - Help and info
- **Admin**: `g!admin`, `g!announcement`, `g!maintenance` - Server management

### Automated Features
- **Greetings**: Automated good morning (8 AM) and good night (10 PM) messages
- **Nickname Management**: Automatic nickname formatting with role-based emojis
- **Profanity Filter**: Custom banned words with muting/disconnection actions
- **Rate Limiting**: Anti-spam protection for commands

## Recent Changes

### July 15, 2025
- ✅ Fixed command registration issue - all 36 commands now working
- ✅ Simplified web interface to show "Bot is live now!" status only
- ✅ Discord bot successfully connecting and responding to commands
- ✅ Firebase database working in production mode
- ✅ Voice features enabled and functional

## External Dependencies

### Required API Keys
- `DISCORD_TOKEN` - Bot authentication
- `GROQ_API_KEY` - AI model access
- `FIREBASE_CREDENTIALS` - Database connection

### Python Libraries
- discord.py - Discord API integration
- groq - AI model API client
- firebase-admin - Database management
- flask - Web interface
- gtts - Text-to-speech
- pyaudio - Voice processing

## Deployment Strategy

- **Platform**: Replit with gunicorn server
- **Port**: 5000 (Flask web interface)
- **Background Process**: Discord bot runs in separate thread
- **Database**: Firebase Firestore (cloud-hosted)
- **Monitoring**: Web interface shows bot status