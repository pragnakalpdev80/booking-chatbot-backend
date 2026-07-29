import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.chatbot.models import ConversationSession
from apps.payments.models import PaymentOrder
from apps.payments.serializers import (
    PaymentOrderCreateSerializer,
    PaymentOrderStatusSerializer,
    WebhookEventSerializer,
)
from apps.payments.services.order_service import PaymentOrderService
from apps.payments.services.webhook_service import PaymentWebhookService
from common.api.exceptions import ApplicationError
from common.api.response import ApiResponse

logger = logging.getLogger(__name__)


class CreatePaymentOrderView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PaymentOrderCreateSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("CreatePaymentOrderView validation failed: %s", serializer.errors)
            return ApiResponse(
                data=serializer.errors, message="Invalid data", status=status.HTTP_400_BAD_REQUEST
            )

        session_key = serializer.validated_data["session_key"]
        try:
            session = ConversationSession.objects.get(session_key=session_key)
        except ConversationSession.DoesNotExist:
            logger.warning("CreatePaymentOrderView: Session not found (%s)", session_key)
            return ApiResponse(message="Session not found", status=status.HTTP_404_NOT_FOUND)

        try:
            order = PaymentOrderService(actor=session.provider).create(
                session=session,
                start_time=serializer.validated_data["start_time"],
                reason=serializer.validated_data.get("reason", ""),
            )
        except ApplicationError as exc:
            logger.warning(
                "CreatePaymentOrderView error: %s (status %d)", str(exc), exc.status_code
            )
            return ApiResponse(message=str(exc), status=exc.status_code)

        logger.info("Payment order %s successfully created via API", order.mock_order_id)
        return ApiResponse(
            data={
                "order_id": order.mock_order_id,
                "payment_url": order.payment_url,
                "amount_paise": order.amount_paise,
                "expires_at": order.expires_at.isoformat(),
            },
            message="Payment order created",
            status=status.HTTP_201_CREATED,
        )


class PaymentOrderStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, order_id):
        try:
            order = PaymentOrder.objects.select_related("booking").get(mock_order_id=order_id)
        except PaymentOrder.DoesNotExist:
            logger.warning("PaymentOrderStatusView: Order %s not found", order_id)
            return ApiResponse(message="Order not found", status=status.HTTP_404_NOT_FOUND)

        serializer = PaymentOrderStatusSerializer(order)
        return ApiResponse(data=serializer.data, message="Order status retrieved")


class PaymentWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = WebhookEventSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("PaymentWebhookView validation failed: %s", serializer.errors)
            return ApiResponse(
                data=serializer.errors,
                message="Invalid webhook data",
                status=status.HTTP_400_BAD_REQUEST,
            )

        event = serializer.validated_data["event"]
        order_id = serializer.validated_data["order_id"]

        logger.info("PaymentWebhookView received event '%s' for order %s", event, order_id)

        service = PaymentWebhookService()

        try:
            if event == "payment.captured":
                service.handle_success(
                    order_id=order_id,
                    payment_id=serializer.validated_data.get("payment_id", ""),
                    signature=serializer.validated_data.get("signature", ""),
                )
            elif event == "payment.failed":
                service.handle_failure(
                    order_id=order_id,
                    reason=serializer.validated_data.get("reason", ""),
                )
        except ApplicationError as exc:
            logger.warning("PaymentWebhookView error for order %s: %s", order_id, str(exc))
            return ApiResponse(message=str(exc), status=exc.status_code)

        return ApiResponse(message="Webhook processed successfully")
