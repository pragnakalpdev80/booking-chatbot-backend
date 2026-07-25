from django.utils.timezone import now

from apps.calendar_app.models import BookingStatus, SlotLock
from apps.payments import messages
from apps.payments.constants import PaymentStatus
from apps.payments.models import PaymentOrder
from apps.payments.tasks import finalize_booking_task
from common.api.exceptions import ApplicationError
from common.services.base import BaseService


class PaymentWebhookService(BaseService):
    def handle_success(self, order_id: str, payment_id: str, signature: str) -> None:
        """Mark order as paid and dispatch Celery task for GCal write (CLAUDE.md §2.5)."""
        order = self._get_order(order_id)

        if order.status == PaymentStatus.PAID:
            return  # idempotent

        if order.status == PaymentStatus.EXPIRED or order.expires_at <= now():
            raise ApplicationError(messages.ORDER_EXPIRED, status_code=400)

        if signature != "mock_sig_valid":
            raise ApplicationError(messages.INVALID_SIGNATURE, status_code=403)

        order.mock_payment_id = payment_id
        order.mock_signature = signature
        order.status = PaymentStatus.PAID
        order.save(update_fields=["mock_payment_id", "mock_signature", "status", "updated_at"])

        # CLAUDE.md §2.5 — all GCal writes must be async via Celery
        finalize_booking_task.delay(order.pk)

    def handle_failure(self, order_id: str, reason: str) -> None:
        order = self._get_order(order_id)

        if order.status in [PaymentStatus.PAID, PaymentStatus.FAILED]:
            return

        order.status = PaymentStatus.FAILED
        order.save(update_fields=["status", "updated_at"])

        booking = order.booking
        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status", "updated_at"])

        # Release the slot lock so others can book
        SlotLock.objects.filter(
            session_key=order.session_key,
            slot_start=booking.start_time,
            is_confirmed=False,
        ).delete()

    def _get_order(self, order_id: str) -> PaymentOrder:
        try:
            return PaymentOrder.objects.select_related("booking").get(mock_order_id=order_id)
        except PaymentOrder.DoesNotExist:
            raise ApplicationError(messages.ORDER_NOT_FOUND, status_code=404)
