import logging

from celery import shared_task
from django.db import transaction
from googleapiclient.errors import HttpError

from apps.calendar_app.models import BookingStatus, GoogleCredential, ProviderSettings, SlotLock
from apps.calendar_app.services.gcal_client import check_freebusy, get_gcal_service
from apps.payments.constants import PaymentStatus
from apps.payments.models import PaymentOrder

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def finalize_booking_task(self, payment_order_pk: int) -> None:
    logger.info("Starting finalize_booking_task for payment_order_pk=%d", payment_order_pk)
    order = PaymentOrder.objects.select_related("booking__provider").get(pk=payment_order_pk)
    booking = order.booking
    assert booking.provider is not None

    # Idempotency guard — skip if GCal event was already created.
    if booking.status == BookingStatus.CONFIRMED:
        logger.info(
            "finalize_booking_task skipped: booking %s is already CONFIRMED (order %d)",
            booking.id,
            payment_order_pk,
        )
        return

    ps = ProviderSettings.get_for_provider(booking.provider)

    try:
        service = get_gcal_service(booking.provider)
    except GoogleCredential.DoesNotExist:
        logger.error(
            "finalize_booking_task failed: Google account connection missing for provider %s (order %d)",
            booking.provider,
            payment_order_pk,
        )
        order.status = PaymentStatus.FAILED
        order.save(update_fields=["status", "updated_at"])
        return

    if not check_freebusy(service, booking.start_time, booking.end_time, ps.calendar_id):
        logger.warning(
            "finalize_booking_task failed: slot %s is busy on Google Calendar for provider %s",
            booking.start_time,
            booking.provider,
        )
        order.status = PaymentStatus.FAILED
        booking.status = BookingStatus.FAILED
        order.save(update_fields=["status", "updated_at"])
        booking.save(update_fields=["status", "updated_at"])
        return

    event_body = {
        "summary": f"Appointment: {booking.email}",
        "description": booking.reason,
        "start": {"dateTime": booking.start_time.isoformat(), "timeZone": ps.timezone},
        "end": {"dateTime": booking.end_time.isoformat(), "timeZone": ps.timezone},
        "attendees": [{"email": booking.email}],
    }
    try:
        created_event = (
            service.events().insert(calendarId=ps.calendar_id, body=event_body).execute()
        )
    except HttpError as exc:
        logger.error(
            "finalize_booking_task Google Calendar API insert error (attempt %d/%d): %s",
            self.request.retries + 1,
            self.max_retries,
            exc,
        )
        raise self.retry(exc=exc)

    with transaction.atomic():
        booking.google_event_id = created_event["id"]
        booking.status = BookingStatus.CONFIRMED
        booking.save(update_fields=["google_event_id", "status", "updated_at"])
        SlotLock.objects.filter(
            session_key=order.session_key,
            slot_start=booking.start_time,
            is_confirmed=False,
        ).update(is_confirmed=True)

    logger.info(
        "finalize_booking_task completed successfully for order %d! GCal Event ID: %s",
        payment_order_pk,
        created_event["id"],
    )
