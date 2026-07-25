from django.contrib import admin

from apps.payments.models import PaymentOrder


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = ["mock_order_id", "booking", "status", "amount_paise", "expires_at"]
    list_filter = ["status"]
    search_fields = ["mock_order_id", "booking__email"]
