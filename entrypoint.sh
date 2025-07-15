#!/bin/bash
set -e

echo "========== GNSLG BOT DOCKER STARTUP =========="
echo "Starting Docker container initialization..."

# Create temp directories if they don't exist
mkdir -p /app/temp_audio
chmod 755 -R /app/temp_audio
echo "✅ Created temp directories"

# Check environment variables
echo "🔍 Checking environment variables..."
if [ -z "$DISCORD_TOKEN" ]; then
    echo "❌ ERROR: DISCORD_TOKEN environment variable is not set! Bot cannot start."
    exit 1
else
    echo "✅ DISCORD_TOKEN is set"
fi

if [ -z "$GROQ_API_KEY" ]; then
    echo "⚠️ WARNING: GROQ_API_KEY is not set. AI responses won't work."
else
    echo "✅ GROQ_API_KEY is set"
fi

# Check if Firebase credentials provided as env var
if [ ! -z "$FIREBASE_CREDENTIALS" ]; then
    echo "🔄 Creating Firebase credentials file from environment variable..."
    echo "$FIREBASE_CREDENTIALS" > /app/firebase-credentials.json
    chmod 600 /app/firebase-credentials.json
    echo "✅ Firebase credentials file created successfully at /app/firebase-credentials.json"
    # Validate JSON format with jq if available
    if command -v jq >/dev/null 2>&1; then
        if cat /app/firebase-credentials.json | jq . >/dev/null 2>&1; then
            echo "✅ Firebase credentials JSON format verified"
        else
            echo "⚠️ WARNING: Firebase credentials don't appear to be valid JSON. Check your FIREBASE_CREDENTIALS value."
        fi
    fi
else
    echo "⚠️ WARNING: No Firebase credentials found in environment variables"
fi

# Check for port
if [ -z "$PORT" ]; then
    export PORT=5000
    echo "✅ Setting default PORT to 5000"
else
    echo "✅ Using PORT: $PORT"
fi

# Set Render flags
export RENDER=true
echo "✅ RENDER environment variable set to true"

# Debug information
echo "📊 System information:"
python --version
echo "📁 Current directory: $(pwd)"
echo "📁 Directory listing:"
ls -la

# Set trap to handle graceful shutdown
trap "echo '🛑 Received termination signal'; exit 0" SIGTERM SIGINT

# Clean up any previous Firebase installs (prevent multiple instances)
if [ -f "/app/firebase-credentials.json" ]; then
    echo "🔍 Checking for running Firebase instances..."
    # Try to use lsof to check if firebase is already in use
    if command -v lsof >/dev/null 2>&1; then
        if lsof | grep -i firebase > /dev/null; then
            echo "⚠️ Previous Firebase instance detected. Will use existing connection."
        fi
    fi
fi

# Clean up Python cache files to prevent stale code
echo "🧹 Cleaning Python cache files for fresh start"
find /app -type d -name "__pycache__" -exec rm -rf {} +
find /app -name "*.pyc" -delete

echo "Starting GNSLG Bot in Docker container"
echo "✅ Starting bot with all configurations set"
# Start the discord bot
echo "🚀 Starting Discord bot..."
echo "================================================"
exec python main.py