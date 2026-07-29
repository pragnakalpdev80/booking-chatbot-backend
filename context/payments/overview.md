# Context — `apps/payments/`

## Purpose

The `payments` app provides a mock payment gateway integration for providers who require a mandatory deposit or booking fee before securing an appointment on their calendar.

## Key Models (`models.py`)

- `PaymentOrder`: Represents a financial transaction tied to a `Booking` or `session_key`. Tracks amount (`amount_paise`), currency, external mock identifiers (`mock_order_id`, `mock_payment_id`), and status (Created, Paid, Failed).

## Key Endpoints (`/api/payments/`)

- `POST /orders/` (`CreatePaymentOrderView`) — Generates a new `PaymentOrder` and returns a mock payment URL for the frontend to render.
- `GET /orders/<str:order_id>/status/` (`PaymentOrderStatusView`) — Polling endpoint used by the frontend to verify if a payment has been completed.
- `POST /webhook/` (`PaymentWebhookView`) — Receives mock asynchronous webhook callbacks to confirm successful transactions.

## Design Decisions

- **Two-Step Booking**: When `ProviderSettings.payment_required` is true, the `calendar_app` places a `SlotLock` and returns a "pending_payment" state instead of confirming the booking. The chatbot frontend then invokes the payment flow, and only upon receiving the webhook does the booking convert to a Confirmed state (dispatching the Celery task to insert to Google Calendar).
