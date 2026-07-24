# calendar_app/models.py
"""
Models for the calendar_app.

GoogleCredential  — single-record table for the admin's OAuth token (encrypted).
ProviderSettings  — singleton model for admin-configurable working hours / scheduling config.
Booking           — lightweight reference table linking an anonymous user (email) to a Google
                    Calendar event ID. Google Calendar is the source of truth for event details;
                    this model only tracks the reference + status.
"""

import datetime
import json
import logging

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
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
    work_days = models.JSONField(
        default=list,
        help_text="List of weekday integers (0=Mon … 6=Sun) when the clinic is open.",
    )
    work_start = models.TimeField(
        default=datetime.time(9, 0),
        help_text="Start of working hours (local time).",
    )
    work_end = models.TimeField(
        default=datetime.time(17, 0),
        help_text="End of working hours (local time).",
    )
    slot_duration = models.IntegerField(
        default=30,
        help_text="Appointment slot duration in minutes. Always 30.",
    )
    timezone = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
        help_text="IANA timezone for the clinic (e.g. Asia/Kolkata, America/New_York).",
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
        obj, _ = cls.objects.get_or_create(
            user=user,
            defaults={
                "provider_name": f"Dr. {user.last_name or user.username}",
                "calendar_id": "primary",
                "work_days": [0, 1, 2, 3, 4],
                "work_start": datetime.time(9, 0),
                "work_end": datetime.time(17, 0),
                "slot_duration": 30,
                "timezone": "Asia/Kolkata",
            },
        )
        return obj


# ─── Booking ──────────────────────────────────────────────────────────────────


class BookingStatus(models.TextChoices):
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    RESCHEDULED = "rescheduled", "Rescheduled"


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
