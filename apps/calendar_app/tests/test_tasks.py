import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils.timezone import now
from googleapiclient.errors import HttpError

from apps.calendar_app.models import (
    Booking,
    BookingStatus,
    GoogleCredential,
    ProviderSettings,
    SlotLock,
)
from apps.calendar_app.tasks import (
    cleanup_expired_locks,
    task_cancel_event,
    task_insert_event,
    task_patch_event,
)


@pytest.fixture
def booking(db, user):
    ProviderSettings.objects.create(user=user, payment_required=False)
    cred = GoogleCredential(user=user)
    cred.token = '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "uri"}'  # noqa: E501
    cred.save()
    return Booking.objects.create(
        provider=user,
        email="test@example.com",
        start_time=now() + timedelta(days=1),
        end_time=now() + timedelta(days=1, minutes=30),
        status=BookingStatus.CONFIRMED,
        google_event_id="existing_id",
    )


@pytest.mark.django_db
class TestCalendarTasks:
    @patch("apps.calendar_app.tasks._get_service")
    def test_insert_event_success(self, mock_get_gcal, booking):
        booking.google_event_id = ""
        booking.save()

        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service
        mock_service.events().insert().execute.return_value = {"id": "new_id"}

        event = task_insert_event({"summary": "test"}, booking.provider_id)
        assert event["id"] == "new_id"

    @patch("apps.calendar_app.tasks._get_service")
    @patch("apps.calendar_app.tasks.task_insert_event.retry")
    def test_insert_event_http_error(self, mock_retry, mock_get_gcal, booking):
        booking.google_event_id = ""
        booking.save()

        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 500
        exc = HttpError(mock_resp, b"error")
        mock_service.events().insert().execute.side_effect = exc

        mock_retry.side_effect = Exception("Retry Triggered")
        with pytest.raises(Exception, match="Retry Triggered"):
            task_insert_event({"summary": "test"}, booking.provider_id)

    @patch("apps.calendar_app.tasks._get_service")
    def test_patch_event_success(self, mock_get_gcal, booking):
        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service

        task_patch_event("existing_id", {}, booking.provider_id)
        mock_service.events().patch().execute.assert_called_once()

    @patch("apps.calendar_app.tasks._get_service")
    @patch("apps.calendar_app.tasks.task_patch_event.retry")
    def test_patch_event_http_error(self, mock_retry, mock_get_gcal, booking):
        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 500
        exc = HttpError(mock_resp, b"error")
        mock_service.events().patch().execute.side_effect = exc

        mock_retry.side_effect = Exception("Retry Triggered")
        with pytest.raises(Exception, match="Retry Triggered"):
            task_patch_event("existing_id", {}, booking.provider_id)

    @patch("apps.calendar_app.tasks._get_service")
    def test_cancel_event_success(self, mock_get_gcal, booking):
        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service

        task_cancel_event("existing_id", booking.provider_id)
        mock_service.events().delete().execute.assert_called_once()

    @patch("apps.calendar_app.tasks._get_service")
    @patch("apps.calendar_app.tasks.task_cancel_event.retry")
    def test_cancel_event_http_error(self, mock_retry, mock_get_gcal, booking):
        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 500
        exc = HttpError(mock_resp, b"error")
        mock_service.events().delete().execute.side_effect = exc

        mock_retry.side_effect = Exception("Retry Triggered")
        with pytest.raises(Exception, match="Retry Triggered"):
            task_cancel_event("existing_id", booking.provider_id)

    def test_cleanup_expired_locks(self, user):
        # Create an expired lock and an active lock on different slots to avoid
        # the unique-constraint collision between the two unconfirmed rows.
        expired_lock = SlotLock.objects.create(
            provider=user,
            session_key=str(uuid.uuid4()),
            slot_start=now() + timedelta(hours=1),
            slot_end=now() + timedelta(hours=1, minutes=30),
            expires_at=now() - timedelta(minutes=5),
            is_confirmed=False,
        )
        active_lock = SlotLock.objects.create(
            provider=user,
            session_key=str(uuid.uuid4()),
            slot_start=now() + timedelta(hours=2),
            slot_end=now() + timedelta(hours=2, minutes=30),
            expires_at=now() + timedelta(minutes=15),
            is_confirmed=False,
        )

        cleanup_expired_locks()

        # Both rows must still exist — no hard-delete
        assert SlotLock.objects.count() == 2

        expired_lock.refresh_from_db()
        active_lock.refresh_from_db()

        # Expired lock is now soft-expired
        assert expired_lock.is_expired is True
        # Active lock is untouched
        assert active_lock.is_expired is False
