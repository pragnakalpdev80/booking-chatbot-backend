# config/settings/production.py
"""
Production settings.
Set DJANGO_SETTINGS_MODULE=config.settings.production
All secrets must come from environment variables — never from a .env file.
"""
from .base import *  # noqa: F401, F403

DEBUG = False

# ─── Security headers ────────────────────────────────────────────────────────
SECURE_HSTS_SECONDS = 31536000          # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ─── Content Security Policy ──────────────────────────────────────────────────
# Tighten CSP once a frontend is introduced.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ─── Static files (production) ────────────────────────────────────────────────
STATICFILES_STORAGE = "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"
