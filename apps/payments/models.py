from django.db import models

from apps.payments.constants import PaymentStatus
from common.models.base import UUIDModel


class PaymentOrder(UUIDModel):
    mock_order_id = models.CharField(max_length=64, unique=True)
    mock_payment_id = models.CharField(max_length=64, blank=True)
    mock_signature = models.CharField(max_length=256, blank=True)

    booking = models.OneToOneField(
        "calendar_app.Booking", on_delete=models.CASCADE, related_name="payment"
    )
    session_key = models.UUIDField(db_index=True)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(
        choices=PaymentStatus.choices, default=PaymentStatus.CREATED, max_length=20
    )
    payment_url = models.URLField()
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["mock_order_id"], name="payments_po_orderid_idx"),
            models.Index(fields=["session_key"], name="payments_po_session_idx"),
            models.Index(fields=["status", "expires_at"], name="payments_po_status_exp_idx"),
        ]

    def __str__(self):
        return f"PaymentOrder({self.mock_order_id}, status={self.status})"
