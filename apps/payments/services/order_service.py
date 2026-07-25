import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils.timezone import now

from apps.calendar_app.models import Booking, BookingStatus, ProviderSettings, SlotLock
from apps.chatbot.models import ConversationSession
from apps.payments import messages
from apps.payments.constants import PaymentStatus
from apps.payments.models import PaymentOrder
from common.api.exceptions import ApplicationError
from common.services.base import BaseService


class PaymentOrderService(BaseService):
    def create(
        self,
        session: ConversationSession,
        start_time: datetime,
        reason: str,
    ) -> PaymentOrder:
        # 1. Guard: email must be set on session
        if not session.user_email:
            raise ApplicationError(messages.EMAIL_NOT_COLLECTED, status_code=400)

        # 2. Guard: active SlotLock must exist for this session + slot
        lock = SlotLock.objects.filter(
            session_key=session.session_key,
            slot_start=start_time,
            expires_at__gt=now(),
            is_confirmed=False,
        ).first()
        if not lock:
            raise ApplicationError(messages.SLOT_LOCK_NOT_FOUND, status_code=400)

        # Check for idempotency: if an order already exists for this lock, return it
        existing_order = PaymentOrder.objects.filter(
            session_key=session.session_key,
            booking__start_time=start_time,
            status=PaymentStatus.CREATED,
            expires_at__gt=now(),
        ).first()
        if existing_order:
            return existing_order

        assert session.provider is not None
        ps = ProviderSettings.get_for_provider(session.provider)

        # 3. Generate order ID and payment URL
        mock_order_id = f"mock_ord_{uuid.uuid4().hex[:16]}"
        payment_url = (
            f"{getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')}/mock-pay/{mock_order_id}"
        )
        expires_at = now() + timedelta(minutes=10)

        # 4. Create Booking with PENDING_PAYMENT (no GCal event yet)
        end_time = start_time + timedelta(minutes=30)
        booking = Booking.objects.create(
            email=session.user_email,
            provider=session.provider,
            google_event_id=f"pending_{mock_order_id}",  # filled by webhook on success
            start_time=start_time,
            end_time=end_time,
            reason=reason,
            status=BookingStatus.PENDING_PAYMENT,
        )

        # 5. Extend existing SlotLock TTL to match payment window
        lock.expires_at = expires_at
        lock.save(update_fields=["expires_at"])

        # 6. Create PaymentOrder
        return PaymentOrder.objects.create(
            mock_order_id=mock_order_id,
            booking=booking,
            session_key=session.session_key,
            amount_paise=ps.booking_fee_paise,
            payment_url=payment_url,
            expires_at=expires_at,
        )
