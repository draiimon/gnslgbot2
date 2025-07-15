FROM python:3.11-slim

# Set environment variables early for build configuration
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RENDER=true
ENV DISABLE_PYAUDIO=false

WORKDIR /app

# Install system dependencies including audio libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libportaudio2 \
    portaudio19-dev \
    libasound-dev \
    libpulse0 \
    libffi-dev \
    libnacl-dev \
    build-essential \
    python3-dev \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create directories first
RUN mkdir -p /app/temp_audio && \
    mkdir -p /app/logs

# Copy requirements file
COPY render_requirements.txt .

# Install PyAudio first since it requires special handling
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir pyaudio==0.2.14 && \
    pip install --no-cache-dir -r render_requirements.txt

# Copy project files 
COPY . .

# Set correct permissions and prepare any necessary files
RUN chmod +x prestart.sh && \
    chmod 755 -R /app/temp_audio

# Health check to verify the container is running properly
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Create entrypoint script for proper initialization and signal handling
RUN echo '#!/bin/bash\n\
echo "Starting GNSLG Bot in Docker container"\n\
\n\
# Handle Firebase credentials setup\n\
if [ ! -z "$FIREBASE_CREDENTIALS" ]; then\n\
    echo "$FIREBASE_CREDENTIALS" > firebase-credentials.json\n\
    chmod 600 firebase-credentials.json\n\
    echo "✅ Created Firebase credentials file"\n\
else\n\
    echo "⚠️ WARNING: FIREBASE_CREDENTIALS not set"\n\
fi\n\
\n\
# Clean up any previous Python cache to prevent stale modules\n\
echo "🧹 Cleaning Python cache files for fresh start"\n\
find /app -type d -name "__pycache__" -exec rm -rf {} +\n\
find /app -name "*.pyc" -delete\n\
\n\
# Trap SIGTERM and SIGINT\n\
trap "echo Received termination signal; exit 0" SIGTERM SIGINT\n\
\n\
# Start the application\n\
echo "✅ Starting bot with all configurations set"\n\
python main.py\n\
' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Run the entrypoint script to handle initialization properly
CMD ["/app/entrypoint.sh"]