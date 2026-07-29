from rest_framework import serializers


class PaymentOrderCreateSerializer(serializers.Serializer):
    session_key = serializers.UUIDField(required=True)
    start_time = serializers.DateTimeField(required=True)
    reason = serializers.CharField(allow_blank=True, required=False, default="")


class BookingStatusSerializer(serializers.Serializer):
    """Minimal booking info embedded in the order-status response."""

    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    reason = serializers.CharField()
    status = serializers.CharField()


class PaymentOrderStatusSerializer(serializers.Serializer):
    mock_order_id = serializers.CharField()
    status = serializers.CharField()
    amount_paise = serializers.IntegerField()
    expires_at = serializers.DateTimeField()
    # Included only after payment is confirmed
    booking = serializers.SerializerMethodField()
    provider_slug = serializers.SerializerMethodField()

    def get_provider_slug(self, obj):
        if obj.booking and obj.booking.provider:
            return obj.booking.provider.username
        return None

    def get_booking(self, obj):  # noqa: D102
        if obj.booking and obj.booking.pk:
            return BookingStatusSerializer(obj.booking).data
        return None


class WebhookEventSerializer(serializers.Serializer):
    EVENT_CHOICES = (
        ("payment.captured", "Payment Captured"),
        ("payment.failed", "Payment Failed"),
    )
    event = serializers.ChoiceField(choices=EVENT_CHOICES, required=True)
    order_id = serializers.CharField(required=True)
    payment_id = serializers.CharField(required=False, allow_blank=True)
    signature = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)
