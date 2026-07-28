# calendar_app/tasks.py
"""
Celery tasks for async Google Calendar write operations.

All tasks use exponential backoff retry on HttpError 429/503.
Read operations (events.list, freebusy) are NOT routed through Celery.
"""

import logging
from datetime import UTC, timedelta

from celery import shared_task
from django.utils.timezone import now
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
    from .models import SlotLock

    deleted_count, _ = SlotLock.objects.filter(expires_at__lte=now(), is_confirmed=False).delete()

    if deleted_count > 0:
        logger.info("cleanup_expired_locks: deleted %d expired lock(s).", deleted_count)


def invalidate_freebusy_cache(provider_id: int, calendar_id: str, target_date: str) -> None:
    """
    Invalidate the Redis freebusy cache for a specific provider/date combination.

    Call this whenever a booking is created, rescheduled, or cancelled so the
    next availability request reflects the latest state from Google Calendar.

    Args:
        provider_id: Primary key of the provider (User).
        calendar_id: Google Calendar ID (e.g. "primary").
        target_date:  ISO-8601 date string (YYYY-MM-DD).
    """
    from django.core.cache import cache

    cache_key = f"freebusy_{provider_id}_{calendar_id}_{target_date}"
    cache.delete(cache_key)
    logger.debug(
        "invalidate_freebusy_cache: cleared key %s for provider %s",
        cache_key,
        provider_id,
    )


@shared_task
def reconcile_bookings_with_gcal() -> None:
    """
    Nightly drift-reconciliation task.

    Iterates over every CONFIRMED booking in the next 7 days and verifies
    it still exists in Google Calendar with the same start/end times.

    Actions taken:
    - If the Google event no longer exists (404) → mark booking CANCELLED.
    - If the Google event time drifted        → update DB start/end times.

    Only READ operations are performed against the Google Calendar API.
    This task must be registered in CELERY_BEAT_SCHEDULE and run nightly.
    """
    from .models import Booking, BookingStatus, ProviderSettings

    window_end = now() + timedelta(days=7)
    upcoming = Booking.objects.filter(
        status=BookingStatus.CONFIRMED,
        start_time__gte=now(),
        start_time__lte=window_end,
    ).select_related("provider")

    logger.info("reconcile_bookings_with_gcal: checking %d upcoming booking(s).", upcoming.count())

    for booking in upcoming:
        if booking.provider is None:
            logger.warning(
                "reconcile_bookings_with_gcal: booking %s has no provider — skipping.",
                booking.pk,
            )
            continue

        assert booking.provider_id is not None, "Booking has no provider_id despite provider check"
        try:
            service = _get_service(booking.provider_id)
            ps = ProviderSettings.get_for_provider(booking.provider)
            event = (
                service.events()
                .get(calendarId=ps.calendar_id, eventId=booking.google_event_id)
                .execute()
            )
        except HttpError as exc:
            if exc.resp.status == 404:
                # Event was deleted directly in Google Calendar.
                logger.warning(
                    "reconcile_bookings_with_gcal: event %s not found in Google Calendar — "
                    "marking booking %s as CANCELLED.",
                    booking.google_event_id,
                    booking.pk,
                )
                booking.status = BookingStatus.CANCELLED
                booking.save(update_fields=["status", "updated_at"])
                assert booking.provider_id is not None
                invalidate_freebusy_cache(
                    booking.provider_id,
                    ps.calendar_id,
                    booking.start_time.date().isoformat(),
                )
            else:
                logger.error(
                    "reconcile_bookings_with_gcal: HttpError %s checking event %s — skipping.",
                    exc.resp.status,
                    booking.google_event_id,
                )
            continue
        except RuntimeError:
            logger.exception(
                "reconcile_bookings_with_gcal: could not build service for provider %s — skipping.",
                booking.provider_id,
            )
            continue

        # Compare times — Google returns ISO 8601 with timezone offset
        gcal_start_str = event.get("start", {}).get("dateTime")
        gcal_end_str = event.get("end", {}).get("dateTime")
        if not gcal_start_str or not gcal_end_str:
            continue

        try:
            gcal_start = now().__class__.fromisoformat(gcal_start_str).astimezone(UTC)
            gcal_end = now().__class__.fromisoformat(gcal_end_str).astimezone(UTC)
        except ValueError:
            logger.warning(
                "reconcile_bookings_with_gcal: could not parse datetimes for event %s — skipping.",
                booking.google_event_id,
            )
            continue

        db_start = booking.start_time.astimezone(UTC)
        db_end = booking.end_time.astimezone(UTC)

        if gcal_start != db_start or gcal_end != db_end:
            logger.warning(
                "reconcile_bookings_with_gcal: time drift detected for booking %s — "
                "DB has %s/%s, Google has %s/%s. Updating DB.",
                booking.pk,
                db_start.isoformat(),
                db_end.isoformat(),
                gcal_start.isoformat(),
                gcal_end.isoformat(),
            )
            old_date = booking.start_time.date().isoformat()
            booking.start_time = gcal_start
            booking.end_time = gcal_end
            booking.save(update_fields=["start_time", "end_time", "updated_at"])
            # Invalidate cache for both old and new date (in case date changed).
            assert booking.provider_id is not None
            invalidate_freebusy_cache(booking.provider_id, ps.calendar_id, old_date)
            invalidate_freebusy_cache(
                booking.provider_id, ps.calendar_id, gcal_start.date().isoformat()
            )

    logger.info("reconcile_bookings_with_gcal: reconciliation complete.")
