# calendar_app/models.py
"""
Models for the calendar_app.

GoogleCredential  — single-record table for the admin's OAuth token (encrypted).
ProviderSettings  — singleton model for admin-configurable working hours / scheduling config.
Booking           — lightweight reference table linking an anonymous user (email) to a Google
                    Calendar event ID. Google Calendar is the source of truth for event details;
                    this model only tracks the reference + status.
"""

import json
import logging

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils.text import slugify
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


# ─── Encryption helpers ───────────────────────────────────────────────────────


def _fernet() -> Fernet:
    """Return a Fernet instance using the FERNET_KEY from settings."""
    key = getattr(settings, "FERNET_KEY", None)
    if not key:
        raise RuntimeError("FERNET_KEY is not set in settings. Cannot encrypt credential tokens.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()


# ─── GoogleCredential ─────────────────────────────────────────────────────────


class GoogleCredential(models.Model):
    """
    Stores the admin/owner's Google OAuth2 token (encrypted at rest).

    There should be only ONE row in this table — created once by the admin
    via the /api/calendar/login/ → /api/calendar/oauth2callback/ flow.
    Never create per-user GoogleCredential records.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="google_credential",
        help_text="The admin user who owns this Google Calendar connection.",
    )
    # Stored as Fernet-encrypted ciphertext of the JSON token string
    token = models.TextField(help_text="Encrypted Google OAuth2 token JSON.")
    token_updated_at = models.DateTimeField(auto_now=True)
    scope = models.TextField(
        blank=True,
        default="",
        help_text="Space-separated OAuth scopes granted.",
    )

    class Meta:
        verbose_name = "Google Credential"
        verbose_name_plural = "Google Credentials"

    def __str__(self) -> str:
        return f"GoogleCredential(user={self.user.username})"

    # ── Token helpers ──────────────────────────────────────────────────────────

    def set_token(self, token_json: str) -> None:
        """Encrypt and persist the raw JSON token string."""
        self.token = encrypt_token(token_json)

    def get_token_json(self) -> str:
        """Decrypt and return the raw JSON token string."""
        return decrypt_token(self.token)

    def get_credentials(self) -> Credentials:
        """Return a google.oauth2.credentials.Credentials object, auto-refreshing if needed."""
        creds = Credentials.from_authorized_user_info(json.loads(self.get_token_json()))

        if creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Google OAuth session for user %s", self.user.username)
            creds.refresh(Request())
            self.set_token(creds.to_json())
            self.save(update_fields=["token", "token_updated_at"])
            logger.info("Session refreshed and persisted for user %s", self.user.username)

        return creds


# ─── ProviderSettings ─────────────────────────────────────────────────────────


class ProviderSettings(models.Model):
    """
    Singleton assumption has been removed — there is ONE row per provider.
    Stores the provider's working hours and scheduling metadata.
    Editable via Django admin or the provider portal.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="provider_settings",
        help_text="The doctor/provider who owns these settings.",
    )
    slug = models.SlugField(
        max_length=100,
        unique=True,
        help_text="URL-safe identifier, e.g. 'drsmith'. Auto-populated from username.",
    )
    calendar_id = models.CharField(
        max_length=255,
        default="primary",
        help_text=(
            "The Google Calendar ID used for bookings "
            "(e.g. 'primary' or 'abc@group.calendar.google.com')."
        ),
    )

    provider_name = models.CharField(
        max_length=255,
        default="Dr. Smith",
        help_text="Service/provider name — injected into the chatbot system prompt.",
    )

    day_schedules = models.JSONField(
        default=dict,
        help_text="Per-day working hours. Keys are weekday strings '0'–'6'.",
    )

    class SlotDurationChoices(models.IntegerChoices):
        MIN_15 = 15, "15 Minutes"
        MIN_30 = 30, "30 Minutes"
        MIN_45 = 45, "45 Minutes"
        MIN_60 = 60, "60 Minutes"

    slot_duration = models.IntegerField(
        choices=SlotDurationChoices.choices,
        default=SlotDurationChoices.MIN_30,
        help_text="Appointment slot duration in minutes.",
    )
    timezone = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
        help_text="IANA timezone for the clinic (e.g. Asia/Kolkata, America/New_York).",
    )
    payment_required = models.BooleanField(
        default=False,
        help_text="If True, users must pay before Google Calendar slot is confirmed.",
    )
    booking_fee_paise = models.PositiveIntegerField(
        default=10000,
        help_text="Booking fee in paise (smallest INR unit). 10000 = ₹100.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Provider Settings"
        verbose_name_plural = "Provider Settings"

    def __str__(self) -> str:
        return f"ProviderSettings({self.provider_name})"

    @classmethod
    def get_for_provider(cls, user: User) -> "ProviderSettings":
        """
        Return the settings instance for a specific provider,
        creating a default if it doesn't exist.
        """
        default_schedule = {
            str(i): {
                "is_active": i < 5,
                "start": "09:00",
                "end": "17:00",
            }
            for i in range(7)
        }

        obj, _ = cls.objects.get_or_create(
            user=user,
            defaults={
                "slug": slugify(user.username),
                "provider_name": f"Dr. {user.last_name or user.username}",
                "calendar_id": "primary",
                "day_schedules": default_schedule,
                "slot_duration": cls.SlotDurationChoices.MIN_30,
                "timezone": "Asia/Kolkata",
                "payment_required": False,
                "booking_fee_paise": 10000,
            },
        )
        return obj


# ─── Settings Child Models ────────────────────────────────────────────────────


class BreakTime(models.Model):
    provider_settings = models.ForeignKey(
        ProviderSettings,
        on_delete=models.CASCADE,
        related_name="break_times",
    )
    weekday = models.IntegerField(
        choices=[(i, d) for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]
    )
    start = models.TimeField()
    end = models.TimeField()
    label = models.CharField(max_length=100, blank=True, default="Break")

    class Meta:
        ordering = ["weekday", "start"]

    def __str__(self) -> str:
        return f"{self.get_weekday_display()} Break ({self.start} - {self.end})"


class Holiday(models.Model):
    provider_settings = models.ForeignKey(
        ProviderSettings,
        on_delete=models.CASCADE,
        related_name="holidays",
    )
    date = models.DateField(db_index=True)
    label = models.CharField(max_length=255, blank=True, default="Holiday")

    class Meta:
        ordering = ["date"]
        unique_together = [("provider_settings", "date")]

    def __str__(self) -> str:
        return f"Holiday on {self.date}: {self.label}"


# ─── Booking ──────────────────────────────────────────────────────────────────


class BookingStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending Payment"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    RESCHEDULED = "rescheduled", "Rescheduled"
    FAILED = "failed", "Failed"


class Booking(models.Model):
    """
    Lightweight reference table that links an anonymous user (by email) to a
    Google Calendar event. Live event details are always fetched from the Google
    Calendar API; this model only tracks:
      - the email address used to book (primary anonymous identifier)
      - an optional display name for the calendar event title
      - the Google event ID (to make follow-up API calls)
      - start/end times (cached for quick listing without extra API calls)
      - booking status
    """

    email = models.EmailField(
        db_index=True,
        help_text="Email address of the anonymous user who made this booking.",
    )
    provider = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="bookings",
        help_text="The doctor/provider this appointment is booked with.",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional display name for the calendar event.",
    )
    google_event_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Google Calendar event ID — primary reference to the live event.",
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.TextField(
        blank=True,
        default="",
        help_text="Reason for the booking (user-supplied).",
    )
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.CONFIRMED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Booking"
        verbose_name_plural = "Bookings"
        ordering = ["-start_time"]

    def __str__(self) -> str:
        return f"Booking(email={self.email}, event={self.google_event_id}, status={self.status})"


# ─── SlotLock ─────────────────────────────────────────────────────────────────


class SlotLock(models.Model):
    """
    Temporary lock for a specific 30-minute time slot.
    Ensures that only one user can attempt to book a given slot at a time.
    Locks automatically expire after a set duration (e.g., 15 minutes).
    """

    # We use a soft reference to the session UUID string because calendar_app
    # doesn't depend on chatbot app (avoiding circular dependency).
    session_key = models.UUIDField(
        db_index=True,
        null=True,
        blank=True,
        help_text="The session key that holds this lock.",
    )
    provider = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="slot_locks",
        null=True,
        help_text="The doctor/provider this slot lock is for.",
    )
    slot_start = models.DateTimeField(db_index=True)
    slot_end = models.DateTimeField()
    expires_at = models.DateTimeField(db_index=True)
    locked_at = models.DateTimeField(auto_now_add=True)
    is_confirmed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if the user successfully booked this slot. The lock is then ignored.",
    )

    class Meta:
        verbose_name = "Slot Lock"
        verbose_name_plural = "Slot Locks"
        ordering = ["-locked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["slot_start", "provider"],
                condition=models.Q(is_confirmed=False),
                name="unique_active_slot_lock_per_provider",
            )
        ]

    def __str__(self) -> str:
        return f"SlotLock(start={self.slot_start}, session={self.session_key})"
