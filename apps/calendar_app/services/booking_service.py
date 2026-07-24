import logging
from datetime import datetime, timedelta

from django.contrib.auth.models import User
from googleapiclient.errors import HttpError

from apps.calendar_app.models import Booking, BookingStatus, ProviderSettings
from apps.calendar_app.tasks import task_cancel_event, task_patch_event
from apps.calendar_app.utils import (
    SLOT_DURATION_MINUTES,
    _build_service,
    _check_freebusy,
    _get_admin_credential,
)
from common.api.exceptions import ApplicationError
from common.services.base import BaseService

logger = logging.getLogger(__name__)


class BookingService(BaseService):
    @classmethod
    def book_appointment(
        cls, email: str, name: str, start_time: datetime, reason: str, provider: User
    ) -> dict:
        ps = ProviderSettings.get_for_provider(provider)

        if start_time.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            raise ApplicationError(
                "Appointments are only available Monday to Friday.", status_code=400
            )

        try:
            cred = _get_admin_credential(provider)
            service = _build_service(cred)
        except RuntimeError as exc:
            raise ApplicationError(str(exc), status_code=503) from exc

        if not _check_freebusy(
            service,
            start_time,
            start_time + timedelta(minutes=SLOT_DURATION_MINUTES),
            ps.calendar_id,
        ):
            raise ApplicationError(
                "The requested slot is not available. Please choose another time.", status_code=409
            )

        event_body = {
            "summary": f"Appointment: {name or email}",
            "description": f"Reason: {reason}",
            "start": {"dateTime": start_time.isoformat(), "timeZone": ps.timezone},
            "end": {
                "dateTime": (start_time + timedelta(minutes=SLOT_DURATION_MINUTES)).isoformat(),
                "timeZone": ps.timezone,
            },
            "attendees": [{"email": email}],
        }

        try:
            created_event = (
                service.events().insert(calendarId=ps.calendar_id, body=event_body).execute()
            )
        except HttpError as exc:
            logger.exception("events.insert failed: %s", exc)
            raise ApplicationError(str(exc), status_code=502) from exc

        google_event_id = created_event["id"]

        booking = Booking.objects.create(
            provider=provider,
            email=email,
            name=name,
            reason=reason,
            start_time=start_time,
            end_time=start_time + timedelta(minutes=SLOT_DURATION_MINUTES),
            google_event_id=google_event_id,
            status=BookingStatus.CONFIRMED,
        )

        logger.info("Booking created: email=%s event=%s", email, google_event_id)

        return {
            "booking_id": booking.pk,
            "google_event_id": google_event_id,
            "status": booking.status,
        }

    @classmethod
    def reschedule_appointment(cls, email: str, event_id: str, new_start_time: datetime) -> Booking:
        try:
            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist as exc:
            raise ApplicationError(
                "Booking not found for this email and event ID.", status_code=404
            ) from exc

        assert booking.provider is not None
        ps = ProviderSettings.get_for_provider(booking.provider)
        if new_start_time.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            raise ApplicationError(
                "Appointments are only available Monday to Friday.", status_code=400
            )

        try:
            cred = _get_admin_credential(booking.provider)
            service = _build_service(cred)
        except RuntimeError as exc:
            raise ApplicationError(str(exc), status_code=503) from exc

        if not _check_freebusy(
            service,
            new_start_time,
            new_start_time + timedelta(minutes=SLOT_DURATION_MINUTES),
            ps.calendar_id,
        ):
            raise ApplicationError("The requested new slot is not available.", status_code=409)

        patch_body = {
            "start": {"dateTime": new_start_time.isoformat(), "timeZone": ps.timezone},
            "end": {
                "dateTime": (new_start_time + timedelta(minutes=SLOT_DURATION_MINUTES)).isoformat(),
                "timeZone": ps.timezone,
            },
        }

        task_patch_event.delay(event_id, patch_body, booking.provider_id)

        booking.start_time = new_start_time
        booking.end_time = new_start_time + timedelta(minutes=SLOT_DURATION_MINUTES)
        booking.status = BookingStatus.RESCHEDULED
        booking.save(update_fields=["start_time", "end_time", "status", "updated_at"])

        logger.info(
            "Booking rescheduled: email=%s event=%s -> %s",
            email,
            event_id,
            new_start_time.isoformat(),
        )
        return booking

    @classmethod
    def cancel_appointment(cls, email: str, event_id: str) -> None:
        try:
            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist as exc:
            raise ApplicationError(
                "Booking not found for this email and event ID.", status_code=404
            ) from exc

        assert booking.provider is not None
        task_cancel_event.delay(event_id, booking.provider_id)

        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status", "updated_at"])

        logger.info("Booking cancelled: email=%s event=%s", email, event_id)
