#!/usr/bin/env python3
"""
GNSLG Bot - Deployment Verification Script
Checks that all dependencies and configurations are ready for deployment.
"""

import importlib.util
import os
import sys

from dotenv import load_dotenv


load_dotenv()


def check_file_exists(filepath, description):
    """Check if a required file exists."""
    if os.path.exists(filepath):
        print(f"[OK] {description}: {filepath}")
        return True

    print(f"[MISSING] {description}: {filepath}")
    return False


def check_env_var(var_name):
    """Check if an environment variable is set."""
    if os.getenv(var_name):
        print(f"[OK] Environment variable set: {var_name}")
        return True

    print(f"[WARN] Environment variable not set: {var_name}")
    return False


def check_python_package(package_name):
    """Check if a Python package is installed."""
    spec = importlib.util.find_spec(package_name)
    if spec is not None:
        print(f"[OK] Python package installed: {package_name}")
        return True

    print(f"[MISSING] Python package missing: {package_name}")
    return False


def main():
    print("=" * 60)
    print("GNSLG Discord Bot - Deployment Verification")
    print("=" * 60)
    print()

    all_checks_passed = True

    print("Checking Required Files...")
    required_files = [
        ("Dockerfile", "Docker configuration"),
        ("render_requirements.txt", "Python dependencies"),
        ("main.py", "Bot entry point"),
        ("bot/cog.py", "Chat cog"),
        ("bot/speech_recognition_cog.py", "Speech cog"),
        ("bot/postgres_db.py", "Database module"),
        ("bot/config.py", "Configuration"),
        (".gitignore", "Git ignore file"),
    ]

    for filepath, description in required_files:
        if not check_file_exists(filepath, description):
            all_checks_passed = False
    print()

    print("Checking Environment Variables...")
    env_vars = [
        "DISCORD_TOKEN",
        "GROQ_API_KEY",
        "DATABASE_URL",
    ]

    for var in env_vars:
        if not check_env_var(var):
            all_checks_passed = False
    print()

    print("Checking Python Packages...")
    critical_packages = [
        "discord",
        "flask",
        "groq",
        "psycopg2",
    ]

    for package in critical_packages:
        if not check_python_package(package):
            all_checks_passed = False
    print()

    print("Checking Audio Packages (Optional)...")
    audio_packages = ["edge_tts", "gtts", "pydub", "speech_recognition"]
    audio_available = all(importlib.util.find_spec(pkg) for pkg in audio_packages)

    if audio_available:
        print("[OK] All audio packages available")
    else:
        print("[WARN] Some audio packages missing (voice features may be limited)")
    print()

    print("Checking Directories...")
    required_dirs = ["bot", "templates", "temp_audio", "logs"]
    for dirname in required_dirs:
        if os.path.exists(dirname):
            print(f"[OK] Directory exists: {dirname}")
        else:
            print(f"[WARN] Directory missing (will be created): {dirname}")
            os.makedirs(dirname, exist_ok=True)
            print(f"   Created: {dirname}")
    print()

    print("=" * 60)
    if all_checks_passed:
        print("[OK] ALL CRITICAL CHECKS PASSED - READY FOR DEPLOYMENT")
    else:
        print("[FAIL] SOME CHECKS FAILED - PLEASE FIX BEFORE DEPLOYING")
        sys.exit(1)
    print("=" * 60)

    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    sys.exit(main())
