import logging

from django.utils.timezone import now

from apps.calendar_app.models import BookingStatus, SlotLock
from apps.payments import messages
from apps.payments.constants import PaymentStatus
from apps.payments.models import PaymentOrder
from apps.payments.tasks import finalize_booking_task
from common.api.exceptions import ApplicationError

logger = logging.getLogger(__name__)


class PaymentWebhookService:
    def __init__(self, actor=None, **kwargs):
        pass

    def handle_success(self, order_id: str, payment_id: str, signature: str) -> None:
        """Mark order as paid and dispatch Celery task for GCal write (CLAUDE.md §2.5)."""
        order = self._get_order(order_id)

        if order.status == PaymentStatus.PAID:
            logger.info("Ignored duplicate webhook success for already PAID order %s", order_id)
            return  # idempotent

        if order.status == PaymentStatus.EXPIRED or order.expires_at <= now():
            logger.warning("Payment webhook failed: order %s is expired", order_id)
            raise ApplicationError(messages.ORDER_EXPIRED, status_code=400)

        if signature != "mock_sig_valid":
            logger.warning("Payment webhook failed: invalid signature for order %s", order_id)
            raise ApplicationError(messages.INVALID_SIGNATURE, status_code=403)

        order.mock_payment_id = payment_id
        order.mock_signature = signature
        order.status = PaymentStatus.PAID
        order.save(update_fields=["mock_payment_id", "mock_signature", "status", "updated_at"])

        logger.info(
            "Payment successful for order %s (payment_id=%s). Dispatching finalize_booking_task",
            order_id,
            payment_id,
        )

        # CLAUDE.md §2.5 — all GCal writes must be async via Celery
        finalize_booking_task.delay(order.pk)

    def handle_failure(self, order_id: str, reason: str) -> None:
        order = self._get_order(order_id)

        if order.status in [PaymentStatus.PAID, PaymentStatus.FAILED]:
            logger.info(
                "Ignored webhook failure for order %s with status %s", order_id, order.status
            )
            return

        logger.warning(
            "Payment failed for order %s (reason: %s). Updating status to FAILED", order_id, reason
        )

        order.status = PaymentStatus.FAILED
        order.save(update_fields=["status", "updated_at"])

        booking = order.booking
        booking.status = BookingStatus.FAILED
        booking.save(update_fields=["status", "updated_at"])

        # Release the slot lock so others can book
        deleted_count, _ = SlotLock.objects.filter(
            session_key=order.session_key,
            slot_start=booking.start_time,
            is_confirmed=False,
        ).delete()
        logger.info(
            "Released %d SlotLock(s) for session %s after payment failure",
            deleted_count,
            order.session_key,
        )

    def _get_order(self, order_id: str) -> PaymentOrder:
        try:
            return PaymentOrder.objects.select_related("booking").get(mock_order_id=order_id)
        except PaymentOrder.DoesNotExist:
            logger.warning("Payment order not found: %s", order_id)
            raise ApplicationError(messages.ORDER_NOT_FOUND, status_code=404)
