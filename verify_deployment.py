#!/usr/bin/env python3
"""
GNSLG Bot - Deployment Verification Script
Checks that all dependencies and configurations are ready for Render deployment
"""

import os
import sys
import importlib.util

def check_file_exists(filepath, description):
    """Check if a required file exists"""
    if os.path.exists(filepath):
        print(f"✅ {description}: {filepath}")
        return True
    else:
        print(f"❌ MISSING {description}: {filepath}")
        return False

def check_env_var(var_name):
    """Check if an environment variable is set"""
    if os.getenv(var_name):
        print(f"✅ Environment variable set: {var_name}")
        return True
    else:
        print(f"⚠️  Environment variable not set: {var_name}")
        return False

def check_python_package(package_name):
    """Check if a Python package is installed"""
    spec = importlib.util.find_spec(package_name)
    if spec is not None:
        print(f"✅ Python package installed: {package_name}")
        return True
    else:
        print(f"❌ Python package missing: {package_name}")
        return False

def main():
    print("=" * 60)
    print("🚀 GNSLG Discord Bot - Deployment Verification")
    print("=" * 60)
    print()
    
    all_checks_passed = True
    
    # Check required files
    print("📁 Checking Required Files...")
    required_files = [
        ("Dockerfile", "Docker configuration"),
        ("render_requirements.txt", "Python dependencies"),
        ("main.py", "Bot entry point"),
        ("bot/cog.py", "Chat cog"),
        ("bot/speech_recognition_cog.py", "Speech cog"),
        ("bot/firebase_db.py", "Database module"),
        ("bot/config.py", "Configuration"),
        (".gitignore", "Git ignore file"),
    ]
    
    for filepath, description in required_files:
        if not check_file_exists(filepath, description):
            all_checks_passed = False
    print()
    
    # Check environment variables
    print("🔐 Checking Environment Variables...")
    env_vars = [
        "DISCORD_TOKEN",
        "GROQ_API_KEY",
        "FIREBASE_CREDENTIALS"
    ]
    
    for var in env_vars:
        if not check_env_var(var):
            all_checks_passed = False
    print()
    
    # Check critical Python packages
    print("📦 Checking Python Packages...")
    critical_packages = [
        "discord",
        "flask",
        "groq",
        "firebase_admin",
    ]
    
    for package in critical_packages:
        if not check_python_package(package):
            all_checks_passed = False
    print()
    
    # Check optional audio packages
    print("🔊 Checking Audio Packages (Optional)...")
    audio_packages = ["edge_tts", "gtts", "pydub", "speech_recognition"]
    audio_available = all(importlib.util.find_spec(pkg) for pkg in audio_packages)
    
    if audio_available:
        print("✅ All audio packages available")
    else:
        print("⚠️  Some audio packages missing (voice features may be limited)")
    print()
    
    # Check directories
    print("📂 Checking Directories...")
    required_dirs = ["bot", "templates", "temp_audio", "logs"]
    for dirname in required_dirs:
        if os.path.exists(dirname):
            print(f"✅ Directory exists: {dirname}")
        else:
            print(f"⚠️  Directory missing (will be created): {dirname}")
            os.makedirs(dirname, exist_ok=True)
            print(f"   Created: {dirname}")
    print()
    
    # Final summary
    print("=" * 60)
    if all_checks_passed:
        print("✅ ALL CRITICAL CHECKS PASSED - READY FOR DEPLOYMENT")
    else:
        print("❌ SOME CHECKS FAILED - PLEASE FIX BEFORE DEPLOYING")
        sys.exit(1)
    print("=" * 60)
    
    return 0 if all_checks_passed else 1

if __name__ == "__main__":
    sys.exit(main())
