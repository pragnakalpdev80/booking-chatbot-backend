# config/__init__.py
# Expose Celery app so Django's app registry picks up tasks automatically
from .celery import app as celery_app

__all__ = ("celery_app",)
