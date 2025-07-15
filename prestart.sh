#!/bin/bash

# Check for temp_audio directory and create if not exists
mkdir -p temp_audio

# Check if Firebase credentials environment variable exists and create file if it does
if [ ! -z "$FIREBASE_CREDENTIALS" ]; then
  echo "Creating firebase-credentials.json from environment variable"
  echo "$FIREBASE_CREDENTIALS" > firebase-credentials.json
  chmod 600 firebase-credentials.json
fi

# Install system dependencies if Aptfile exists
if [ -f Aptfile ]; then
  echo "Installing system dependencies from Aptfile"
  apt-get update
  apt-get install -y $(cat Aptfile)
fi