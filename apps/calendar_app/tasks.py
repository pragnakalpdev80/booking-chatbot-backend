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


def _get_service(provider_user_id: int):
    """Build an authenticated Google Calendar service using the provider's credential."""
    from .models import GoogleCredential

    credential = GoogleCredential.objects.select_related("user").get(user_id=provider_user_id)
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


@shared_task(bind=True, **_RETRY_KWARGS)
def task_insert_event(
    self, event_body: dict, provider_user_id: int, calendar_id: str = "primary"
) -> dict:
    """
    Insert a new event on the doctor's calendar.
    Returns the created event dict (including id and htmlLink).
    """
    try:
        service = _get_service(provider_user_id)
        event = service.events().insert(calendarId=calendar_id, body=event_body).execute()
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
        logger.exception("task_insert_event: non-retryable HttpError %s", exc)
        raise


@shared_task(bind=True, **_RETRY_KWARGS)
def task_patch_event(
    self, event_id: str, patch_body: dict, provider_user_id: int, calendar_id: str = "primary"
) -> dict:
    """
    Patch (partial update) an existing event on the doctor's calendar.
    """
    try:
        service = _get_service(provider_user_id)
        event = (
            service.events()
            .patch(calendarId=calendar_id, eventId=event_id, body=patch_body)
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
        logger.exception("task_patch_event: non-retryable HttpError %s for event %s", exc, event_id)
        raise


@shared_task(bind=True, **_RETRY_KWARGS)
def task_cancel_event(
    self, event_id: str, provider_user_id: int, calendar_id: str = "primary"
) -> None:
    """
    Delete an event from the doctor's calendar.
    Idempotent: 410 Gone is treated as success.
    """
    try:
        service = _get_service(provider_user_id)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
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
        logger.exception(
            "task_cancel_event: non-retryable HttpError %s for event %s", exc, event_id
        )
        raise


@shared_task
def cleanup_expired_locks() -> None:
    """
    Delete expired, unconfirmed SlotLock records.
    Runs periodically via Celery Beat.
    """
    from django.utils.timezone import now

    from .models import SlotLock

    deleted_count, _ = SlotLock.objects.filter(expires_at__lte=now(), is_confirmed=False).delete()

    if deleted_count > 0:
        logger.info("cleanup_expired_locks: deleted %d expired lock(s).", deleted_count)
