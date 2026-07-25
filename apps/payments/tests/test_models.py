import uuid
from datetime import timedelta

import pytest
from django.utils.timezone import now

from apps.payments.constants import PaymentStatus
from apps.payments.models import PaymentOrder


@pytest.mark.django_db
class TestPaymentOrderModel:
    def test_payment_order_defaults(self, db, user):
        from apps.calendar_app.models import Booking

        booking = Booking.objects.create(
            email="test@example.com",
            provider=user,
            start_time=now(),
            end_time=now() + timedelta(minutes=30),
        )
        expires_at = now() + timedelta(minutes=10)

        order = PaymentOrder.objects.create(
            mock_order_id="mock_ord_123",
            booking=booking,
            session_key=uuid.uuid4(),
            amount_paise=10000,
            payment_url="http://localhost:5173/mock-pay/mock_ord_123",
            expires_at=expires_at,
        )

        assert order.status == PaymentStatus.CREATED
        assert order.currency == "INR"
        assert order.mock_payment_id == ""
        assert order.mock_signature == ""

    def test_payment_status_choices(self):
        assert PaymentStatus.CREATED == "created"
        assert PaymentStatus.PAID == "paid"
        assert PaymentStatus.FAILED == "failed"
        assert PaymentStatus.EXPIRED == "expired"
