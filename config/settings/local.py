# config/settings/local.py
"""
Local development settings.
Set DJANGO_SETTINGS_MODULE=config.settings.local
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from .base import *  # noqa: E402, F401, F403  # standard Django settings inheritance

DEBUG = True

# Allow all hosts in local dev
ALLOWED_HOSTS = ["*"]

# Allow HTTP for Google OAuth in local dev only
# WARNING: never set this in production
if os.getenv("OAUTHLIB_INSECURE_TRANSPORT") == "1":
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# CORS — allow everything in dev
CORS_ALLOW_ALL_ORIGINS = True

# Use a fast password hasher in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
