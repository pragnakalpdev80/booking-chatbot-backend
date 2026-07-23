# calendar_app/tasks.py
"""
Celery tasks for async Google Calendar write operations.

All tasks use exponential backoff retry on HttpError 429/503.
Read operations (events.list, freebusy) are NOT routed through Celery.
"""

import logging

from celery import shared_task
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Retry on quota / server errors — up to 5 attempts with exponential backoff
_RETRY_KWARGS = {
    "max_retries": 5,
    "default_retry_delay": 10,  # seconds; doubles each retry (countdown= in self.retry)
}

RETRYABLE_STATUS_CODES = {429, 503, 500}


def _get_service():
    """Build an authenticated Google Calendar service using the single credential."""
    from .models import GoogleCredential

    credential = GoogleCredential.objects.select_related("user").get()
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


@shared_task(bind=True, **_RETRY_KWARGS)
def task_insert_event(self, event_body: dict) -> dict:
    """
    Insert a new event on the doctor's primary calendar.
    Returns the created event dict (including id and htmlLink).
    """
    try:
        service = _get_service()
        event = service.events().insert(calendarId="primary", body=event_body).execute()
        logger.info("task_insert_event: created event %s", event.get("id"))
        return event
    except HttpError as exc:
        if exc.resp.status in RETRYABLE_STATUS_CODES:
            delay = (2**self.request.retries) * 10
            logger.warning(
                "task_insert_event: retryable error %s (attempt %d), retrying in %ds",
                exc.resp.status,
                self.request.retries + 1,
                delay,
            )
            raise self.retry(exc=exc, countdown=delay) from exc
        logger.error("task_insert_event: non-retryable HttpError %s", exc)
        raise


@shared_task(bind=True, **_RETRY_KWARGS)
def task_patch_event(self, event_id: str, patch_body: dict) -> dict:
    """
    Patch (partial update) an existing event on the doctor's primary calendar.
    """
    try:
        service = _get_service()
        event = (
            service.events()
            .patch(calendarId="primary", eventId=event_id, body=patch_body)
            .execute()
        )
        logger.info("task_patch_event: patched event %s", event_id)
        return event
    except HttpError as exc:
        if exc.resp.status in RETRYABLE_STATUS_CODES:
            delay = (2**self.request.retries) * 10
            logger.warning(
                "task_patch_event: retryable error %s (attempt %d), retrying in %ds",
                exc.resp.status,
                self.request.retries + 1,
                delay,
            )
            raise self.retry(exc=exc, countdown=delay) from exc
        logger.error("task_patch_event: non-retryable HttpError %s for event %s", exc, event_id)
        raise


@shared_task(bind=True, **_RETRY_KWARGS)
def task_cancel_event(self, event_id: str) -> None:
    """
    Delete an event from the doctor's primary calendar.
    Idempotent: 410 Gone is treated as success.
    """
    try:
        service = _get_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        logger.info("task_cancel_event: deleted event %s", event_id)
    except HttpError as exc:
        if exc.resp.status == 410:
            # Already deleted — treat as success
            logger.info("task_cancel_event: event %s already gone (410)", event_id)
            return
        if exc.resp.status in RETRYABLE_STATUS_CODES:
            delay = (2**self.request.retries) * 10
            logger.warning(
                "task_cancel_event: retryable error %s (attempt %d), retrying in %ds",
                exc.resp.status,
                self.request.retries + 1,
                delay,
            )
            raise self.retry(exc=exc, countdown=delay) from exc
        logger.error("task_cancel_event: non-retryable HttpError %s for event %s", exc, event_id)
        raise
