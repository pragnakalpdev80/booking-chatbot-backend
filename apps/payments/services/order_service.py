import logging
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

logger = logging.getLogger(__name__)


class PaymentOrderService(BaseService):
    def create(
        self,
        session: ConversationSession,
        start_time: datetime,
        reason: str,
    ) -> PaymentOrder:
        # 1. Guard: email must be set on session
        if not session.user_email:
            logger.warning(
                "Failed to create PaymentOrder: email not collected for session %s",
                session.session_key,
            )
            raise ApplicationError(messages.EMAIL_NOT_COLLECTED, status_code=400)

        # 2. Guard: active SlotLock must exist for this session + slot
        lock = SlotLock.objects.filter(
            session_key=session.session_key,
            slot_start=start_time,
            expires_at__gt=now(),
            is_confirmed=False,
        ).first()
        if not lock:
            logger.warning(
                "Failed to create PaymentOrder: no active lock found for session %s slot %s",
                session.session_key,
                start_time,
            )
            raise ApplicationError(
                "EXPIRED_LOCK: The 15-minute reservation for this slot has EXPIRED "
                "and the slot is no longer held. Inform the user their reservation timed out. "
                "Ask if they still want this slot and, if so, call lock_slot again to "
                "re-secure it before proceeding to confirm.",
                status_code=400,
            )

        # Check for idempotency: if an order already exists for this lock, return it
        existing_order = PaymentOrder.objects.filter(
            session_key=session.session_key,
            booking__start_time=start_time,
            status=PaymentStatus.CREATED,
            expires_at__gt=now(),
        ).first()
        if existing_order:
            logger.info(
                "Returning existing active PaymentOrder %s for session %s",
                existing_order.mock_order_id,
                session.session_key,
            )
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
        order = PaymentOrder.objects.create(
            mock_order_id=mock_order_id,
            booking=booking,
            session_key=session.session_key,
            amount_paise=ps.booking_fee_paise,
            payment_url=payment_url,
            expires_at=expires_at,
        )
        logger.info(
            "Created PaymentOrder %s for session %s (amount: %d paise, expires: %s)",
            mock_order_id,
            session.session_key,
            order.amount_paise,
            expires_at.isoformat(),
        )
        return order
