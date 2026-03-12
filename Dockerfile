FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RENDER=true \
    DISABLE_PYAUDIO=false \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    git \
    curl \
    ffmpeg \
    libopus0 \
    libopus-dev \
    libsodium23 \
    libsodium-dev \
    libportaudio2 \
    portaudio19-dev \
    libasound-dev \
    libpulse0 \
    libffi-dev \
    libnacl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app/temp_audio /app/logs /app/bot /app/templates && \
    chmod 755 /app/temp_audio /app/logs

COPY render_requirements.txt .

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir pynacl==1.5.0 && \
    pip install --no-cache-dir pyaudio==0.2.14 && \
    pip install --no-cache-dir -r render_requirements.txt

COPY . .

RUN chmod 755 -R /app/temp_audio /app/logs

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ping || exit 1

RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "Starting GNSLG Discord Bot"\n\
echo "================================"\n\
\n\
echo "Cleaning Python cache..."\n\
find /app -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true\n\
find /app -name "*.pyc" -delete 2>/dev/null || true\n\
\n\
echo "Checking voice dependencies..."\n\
if command -v ffmpeg &> /dev/null; then\n\
    echo "ffmpeg installed"\n\
fi\n\
if ldconfig -p | grep -q libopus; then\n\
    echo "libopus installed"\n\
fi\n\
if ldconfig -p | grep -q libsodium; then\n\
    echo "libsodium installed"\n\
fi\n\
\n\
trap "echo \"Received termination signal\"; exit 0" SIGTERM SIGINT\n\
\n\
echo "Starting Discord bot..."\n\
echo "================================"\n\
exec python main.py\n\
' > /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
