# GNSLG Discord Bot - Optimized Docker Configuration
FROM python:3.11-slim

# Environment variables for build configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RENDER=true \
    DISABLE_PYAUDIO=false \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies in organized layers for better caching
# Layer 1: Essential build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Layer 2: Audio libraries for voice/TTS support
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libopus-dev \
    libsodium23 \
    libsodium-dev \
    libportaudio2 \
    portaudio19-dev \
    libasound-dev \
    libpulse0 \
    && rm -rf /var/lib/apt/lists/*

# Layer 3: Crypto and security libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    libnacl-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create required directories
RUN mkdir -p /app/temp_audio /app/logs /app/bot /app/templates && \
    chmod 755 /app/temp_audio /app/logs

# Copy and install Python dependencies
COPY render_requirements.txt .

# Install Python packages with proper ordering
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir pynacl==1.5.0 && \
    pip install --no-cache-dir pyaudio==0.2.14 && \
    pip install --no-cache-dir -r render_requirements.txt

# Copy application files
COPY . .

# Set permissions
RUN chmod +x prestart.sh entrypoint.sh 2>/dev/null || true && \
    chmod 755 -R /app/temp_audio /app/logs

# Health check for container monitoring
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Entrypoint script for proper initialization
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "🚀 Starting GNSLG Discord Bot"\n\
echo "================================"\n\
\n\
# Firebase credentials setup\n\
if [ ! -z "$FIREBASE_CREDENTIALS" ]; then\n\
    echo "$FIREBASE_CREDENTIALS" > /app/firebase-credentials.json\n\
    chmod 600 /app/firebase-credentials.json\n\
    echo "✅ Firebase credentials configured"\n\
else\n\
    echo "⚠️  WARNING: FIREBASE_CREDENTIALS not set"\n\
fi\n\
\n\
# Clean Python cache\n\
echo "🧹 Cleaning Python cache..."\n\
find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true\n\
find /app -name "*.pyc" -delete 2>/dev/null || true\n\
\n\
# Verify voice dependencies\n\
echo "🔊 Checking voice dependencies..."\n\
if command -v ffmpeg &> /dev/null; then\n\
    echo "✅ ffmpeg installed"\n\
fi\n\
if ldconfig -p | grep -q libopus; then\n\
    echo "✅ libopus installed"\n\
fi\n\
if ldconfig -p | grep -q libsodium; then\n\
    echo "✅ libsodium installed"\n\
fi\n\
\n\
# Signal handling\n\
trap "echo \"🛑 Received termination signal\"; exit 0" SIGTERM SIGINT\n\
\n\
# Start the bot\n\
echo "✅ Starting Discord bot..."\n\
echo "================================"\n\
exec python main.py\n\
' > /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

# Use the entrypoint script
ENTRYPOINT ["/app/docker-entrypoint.sh"]
