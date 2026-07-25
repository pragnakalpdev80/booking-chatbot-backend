# Payments App Overview

> **Namespace:** `apps.payments`
> **Purpose:** Handles mock payment processing, order generation, and asynchronous booking finalization via webhooks. Designed to emulate standard integrations like Razorpay.

---

## 1. Core Responsibilities

The `payments` app provides a self-contained mock payment flow to finalize appointment bookings when a provider requires a fee. It uses `SlotLock` records to temporarily reserve time, issues a payment URL to the frontend, and finalizes the Google Calendar interaction asynchronously upon payment success.

---

## 2. Models

### `PaymentOrder`
Stores the metadata for a payment attempt.

```python
class PaymentOrder(models.Model):
    STATUS_CHOICES = [
        ("created", "Created"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("expired", "Expired"),
    ]
    mock_order_id = models.CharField(max_length=50, unique=True)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    amount_paise = models.IntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="created")
    payment_url = models.URLField()
```

---

## 3. Services

Business logic is strictly decoupled from the views:

- **`PaymentOrderService`**: Handles `create()`. It verifies that a valid `SlotLock` exists, creates a `PENDING_PAYMENT` booking in the database (without writing to Google Calendar), extends the lock duration, and returns an idempotent `PaymentOrder`.
- **`PaymentWebhookService`**: Handles incoming payment triggers from the simulated provider.
  - On `success`, it delegates Google Calendar writes to a Celery task.
  - On `failure`, it cancels the booking and deletes the `SlotLock`.

---

## 4. Endpoints & Views

| Endpoint | Method | Payload / Action |
|----------|--------|------------------|
| `/api/v1/payments/orders/` | `POST` | Generates a new `PaymentOrder` and pending booking. Requires active `SlotLock`. |
| `/api/v1/payments/orders/<id>/status/` | `GET` | Polling endpoint for the frontend to check if a mock order has transitioned to `paid`. |
| `/api/v1/payments/webhook/` | `POST` | Receives simulated mock provider events (e.g., `payment.success` or `payment.failed`). |

---

## 5. Asynchronous Finalization

To ensure 100% adherence to asynchronous Google Calendar writes (`CLAUDE.md §2.5`), the `payments` app uses Celery.

**`finalize_booking_task`**: Triggered by the webhook on payment success. It:
1. Queries the database for the `PENDING_PAYMENT` booking.
2. Performs the `events().insert` call to Google Calendar.
3. Updates the `booking.google_event_id` and changes the status to `CONFIRMED`.
