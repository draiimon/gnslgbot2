#!/bin/bash

# Script to create a clean repository without sensitive data
echo "🧹 Creating clean repository for GitHub..."

# Remove existing git directory completely
rm -rf .git

# Initialize new git repository
git init

# Configure git user (optional but recommended)
git config user.name "draiimon" 
git config user.email "your-email@example.com"

# Add remote repository
git remote add origin https://draiimon:$GITHUB_PERSONAL_ACCESS_TOKEN@github.com/draiimon/gnslgbot2.git

# Ensure sensitive files are ignored
echo "🔒 Ensuring sensitive files are ignored..."
if [ ! -f ".gitignore" ]; then
    echo "Creating .gitignore file..."
    cat > .gitignore << 'EOF'
# Credentials and sensitive files
firebase-credentials.json
.env
.env.local
.env.development.local
.env.test.local
.env.production.local
*.pem
*.key
*.crt

# Python cache
__pycache__/
*.py[cod]
*$py.class
*.so

# Audio files
temp_audio/
*.wav
*.mp3
*.ogg

# Logs
logs/
*.log

# Temporary files
*.tmp
*.temp
.DS_Store
Thumbs.db

# Backup files
*.bak
*.backup
EOF
fi

# Remove any existing sensitive files
echo "🗑️ Removing sensitive files..."
rm -f firebase-credentials.json
rm -f .env
rm -f *.pem
rm -f *.key
rm -f *.crt

# Add all files to staging
echo "📦 Adding files to git..."
git add .

# Create initial commit
echo "💾 Creating initial commit..."
git commit -m "Initial commit: Discord bot ready for Render deployment"

# Push to GitHub
echo "🚀 Pushing to GitHub..."
git push -u origin main

echo "✅ Repository created successfully!"
echo "🔗 Repository URL: https://github.com/draiimon/gnslgbot2"