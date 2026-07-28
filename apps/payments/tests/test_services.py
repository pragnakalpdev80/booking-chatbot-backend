import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils.timezone import now

from apps.calendar_app.models import Booking, BookingStatus, ProviderSettings, SlotLock
from apps.chatbot.models import ConversationSession
from apps.payments.constants import PaymentStatus
from apps.payments.services.order_service import PaymentOrderService
from apps.payments.services.webhook_service import PaymentWebhookService
from common.api.exceptions import ApplicationError


@pytest.fixture
def session(db, user):
    provider = user
    ProviderSettings.objects.create(user=provider, payment_required=True, booking_fee_paise=10000)
    return ConversationSession.objects.create(
        session_key=uuid.uuid4(), provider=provider, user_email="test@example.com"
    )


@pytest.fixture
def slot_lock(db, session):
    start = now() + timedelta(days=1)
    return SlotLock.objects.create(
        session_key=session.session_key,
        slot_start=start,
        slot_end=start + timedelta(minutes=30),
        expires_at=now() + timedelta(minutes=15),
        is_confirmed=False,
    )


@pytest.mark.django_db
class TestPaymentOrderService:
    def test_create_happy_path(self, session, slot_lock):
        start_time = slot_lock.slot_start
        order = PaymentOrderService().create(session, start_time, "Checkup")

        assert order.status == PaymentStatus.CREATED
        assert order.amount_paise == 10000
        assert "mock-pay/mock_ord_" in order.payment_url

        booking = Booking.objects.get(id=order.booking_id)
        assert booking.status == BookingStatus.PENDING_PAYMENT
        assert booking.email == "test@example.com"

        lock = SlotLock.objects.get(id=slot_lock.id)
        assert lock.expires_at > now() + timedelta(minutes=9)

    def test_create_no_active_slot_lock(self, session):
        start_time = now() + timedelta(days=1)
        service = PaymentOrderService()
        with pytest.raises(ApplicationError) as excinfo:
            service.create(session, start_time, "Checkup")
        assert excinfo.value.status_code == 400

    def test_create_expired_slot_lock(self, session, slot_lock):
        slot_lock.expires_at = now() - timedelta(minutes=1)
        slot_lock.save()
        service = PaymentOrderService()
        with pytest.raises(ApplicationError) as excinfo:
            service.create(session, slot_lock.slot_start, "Checkup")
        assert excinfo.value.status_code == 400

    def test_create_empty_email(self, session, slot_lock):
        session.user_email = ""
        session.save()
        service = PaymentOrderService()
        with pytest.raises(ApplicationError) as excinfo:
            service.create(session, slot_lock.slot_start, "Checkup")
        assert excinfo.value.status_code == 400

    def test_create_idempotency(self, session, slot_lock):
        start_time = slot_lock.slot_start
        order1 = PaymentOrderService().create(session, start_time, "Checkup")
        order2 = PaymentOrderService().create(session, start_time, "Checkup")
        assert order1.id == order2.id
        assert Booking.objects.count() == 1


@pytest.mark.django_db
class TestPaymentWebhookService:
    @pytest.fixture
    def payment_order(self, session, slot_lock):
        start_time = slot_lock.slot_start
        return PaymentOrderService().create(session, start_time, "Checkup")

    @patch("apps.payments.services.webhook_service.finalize_booking_task.delay")
    def test_handle_success(self, mock_delay, payment_order):
        service = PaymentWebhookService()
        service.handle_success(payment_order.mock_order_id, "mock_pay_123", "mock_sig_valid")

        payment_order.refresh_from_db()
        assert payment_order.status == PaymentStatus.PAID
        assert payment_order.mock_payment_id == "mock_pay_123"
        mock_delay.assert_called_once_with(payment_order.pk)

    def test_handle_failure(self, payment_order, slot_lock):
        service = PaymentWebhookService()
        service.handle_failure(payment_order.mock_order_id, "Declined")

        payment_order.refresh_from_db()
        assert payment_order.status == PaymentStatus.FAILED

        booking = payment_order.booking
        assert booking.status == BookingStatus.FAILED

        assert not SlotLock.objects.filter(id=slot_lock.id).exists()

    def test_handle_success_bad_signature(self, payment_order):
        service = PaymentWebhookService()
        with pytest.raises(ApplicationError) as excinfo:
            service.handle_success(payment_order.mock_order_id, "mock_pay_123", "bad_sig")
        assert excinfo.value.status_code == 403

    def test_handle_success_expired_order(self, payment_order):
        payment_order.expires_at = now() - timedelta(minutes=1)
        payment_order.save()
        service = PaymentWebhookService()
        with pytest.raises(ApplicationError) as excinfo:
            service.handle_success(payment_order.mock_order_id, "mock_pay_123", "mock_sig_valid")
        assert excinfo.value.status_code == 400

    def test_handle_success_unknown_order(self):
        service = PaymentWebhookService()
        with pytest.raises(ApplicationError) as excinfo:
            service.handle_success("unknown_id", "mock_pay_123", "mock_sig_valid")
        assert excinfo.value.status_code == 404

    @patch("apps.payments.services.webhook_service.finalize_booking_task.delay")
    def test_handle_success_idempotent(self, mock_delay, payment_order):
        service = PaymentWebhookService()
        service.handle_success(payment_order.mock_order_id, "mock_pay_123", "mock_sig_valid")
        mock_delay.assert_called_once()

        # Call again
        mock_delay.reset_mock()
        service.handle_success(payment_order.mock_order_id, "mock_pay_123", "mock_sig_valid")
        mock_delay.assert_not_called()
