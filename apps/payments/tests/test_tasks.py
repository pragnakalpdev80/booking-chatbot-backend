import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils.timezone import now
from googleapiclient.errors import HttpError

from apps.calendar_app.models import Booking, BookingStatus, GoogleCredential, ProviderSettings
from apps.payments.models import PaymentOrder, PaymentStatus
from apps.payments.tasks import finalize_booking_task


@pytest.fixture
def payment_order(db, user):
    ProviderSettings.objects.create(user=user, payment_required=True, booking_fee_paise=1000)
    booking = Booking.objects.create(
        provider=user,
        email="test@example.com",
        start_time=now() + timedelta(days=1),
        end_time=now() + timedelta(days=1, minutes=30),
        status=BookingStatus.PENDING_PAYMENT,
    )
    return PaymentOrder.objects.create(
        booking=booking,
        amount_paise=1000,
        status=PaymentStatus.PAID,
        mock_order_id=str(uuid.uuid4()),
        session_key=str(uuid.uuid4()),
        expires_at=now() + timedelta(minutes=15),
    )


@pytest.mark.django_db
class TestFinalizeBookingTask:
    @patch("apps.payments.tasks.get_gcal_service")
    def test_finalize_booking_success(self, mock_get_gcal, payment_order):
        cred = GoogleCredential(user=payment_order.booking.provider)
        cred.token = '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "uri"}'
        cred.save()

        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service
        mock_service.events().insert().execute.return_value = {"id": "new_google_event_id"}

        finalize_booking_task(payment_order.id)

        payment_order.booking.refresh_from_db()
        assert payment_order.booking.status == BookingStatus.CONFIRMED
        assert payment_order.booking.google_event_id == "new_google_event_id"

    def test_finalize_booking_order_not_found(self):
        # Should return silently
        assert finalize_booking_task(9999) is None

    def test_finalize_booking_not_paid(self, payment_order):
        payment_order.status = PaymentStatus.CREATED
        payment_order.save()
        assert finalize_booking_task(payment_order.id) is None

    @patch("apps.payments.tasks.logger.error")
    def test_finalize_booking_no_credentials(self, mock_logger, payment_order):
        # No GoogleCredential created
        finalize_booking_task(payment_order.id)

        payment_order.booking.refresh_from_db()
        assert payment_order.booking.status == BookingStatus.FAILED
        mock_logger.assert_called_once()

    @patch("apps.payments.tasks.get_gcal_service")
    @patch("apps.payments.tasks.finalize_booking_task.retry")
    def test_finalize_booking_http_error(self, mock_retry, mock_get_gcal, payment_order):
        cred = GoogleCredential(user=payment_order.booking.provider)
        cred.token = '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "u"}'
        cred.save()

        mock_service = MagicMock()
        mock_get_gcal.return_value = mock_service
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.reason = "Internal Server Error"
        exc = HttpError(mock_resp, b"error")
        mock_service.events().insert().execute.side_effect = exc

        mock_retry.side_effect = Exception("Retry Triggered")

        with pytest.raises(Exception, match="Retry Triggered"):
            finalize_booking_task(payment_order.id)

        mock_retry.assert_called_once_with(exc=exc)
