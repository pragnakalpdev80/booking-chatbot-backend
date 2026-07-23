# config/celery.py
"""
Celery application instance for the calendar-chatbot project.
Import this in config/__init__.py to ensure tasks are auto-discovered.
"""

import os
from typing import Any

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("calendar_chatbot")

# Read Celery config from Django settings using the CELERY_ namespace
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks from all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self: Any) -> None:
    print(f"Request: {self.request!r}")
