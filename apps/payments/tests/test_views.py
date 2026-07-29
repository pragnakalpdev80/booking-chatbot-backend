import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.calendar_app.models import ProviderSettings, SlotLock
from apps.chatbot.models import ConversationSession
from apps.payments.constants import PaymentStatus
from apps.payments.services.order_service import PaymentOrderService


@pytest.fixture
def api_client():
    return APIClient()


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


@pytest.fixture
def payment_order(db, session, slot_lock):
    return PaymentOrderService(actor=session.provider).create(
        session, slot_lock.slot_start, "Checkup"
    )


@pytest.mark.django_db
class TestPaymentAPI:
    def test_create_order(self, api_client, session, slot_lock):
        url = reverse("payments_order_create")
        data = {
            "session_key": str(session.session_key),
            "start_time": slot_lock.slot_start.isoformat(),
            "reason": "Checkup",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert "order_id" in response.data["data"]
        assert "payment_url" in response.data["data"]

    def test_create_order_without_lock(self, api_client, session):
        url = reverse("payments_order_create")
        data = {
            "session_key": str(session.session_key),
            "start_time": (now() + timedelta(days=1)).isoformat(),
            "reason": "Checkup",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_order_status(self, api_client, payment_order):
        url = reverse("payments_order_status", kwargs={"order_id": payment_order.mock_order_id})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["status"] == PaymentStatus.CREATED
        assert response.data["data"]["amount_paise"] == 10000

    def test_get_order_status_not_found(self, api_client):
        url = reverse("payments_order_status", kwargs={"order_id": "invalid"})
        response = api_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @patch("apps.payments.services.webhook_service.finalize_booking_task.delay")
    def test_webhook_success(self, mock_delay, api_client, payment_order):
        url = reverse("payments_webhook_handle")
        data = {
            "event": "payment.captured",
            "order_id": payment_order.mock_order_id,
            "payment_id": "mock_pay_123",
            "signature": "mock_sig_valid",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_200_OK
        payment_order.refresh_from_db()
        assert payment_order.status == PaymentStatus.PAID
        mock_delay.assert_called_once_with(payment_order.pk)

    def test_webhook_bad_signature(self, api_client, payment_order):
        url = reverse("payments_webhook_handle")
        data = {
            "event": "payment.captured",
            "order_id": payment_order.mock_order_id,
            "payment_id": "mock_pay_123",
            "signature": "bad_sig",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
