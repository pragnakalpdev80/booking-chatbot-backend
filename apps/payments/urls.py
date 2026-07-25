from django.urls import path

from apps.payments.views import (
    CreatePaymentOrderView,
    PaymentOrderStatusView,
    PaymentWebhookView,
)

urlpatterns = [
    path("orders/", CreatePaymentOrderView.as_view(), name="payments_order_create"),
    path(
        "orders/<str:order_id>/status/",
        PaymentOrderStatusView.as_view(),
        name="payments_order_status",
    ),
    path("webhook/", PaymentWebhookView.as_view(), name="payments_webhook_handle"),
]
